"""
Tests for UptimeCat.

Run with:  pytest tests/
"""

import json
import os
import sqlite3
import tempfile
from unittest.mock import MagicMock, patch

import pytest

# Import the Flask app factory and the check_site function.
import app as uptimecat
from app import check_site, create_app, get_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db(tmp_path):
    """Return a path to a fresh temporary SQLite database."""
    return str(tmp_path / "test.db")


@pytest.fixture()
def flask_app(tmp_db):
    """Create a Flask test app with an isolated database."""
    # Patch scheduler so it does not spawn real background threads during tests.
    with patch.object(uptimecat._scheduler, "start"), \
         patch.object(uptimecat._scheduler, "add_job"), \
         patch.object(uptimecat._scheduler, "get_job", return_value=None):
        test_app = create_app(database=tmp_db)
        test_app.config["TESTING"] = True
        yield test_app


@pytest.fixture()
def client(flask_app):
    return flask_app.test_client()


# ---------------------------------------------------------------------------
# Unit tests – check_site
# ---------------------------------------------------------------------------


class TestGetDb:
    """Verify that get_db() returns a correctly configured connection."""

    def test_row_factory(self, flask_app):
        with flask_app.app_context() if False else open(os.devnull):
            pass
        conn = get_db()
        assert conn.row_factory is sqlite3.Row

    def test_foreign_keys_enabled(self, flask_app):
        conn = get_db()
        result = conn.execute("PRAGMA foreign_keys").fetchone()
        assert result[0] == 1

    def test_wal_mode(self, flask_app):
        conn = get_db()
        result = conn.execute("PRAGMA journal_mode").fetchone()
        assert result[0] == "wal"


# ---------------------------------------------------------------------------
# Unit tests – check_site
# ---------------------------------------------------------------------------


class TestCheckSite:
    def _mock_response(self, status_code):
        mock = MagicMock()
        mock.status_code = status_code
        return mock

    def test_up_on_200(self):
        with patch("app.requests.get", return_value=self._mock_response(200)):
            result = check_site("https://example.com")
        assert result["is_up"] is True
        assert result["status_code"] == 200
        assert result["error_message"] is None
        assert result["response_time_ms"] is not None

    def test_up_on_301_redirect(self):
        with patch("app.requests.get", return_value=self._mock_response(301)):
            result = check_site("http://example.com")
        assert result["is_up"] is True
        assert result["status_code"] == 301

    def test_down_on_404(self):
        with patch("app.requests.get", return_value=self._mock_response(404)):
            result = check_site("https://example.com/missing")
        assert result["is_up"] is False
        assert result["status_code"] == 404

    def test_down_on_500(self):
        with patch("app.requests.get", return_value=self._mock_response(500)):
            result = check_site("https://example.com")
        assert result["is_up"] is False

    def test_down_on_timeout(self):
        import requests as req_lib
        with patch("app.requests.get", side_effect=req_lib.exceptions.Timeout):
            result = check_site("https://example.com")
        assert result["is_up"] is False
        assert "timed out" in result["error_message"].lower()
        assert result["status_code"] is None

    def test_down_on_connection_error(self):
        import requests as req_lib
        with patch("app.requests.get", side_effect=req_lib.exceptions.ConnectionError("refused")):
            result = check_site("https://nonexistent.invalid")
        assert result["is_up"] is False
        assert result["error_message"] == "Connection error"


# ---------------------------------------------------------------------------
# API tests – /api/sites
# ---------------------------------------------------------------------------


