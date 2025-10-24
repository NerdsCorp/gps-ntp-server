#!/bin/bash

# GPS NTP Server Update Script
# Updates source code, dependencies, and restarts service if installed

set -e

SERVICE_NAME="gps-ntp-server"
SYSTEM_DIR="/opt/gps-ntp-server"
USER_DIR="$HOME/gps-ntp-server"

echo "================================"
echo "GPS NTP Server Update Script"
echo "================================"
echo ""

# Detect install type
if [ "$EUID" -eq 0 ] && [ -d "$SYSTEM_DIR" ]; then
    echo "🔧 Detected system installation at $SYSTEM_DIR"
    INSTALL_DIR="$SYSTEM_DIR"
    SYSTEM_MODE=true
elif [ -d "$USER_DIR" ]; then
    echo "👤 Detected user installation at $USER_DIR"
    INSTALL_DIR="$USER_DIR"
    SYSTEM_MODE=false
else
    echo "❌ No installation found."
    echo "Run install.sh first."
    exit 1
fi

cd "$INSTALL_DIR"

# Stop running service if system installation
if [ "$SYSTEM_MODE" = true ]; then
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        echo "🛑 Stopping running service..."
        systemctl stop "$SERVICE_NAME"
    fi
fi

# Update repository
if [ -d .git ]; then
    echo ""
    echo "📡 Pulling latest version from GitHub..."
    git fetch origin main
    git reset --hard origin/main
else
    echo "Repository not found — re-cloning..."
    cd /tmp
    git clone https://github.com/NerdsCorp/gps-ntp-server.git
    cp -r gps-ntp-server/* "$INSTALL_DIR/"
    rm -rf gps-ntp-server
    cd "$INSTALL_DIR"
fi

# Update Python environment
if [ -d "venv" ]; then
    echo ""
    echo "🐍 Updating Python packages..."
    source venv/bin/activate
    pip install --upgrade pip
    pip install --upgrade -r requirements.txt
else
    echo "⚠️ No virtual environment found — creating new one..."
    python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
fi

# Restart systemd service if applicable
if [ "$SYSTEM_MODE" = true ]; then
    echo ""
    echo "🚀 Restarting systemd service..."
    systemctl daemon-reload
    systemctl start "$SERVICE_NAME"
    systemctl status "$SERVICE_NAME" --no-pager
else
    echo ""
    echo "✅ Update complete!"
    echo "To restart manually, run:"
    echo "  cd $INSTALL_DIR && ./start_gps_server.sh"
fi

echo ""
echo "================================"
echo "Update Complete!"
echo "================================"
