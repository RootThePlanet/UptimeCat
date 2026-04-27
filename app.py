"""
UptimeCat - Website uptime monitoring application.

Checks remote websites concurrently on a user-defined schedule and tracks
uptime history so it can be charted over the last 30/60/90 days.
"""

import sqlite3
import time
import threading
import concurrent.futures
from datetime import datetime, timezone

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, jsonify, redirect, render_template, request, url_for

# ---------------------------------------------------------------------------
# App / DB setup
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.config["DATABASE"] = "uptimecat.db"

_scheduler = BackgroundScheduler(daemon=True)
_scheduler_lock = threading.Lock()


def get_db():
    """Return a SQLite connection with row_factory set."""
    conn = sqlite3.connect(app.config["DATABASE"])
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create tables if they do not exist."""
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sites (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                name             TEXT    NOT NULL,
                url              TEXT    NOT NULL,
                check_interval   INTEGER NOT NULL DEFAULT 300,
                enabled          INTEGER NOT NULL DEFAULT 1,
                created_at       TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS checks (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id          INTEGER NOT NULL,
                is_up            INTEGER NOT NULL,
                status_code      INTEGER,
                response_time_ms REAL,
                error_message    TEXT,
                checked_at       TEXT    NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (site_id) REFERENCES sites(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_checks_site_checked
                ON checks(site_id, checked_at);
            """
        )


# ---------------------------------------------------------------------------
# Site-checking logic
# ---------------------------------------------------------------------------

REQUEST_TIMEOUT = 15  # seconds


def check_site(url: str) -> dict:
    """
    Perform a single HTTP GET for *url* and return a result dict with keys:
      is_up, status_code, response_time_ms, error_message.

    Follows redirects (including 301) automatically.
    """
    start = time.monotonic()
    try:
        resp = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
            headers={"User-Agent": "UptimeCat/1.0"},
        )
        elapsed_ms = (time.monotonic() - start) * 1000
        is_up = resp.status_code < 400
        return {
            "is_up": is_up,
            "status_code": resp.status_code,
            "response_time_ms": round(elapsed_ms, 2),
            "error_message": None,
        }
    except requests.exceptions.Timeout:
        return {
            "is_up": False,
            "status_code": None,
            "response_time_ms": None,
            "error_message": "Connection timed out",
        }
    except requests.exceptions.ConnectionError:
        return {
            "is_up": False,
            "status_code": None,
            "response_time_ms": None,
            "error_message": "Connection error",
        }
    except requests.exceptions.RequestException:
        return {
            "is_up": False,
            "status_code": None,
            "response_time_ms": None,
            "error_message": "Request failed",
        }


def _save_check(site_id: int, result: dict):
    """Persist a check result to the database."""
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO checks
                (site_id, is_up, status_code, response_time_ms, error_message)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                site_id,
                1 if result["is_up"] else 0,
                result["status_code"],
                result["response_time_ms"],
                result["error_message"],
            ),
        )


MAX_CONCURRENT_CHECKS = 20  # cap to avoid spawning too many threads at once


def run_checks_for_sites(site_ids: list[int] | None = None):
    """
    Check enabled sites concurrently via a ThreadPoolExecutor.

    Args:
        site_ids: When ``None`` (default) every enabled site is checked.
                  When a non-empty list of integers is supplied only those
                  site IDs are queried (still filtered to enabled sites only).
                  An empty list is treated the same as ``None``.

    The number of worker threads is capped at ``MAX_CONCURRENT_CHECKS`` to
    prevent resource exhaustion when a large number of sites is configured.
    """
    with get_db() as conn:
        if site_ids:
            placeholders = ",".join("?" * len(site_ids))
            rows = conn.execute(
                f"SELECT id, url FROM sites WHERE enabled=1 AND id IN ({placeholders})",
                site_ids,
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, url FROM sites WHERE enabled=1"
            ).fetchall()

    if not rows:
        return

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(len(rows), MAX_CONCURRENT_CHECKS)
    ) as executor:
        future_to_site = {
            executor.submit(check_site, row["url"]): row["id"] for row in rows
        }
        for future in concurrent.futures.as_completed(future_to_site):
            site_id = future_to_site[future]
            try:
                result = future.result()
            except (RuntimeError, OSError, ValueError) as exc:
                result = {
                    "is_up": False,
                    "status_code": None,
                    "response_time_ms": None,
                    "error_message": "Unexpected check error",
                }
            _save_check(site_id, result)


# ---------------------------------------------------------------------------
# Scheduler helpers
# ---------------------------------------------------------------------------


def _job_id(site_id: int) -> str:
    return f"site_{site_id}"


def _schedule_site(site_id: int, interval_seconds: int):
    """Add or replace the APScheduler interval job for a site."""
    job_id = _job_id(site_id)
    with _scheduler_lock:
        existing = _scheduler.get_job(job_id)
        if existing:
            existing.remove()
        _scheduler.add_job(
            run_checks_for_sites,
            "interval",
            seconds=interval_seconds,
            id=job_id,
            args=[[site_id]],
            replace_existing=True,
        )


