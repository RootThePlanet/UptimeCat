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

These steps set up UptimeCat as a persistent background service using
**systemd** and **Gunicorn** so it survives reboots and restarts automatically
on failure.

**Requirements:** Python 3.10 or newer, `python3-venv`, `git`.

### 1. Create a dedicated user and install directory

```bash
sudo useradd --system --shell /usr/sbin/nologin --home /opt/uptimecat uptimecat
sudo mkdir -p /opt/uptimecat
sudo chown uptimecat:uptimecat /opt/uptimecat
```

### 2. Copy the application files

```bash
# From your local machine (or clone directly on the server)
sudo cp -r . /opt/uptimecat/
sudo chown -R uptimecat:uptimecat /opt/uptimecat
```

Or clone directly on the server:

```bash
sudo -u uptimecat git clone https://github.com/RootThePlanet/UptimeCat /opt/uptimecat
```

### 3. Create a Python virtual environment and install dependencies

```bash
sudo -u uptimecat python3 -m venv /opt/uptimecat/venv
sudo -u uptimecat /opt/uptimecat/venv/bin/pip install -r /opt/uptimecat/requirements.txt
```

### 4. Install the systemd service

```bash
sudo cp /opt/uptimecat/uptimecat.service /etc/systemd/system/uptimecat.service
sudo systemctl daemon-reload
sudo systemctl enable uptimecat   # start automatically at boot
sudo systemctl start uptimecat
```

### 5. Check that it's running

```bash
sudo systemctl status uptimecat
```

The dashboard is now available at `http://<your-server-ip>:5000`.

### Viewing logs

All output is captured by systemd's journal:

```bash
# Live log stream
sudo journalctl -u uptimecat -f

# Last 100 lines
sudo journalctl -u uptimecat -n 100
```

### Common management commands

```bash
sudo systemctl stop uptimecat      # stop the service
sudo systemctl restart uptimecat   # restart after a config change
sudo systemctl disable uptimecat   # don't start at boot
```

### (Optional) Reverse proxy with nginx

If you want to serve UptimeCat on port 80/443 or behind a domain name, change
the `--bind` address in `uptimecat.service` to `127.0.0.1:5000` (so it is not
directly reachable from the network) and then place this snippet inside your
nginx `server {}` block:

```nginx
location / {
    proxy_pass         http://127.0.0.1:5000;
    proxy_set_header   Host              $host;
    proxy_set_header   X-Real-IP         $remote_addr;
    proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto $scheme;
}
```

Then reload nginx:

```bash
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
uptimecat.service      # systemd unit file for Linux server deployment
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

