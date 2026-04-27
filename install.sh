#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# UptimeCat installer
#
# Usage (from the internet, one-liner):
#   curl -fsSL https://raw.githubusercontent.com/RootThePlanet/UptimeCat/main/install.sh | sudo bash
#
# Usage (from a local clone):
#   sudo bash install.sh
#
# What this script does:
#   1. Checks prerequisites (Python 3.10+, git, systemd)
#   2. Creates a dedicated system user 'uptimecat'
#   3. Clones or updates the app to /opt/uptimecat
#   4. Creates a Python virtual environment and installs dependencies
#   5. Installs and enables the systemd service
#   6. Starts the service and prints the access URL
#
# The script is idempotent — safe to run again to update an existing install.
# ---------------------------------------------------------------------------
set -euo pipefail

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
RESET='\033[0m'

info()    { echo -e "${GREEN}[✔]${RESET} $*"; }
step()    { echo -e "\n${BOLD}▶ $*${RESET}"; }
warn()    { echo -e "${YELLOW}[!]${RESET} $*"; }
die()     { echo -e "${RED}[✘] ERROR:${RESET} $*" >&2; exit 1; }

INSTALL_DIR="/opt/uptimecat"
SERVICE_USER="uptimecat"
SERVICE_FILE="/etc/systemd/system/uptimecat.service"
REPO_URL="https://github.com/RootThePlanet/UptimeCat"

# ---------------------------------------------------------------------------
# 0. Must be run as root
# ---------------------------------------------------------------------------
if [[ $EUID -ne 0 ]]; then
    die "Please run this script as root (e.g. sudo bash install.sh)"
fi

echo -e "\n${BOLD}╔══════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║       UptimeCat Installer 🐱         ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════╝${RESET}"

# ---------------------------------------------------------------------------
# 1. Check prerequisites
# ---------------------------------------------------------------------------
step "Checking prerequisites"

# systemd
if ! command -v systemctl &>/dev/null; then
    die "systemd is required but was not found. This installer supports systemd-based Linux distributions."
fi
info "systemd found"

# git
if ! command -v git &>/dev/null; then
    die "git is required but was not found. Install it with: apt install git  OR  dnf install git"
fi
info "git found"

# Python 3.10+
PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" &>/dev/null; then
        ver=$("$candidate" -c 'import sys; print(sys.version_info[:2])')
        if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    die "Python 3.10 or newer is required but was not found.\nInstall it with: apt install python3  OR  dnf install python3"
fi
info "Python found: $PYTHON ($($PYTHON --version))"

# python3-venv / ensurepip
if ! "$PYTHON" -m ensurepip --version &>/dev/null && ! "$PYTHON" -c 'import venv' &>/dev/null; then
    die "Python venv module not found. Install it with: apt install python3-venv"
fi
info "Python venv module available"

# ---------------------------------------------------------------------------
# 2. Create dedicated system user
# ---------------------------------------------------------------------------
step "Setting up system user '$SERVICE_USER'"

if id "$SERVICE_USER" &>/dev/null; then
    info "User '$SERVICE_USER' already exists — skipping creation"
else
    useradd --system --shell /usr/sbin/nologin --home "$INSTALL_DIR" --no-create-home "$SERVICE_USER"
    info "Created system user '$SERVICE_USER'"
fi

# ---------------------------------------------------------------------------
# 3. Clone or update application files
# ---------------------------------------------------------------------------
step "Installing application to $INSTALL_DIR"

mkdir -p "$INSTALL_DIR"

if [[ -d "$INSTALL_DIR/.git" ]]; then
    info "Existing installation found — pulling latest changes"
    sudo -u "$SERVICE_USER" git -C "$INSTALL_DIR" pull --ff-only
elif [[ -f "$(dirname "$0")/app.py" ]]; then
    # Script is being run from inside a local clone — copy files in place
    SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
    info "Local source detected at $SRC_DIR — copying files"
    rsync -a --exclude='.git' --exclude='venv' --exclude='*.db' \
        "$SRC_DIR/" "$INSTALL_DIR/"
else
    info "Cloning repository from $REPO_URL"
    sudo -u "$SERVICE_USER" git clone "$REPO_URL" "$INSTALL_DIR"
fi

chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
info "Files ready at $INSTALL_DIR"

# ---------------------------------------------------------------------------
# 4. Create virtual environment and install Python dependencies
# ---------------------------------------------------------------------------
step "Setting up Python virtual environment"

VENV="$INSTALL_DIR/venv"

if [[ ! -d "$VENV" ]]; then
    sudo -u "$SERVICE_USER" "$PYTHON" -m venv "$VENV"
    info "Virtual environment created"
else
    info "Virtual environment already exists — updating packages"
fi

sudo -u "$SERVICE_USER" "$VENV/bin/pip" install --quiet --upgrade pip
sudo -u "$SERVICE_USER" "$VENV/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"
info "Dependencies installed"

# ---------------------------------------------------------------------------
# 5. Install systemd service
# ---------------------------------------------------------------------------
step "Installing systemd service"

# Write the service file directly so the installer is self-contained and
# always installs the correct version regardless of what's in the repo copy.
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=UptimeCat website uptime monitor
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$VENV/bin/gunicorn \\
    --workers 1 \\
    --bind 0.0.0.0:5000 \\
    "app:create_app()"
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=uptimecat

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable uptimecat
info "Service installed and enabled"

# ---------------------------------------------------------------------------
# 6. Start (or restart) the service
# ---------------------------------------------------------------------------
step "Starting UptimeCat"

if systemctl is-active --quiet uptimecat; then
    systemctl restart uptimecat
    info "Service restarted"
else
    systemctl start uptimecat
    info "Service started"
fi

# ---------------------------------------------------------------------------
# 7. Done
# ---------------------------------------------------------------------------
# Determine a sensible IP to show the user
SERVER_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "<your-server-ip>")

echo -e "\n${BOLD}${GREEN}══════════════════════════════════════${RESET}"
echo -e "${BOLD}${GREEN}  UptimeCat is running! 🐱${RESET}"
echo -e "${BOLD}${GREEN}══════════════════════════════════════${RESET}"
echo -e "  Dashboard : ${BOLD}http://${SERVER_IP}:5000${RESET}"
echo -e ""
echo -e "  Useful commands:"
echo -e "    sudo systemctl status uptimecat     # check status"
echo -e "    sudo journalctl -u uptimecat -f     # live logs"
echo -e "    sudo systemctl restart uptimecat    # restart"
echo -e "    sudo bash $INSTALL_DIR/install.sh   # update"
echo -e "${BOLD}${GREEN}══════════════════════════════════════${RESET}\n"