def _unschedule_site(site_id: int):
    """Remove the APScheduler job for a site (if it exists)."""
    job_id = _job_id(site_id)
    with _scheduler_lock:
        job = _scheduler.get_job(job_id)
        if job:
            job.remove()


def reload_all_schedules():
    """Read all enabled sites from the DB and (re)schedule them."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, check_interval FROM sites WHERE enabled=1"
        ).fetchall()
    for row in rows:
        _schedule_site(row["id"], row["check_interval"])


# ---------------------------------------------------------------------------
# Routes – pages
# ---------------------------------------------------------------------------


@app.route("/")
def index():
    with get_db() as conn:
        sites = conn.execute("SELECT * FROM sites ORDER BY name").fetchall()
        site_stats = []
        for site in sites:
            last_check = conn.execute(
                """
                SELECT is_up, status_code, response_time_ms, checked_at
                FROM checks
                WHERE site_id = ?
                ORDER BY checked_at DESC
                LIMIT 1
                """,
                (site["id"],),
            ).fetchone()
            # 24-hour uptime %
            total = conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM checks
                WHERE site_id = ? AND checked_at >= datetime('now','-1 day')
                """,
                (site["id"],),
            ).fetchone()["cnt"]
            up_count = conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM checks
                WHERE site_id = ? AND is_up=1
                      AND checked_at >= datetime('now','-1 day')
                """,
                (site["id"],),
            ).fetchone()["cnt"]
            uptime_24h = (up_count / total * 100) if total else None
            site_stats.append(
                {
                    "site": dict(site),
                    "last_check": dict(last_check) if last_check else None,
                    "uptime_24h": round(uptime_24h, 1) if uptime_24h is not None else None,
                }
            )
    return render_template("index.html", site_stats=site_stats)


@app.route("/site/<int:site_id>")
def site_detail(site_id):
    with get_db() as conn:
        site = conn.execute(
            "SELECT * FROM sites WHERE id=?", (site_id,)
        ).fetchone()
        if not site:
            return "Site not found", 404
        recent_checks = conn.execute(
            """
            SELECT * FROM checks
            WHERE site_id=?
            ORDER BY checked_at DESC
            LIMIT 50
            """,
            (site_id,),
        ).fetchall()
    return render_template(
        "site_detail.html",
        site=dict(site),
        recent_checks=[dict(c) for c in recent_checks],
    )


# ---------------------------------------------------------------------------
# Routes – API
# ---------------------------------------------------------------------------


@app.route("/api/sites", methods=["GET"])
def api_list_sites():
    with get_db() as conn:
        sites = conn.execute("SELECT * FROM sites ORDER BY name").fetchall()
    return jsonify([dict(s) for s in sites])


@app.route("/api/sites", methods=["POST"])
def api_add_site():
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    url = (data.get("url") or "").strip()
    interval = int(data.get("check_interval", 300))
    enabled = int(bool(data.get("enabled", True)))

    if not name or not url:
        return jsonify({"error": "name and url are required"}), 400
    if not url.startswith(("http://", "https://")):
        return jsonify({"error": "url must start with http:// or https://"}), 400
    if interval < 60:
        return jsonify({"error": "check_interval must be at least 60 seconds"}), 400

    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO sites (name, url, check_interval, enabled) VALUES (?,?,?,?)",
            (name, url, interval, enabled),
        )
        site_id = cur.lastrowid
        site = conn.execute("SELECT * FROM sites WHERE id=?", (site_id,)).fetchone()

    if enabled:
        _schedule_site(site_id, interval)

    return jsonify(dict(site)), 201


@app.route("/api/sites/<int:site_id>", methods=["PUT"])
def api_update_site(site_id):
    with get_db() as conn:
        existing = conn.execute(
            "SELECT * FROM sites WHERE id=?", (site_id,)
        ).fetchone()
        if not existing:
            return jsonify({"error": "Site not found"}), 404

    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or existing["name"]).strip()
    url = (data.get("url") or existing["url"]).strip()
    interval = int(data.get("check_interval", existing["check_interval"]))
    enabled = int(bool(data.get("enabled", existing["enabled"])))

    if not url.startswith(("http://", "https://")):
        return jsonify({"error": "url must start with http:// or https://"}), 400
    if interval < 60:
        return jsonify({"error": "check_interval must be at least 60 seconds"}), 400

    with get_db() as conn:
        conn.execute(
            """
            UPDATE sites
            SET name=?, url=?, check_interval=?, enabled=?
            WHERE id=?
            """,
            (name, url, interval, enabled, site_id),
        )
        site = conn.execute("SELECT * FROM sites WHERE id=?", (site_id,)).fetchone()

    if enabled:
        _schedule_site(site_id, interval)
    else:
        _unschedule_site(site_id)

    return jsonify(dict(site))


@app.route("/api/sites/<int:site_id>", methods=["DELETE"])
def api_delete_site(site_id):
    _unschedule_site(site_id)
    with get_db() as conn:
        conn.execute("DELETE FROM sites WHERE id=?", (site_id,))
    return "", 204


@app.route("/api/sites/<int:site_id>/check", methods=["POST"])
def api_check_now(site_id):
    """Trigger an immediate check for a single site."""
    with get_db() as conn:
        site = conn.execute(
            "SELECT * FROM sites WHERE id=?", (site_id,)
        ).fetchone()
        if not site:
            return jsonify({"error": "Site not found"}), 404

    result = check_site(site["url"])
    _save_check(site_id, result)
    return jsonify(result), 200


@app.route("/api/sites/<int:site_id>/history")
def api_site_history(site_id):
    """
    Return daily uptime percentages for the last N days.
    Query param: days=30 (default), 60, or 90.
    """
    days = min(int(request.args.get("days", 30)), 90)
    with get_db() as conn:
        site = conn.execute(
            "SELECT id FROM sites WHERE id=?", (site_id,)
        ).fetchone()
        if not site:
            return jsonify({"error": "Site not found"}), 404

        rows = conn.execute(
            """
            SELECT
                date(checked_at) AS day,
                COUNT(*)         AS total,
                SUM(is_up)       AS up_count
            FROM checks
            WHERE site_id = ?
              AND checked_at >= datetime('now', ? || ' days')
            GROUP BY day
            ORDER BY day
            """,
            (site_id, f"-{days}"),
        ).fetchall()

    history = [
        {
            "day": r["day"],
            "total": r["total"],
            "up_count": r["up_count"],
            "uptime_pct": round(r["up_count"] / r["total"] * 100, 2)
            if r["total"]
            else None,
        }
        for r in rows
    ]
    return jsonify({"days": days, "history": history})


# ---------------------------------------------------------------------------
# Form-based helpers (HTML form submissions from the dashboard)
# ---------------------------------------------------------------------------


@app.route("/sites/add", methods=["POST"])
def form_add_site():
    name = request.form.get("name", "").strip()
    url = request.form.get("url", "").strip()
    interval = int(request.form.get("check_interval", 300))
    enabled = 1 if request.form.get("enabled") else 0

    errors = []
    if not name:
        errors.append("Name is required.")
    if not url or not url.startswith(("http://", "https://")):
        errors.append("A valid URL starting with http:// or https:// is required.")
    if interval < 60:
        errors.append("Check interval must be at least 60 seconds.")

    if errors:
        # Re-render dashboard with errors
        with get_db() as conn:
            sites = conn.execute("SELECT * FROM sites ORDER BY name").fetchall()
        return render_template(
            "index.html",
            site_stats=[{"site": dict(s), "last_check": None, "uptime_24h": None} for s in sites],
            errors=errors,
            form_data={"name": name, "url": url, "check_interval": interval},
        ), 400

    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO sites (name, url, check_interval, enabled) VALUES (?,?,?,?)",
            (name, url, interval, enabled),
        )
        site_id = cur.lastrowid

    if enabled:
        _schedule_site(site_id, interval)

    return redirect(url_for("index"))


@app.route("/sites/<int:site_id>/delete", methods=["POST"])
def form_delete_site(site_id):
    _unschedule_site(site_id)
    with get_db() as conn:
        conn.execute("DELETE FROM sites WHERE id=?", (site_id,))
    return redirect(url_for("index"))


@app.route("/sites/<int:site_id>/toggle", methods=["POST"])
def form_toggle_site(site_id):
    with get_db() as conn:
        site = conn.execute(
            "SELECT * FROM sites WHERE id=?", (site_id,)
        ).fetchone()
        if not site:
            return "Site not found", 404
        new_enabled = 0 if site["enabled"] else 1
        conn.execute(
            "UPDATE sites SET enabled=? WHERE id=?", (new_enabled, site_id)
        )

    if new_enabled:
        _schedule_site(site_id, site["check_interval"])
    else:
        _unschedule_site(site_id)

    return redirect(url_for("index"))


@app.route("/sites/<int:site_id>/check", methods=["POST"])
def form_check_now(site_id):
    with get_db() as conn:
        site = conn.execute(
            "SELECT * FROM sites WHERE id=?", (site_id,)
        ).fetchone()
        if not site:
            return "Site not found", 404
    result = check_site(site["url"])
    _save_check(site_id, result)
    return redirect(url_for("site_detail", site_id=site_id))


# ---------------------------------------------------------------------------
# Application entry point
# ---------------------------------------------------------------------------


def create_app(database: str | None = None) -> Flask:
    """Factory used by tests and direct runs."""
    if database:
        app.config["DATABASE"] = database
    init_db()
    if not _scheduler.running:
        _scheduler.start()
    reload_all_schedules()
    return app


if __name__ == "__main__":
    create_app()
    app.run(debug=False, host="0.0.0.0", port=5000)
