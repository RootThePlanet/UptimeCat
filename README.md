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

## Deploy on a Linux server

UptimeCat ships with an automated installer that handles every step for you.

**Requirements:** Python 3.10+, `git`, a systemd-based Linux distribution
(Debian, Ubuntu, RHEL, Fedora, etc.).

### One-line install

```bash
curl -fsSL https://raw.githubusercontent.com/RootThePlanet/UptimeCat/main/install.sh | sudo bash
```

That single command will:
1. Verify prerequisites (Python, git, systemd)
2. Create a dedicated `uptimecat` system user
3. Clone the repository to `/opt/uptimecat`
4. Create a Python virtual environment and install all dependencies
5. Install and enable the systemd service (starts automatically at boot)
6. Start UptimeCat and print the dashboard URL

The installer is **idempotent** — run it again at any time to update to the
latest version.

### After installing

```bash
# Check the service is running
sudo systemctl status uptimecat

# Live log stream
sudo journalctl -u uptimecat -f

# Update to the latest version
sudo bash /opt/uptimecat/install.sh
```

### Common management commands

```bash
sudo systemctl stop uptimecat      # stop the service
sudo systemctl restart uptimecat   # restart after a config change
sudo systemctl disable uptimecat   # don't start at boot
```

### (Optional) Reverse proxy with nginx

To serve UptimeCat on port 80/443 or behind a domain name, edit
`/etc/systemd/system/uptimecat.service` and change `--bind 0.0.0.0:5000` to
`--bind 127.0.0.1:5000`, then add this to your nginx `server {}` block:

```nginx
location / {
    proxy_pass         http://127.0.0.1:5000;
    proxy_set_header   Host              $host;
    proxy_set_header   X-Real-IP         $remote_addr;
    proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto $scheme;
}
```

```bash
sudo systemctl daemon-reload && sudo systemctl restart uptimecat
sudo systemctl reload nginx
```

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
install.sh             # One-command Linux server installer
uptimecat.service      # systemd unit file (also written by install.sh)
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