class TestApiSites:
    def test_list_empty(self, client):
        resp = client.get("/api/sites")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_add_site(self, client):
        resp = client.post(
            "/api/sites",
            data=json.dumps(
                {"name": "Example", "url": "https://example.com", "check_interval": 300}
            ),
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["name"] == "Example"
        assert data["url"] == "https://example.com"
        assert data["check_interval"] == 300
        assert data["enabled"] == 1
        assert "id" in data

    def test_add_site_missing_fields(self, client):
        resp = client.post(
            "/api/sites",
            data=json.dumps({"name": "NoURL"}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_add_site_bad_url(self, client):
        resp = client.post(
            "/api/sites",
            data=json.dumps({"name": "X", "url": "ftp://bad", "check_interval": 300}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_add_site_interval_too_short(self, client):
        resp = client.post(
            "/api/sites",
            data=json.dumps(
                {"name": "X", "url": "https://x.com", "check_interval": 30}
            ),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_list_after_add(self, client):
        client.post(
            "/api/sites",
            data=json.dumps({"name": "A", "url": "https://a.com", "check_interval": 60}),
            content_type="application/json",
        )
        resp = client.get("/api/sites")
        sites = resp.get_json()
        assert len(sites) == 1
        assert sites[0]["name"] == "A"

    def test_update_site(self, client):
        add = client.post(
            "/api/sites",
            data=json.dumps({"name": "A", "url": "https://a.com", "check_interval": 60}),
            content_type="application/json",
        )
        site_id = add.get_json()["id"]
        resp = client.put(
            f"/api/sites/{site_id}",
            data=json.dumps({"name": "B", "check_interval": 120}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        updated = resp.get_json()
        assert updated["name"] == "B"
        assert updated["check_interval"] == 120

    def test_update_nonexistent(self, client):
        resp = client.put(
            "/api/sites/9999",
            data=json.dumps({"name": "X"}),
            content_type="application/json",
        )
        assert resp.status_code == 404

    def test_delete_site(self, client):
        add = client.post(
            "/api/sites",
            data=json.dumps({"name": "D", "url": "https://d.com", "check_interval": 60}),
            content_type="application/json",
        )
        site_id = add.get_json()["id"]
        resp = client.delete(f"/api/sites/{site_id}")
        assert resp.status_code == 204
        assert client.get("/api/sites").get_json() == []

    def test_check_now(self, client):
        add = client.post(
            "/api/sites",
            data=json.dumps(
                {"name": "C", "url": "https://c.com", "check_interval": 60}
            ),
            content_type="application/json",
        )
        site_id = add.get_json()["id"]

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("app.requests.get", return_value=mock_resp):
            resp = client.post(f"/api/sites/{site_id}/check")
        assert resp.status_code == 200
        result = resp.get_json()
        assert result["is_up"] is True

    def test_check_now_nonexistent(self, client):
        resp = client.post("/api/sites/9999/check")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# API tests – /api/sites/<id>/history
# ---------------------------------------------------------------------------


class TestApiHistory:
    def _add_site(self, client):
        resp = client.post(
            "/api/sites",
            data=json.dumps(
                {"name": "H", "url": "https://h.com", "check_interval": 60}
            ),
            content_type="application/json",
        )
        return resp.get_json()["id"]

    def test_history_empty(self, client):
        site_id = self._add_site(client)
        resp = client.get(f"/api/sites/{site_id}/history")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["days"] == 30
        assert data["history"] == []

    def test_history_after_checks(self, client):
        site_id = self._add_site(client)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("app.requests.get", return_value=mock_resp):
            client.post(f"/api/sites/{site_id}/check")
            client.post(f"/api/sites/{site_id}/check")

        resp = client.get(f"/api/sites/{site_id}/history?days=30")
        data = resp.get_json()
        assert len(data["history"]) == 1
        assert data["history"][0]["total"] == 2
        assert data["history"][0]["up_count"] == 2
        assert data["history"][0]["uptime_pct"] == 100.0

    def test_history_days_param(self, client):
        site_id = self._add_site(client)
        resp = client.get(f"/api/sites/{site_id}/history?days=90")
        assert resp.get_json()["days"] == 90

    def test_history_nonexistent_site(self, client):
        resp = client.get("/api/sites/9999/history")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Page rendering tests
# ---------------------------------------------------------------------------


class TestPages:
    def test_index_page(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"UptimeCat" in resp.data

    def test_site_detail_page(self, client):
        add = client.post(
            "/api/sites",
            data=json.dumps(
                {"name": "P", "url": "https://p.com", "check_interval": 60}
            ),
            content_type="application/json",
        )
        site_id = add.get_json()["id"]
        resp = client.get(f"/site/{site_id}")
        assert resp.status_code == 200
        assert b"Recent Checks" in resp.data

    def test_site_detail_not_found(self, client):
        resp = client.get("/site/9999")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Concurrent checks
# ---------------------------------------------------------------------------


class TestConcurrentChecks:
    def test_multiple_sites_checked(self, client):
        """run_checks_for_sites should check all enabled sites concurrently."""
        for i in range(3):
            client.post(
                "/api/sites",
                data=json.dumps(
                    {
                        "name": f"Site{i}",
                        "url": f"https://site{i}.com",
                        "check_interval": 60,
                    }
                ),
                content_type="application/json",
            )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("app.requests.get", return_value=mock_resp) as mock_get:
            uptimecat.run_checks_for_sites()
        assert mock_get.call_count == 3
