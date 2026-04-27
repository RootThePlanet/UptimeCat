# UptimeCat 🐱

**The cat never sleeps.** Track the uptime of your websites.

UptimeCat is a Flask web application that monitors remote websites on a
configurable schedule, checks multiple sites concurrently, and charts
uptime history over the last 30, 60, or 90 days.

---

## Features

- **Add / remove sites** to monitor via an in-browser dashboard.
- **Flexible schedule** — set any interval in seconds (e.g. 60 s · 300 s = 5 min · 3 600 s = 1 hr · 86 400 s = 1 day).
- **Concurrent checks** — all enabled sites are fetched in parallel using `ThreadPoolExecutor`.
- **HTTP compliance** — follows 301/302 redirects automatically; considers any `< 400` status code as "up".
- **Uptime history charts** — interactive bar chart (Chart.js) showing daily uptime % for the last 30, 60, or 90 days.
- **Recent-checks table** — timestamps, HTTP status codes, response times, and error messages.
- **Pause / resume** — disable monitoring for a site without deleting it.
- **REST JSON API** — all CRUD operations and history are also available as JSON endpoints.
- **SQLite storage** — zero-config, file-based persistence (`uptimecat.db`).

---

## Quick start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Start the server (creates uptimecat.db automatically)
python app.py
```

Open <http://localhost:5000> in your browser.

---

## Running tests

```bash
pytest tests/ -v
```

---

## Project layout

```
app.py                 # Flask application, checker, scheduler, routes
requirements.txt       # Python dependencies
static/
  css/style.css        # Stylesheet
  js/app.js            # Auto-refresh helper
  js/chart.umd.js      # Bundled Chart.js (no CDN required)
templates/
  base.html            # Shared layout
  index.html           # Dashboard
  site_detail.html     # Per-site history + chart
tests/
  test_app.py          # pytest test suite (25 tests)
```

---

## REST API

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/api/sites` | List all sites |
| `POST` | `/api/sites` | Add a site (`name`, `url`, `check_interval`, `enabled`) |
| `PUT`  | `/api/sites/<id>` | Update a site |
| `DELETE` | `/api/sites/<id>` | Delete a site |
| `POST` | `/api/sites/<id>/check` | Trigger an immediate check |
| `GET`  | `/api/sites/<id>/history?days=30` | Daily uptime history (30/60/90 days) |

