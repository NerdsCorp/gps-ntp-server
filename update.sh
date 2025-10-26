#!/bin/bash

# GPS NTP Server Update Script
# Updates source code, dependencies, and restarts services if installed

set -e

GPS_SERVICE="gps-ntp-server"
WEB_SERVICE="gps-ntp-webserver"
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

# Stop running services if system installation
if [ "$SYSTEM_MODE" = true ]; then
    echo ""
    echo "🛑 Stopping running services..."

    if systemctl is-active --quiet "$WEB_SERVICE"; then
        echo "  Stopping $WEB_SERVICE..."
        systemctl stop "$WEB_SERVICE"
    fi

    if systemctl is-active --quiet "$GPS_SERVICE"; then
        echo "  Stopping $GPS_SERVICE..."
        systemctl stop "$GPS_SERVICE"
    fi
fi

# Update repository
if [ -d .git ]; then
    echo ""
    echo "📡 Pulling latest version from GitHub..."

    # Detect the default/main branch
    DEFAULT_BRANCH=$(git remote show origin | grep 'HEAD branch' | cut -d' ' -f5)
    if [ -z "$DEFAULT_BRANCH" ]; then
        # Fallback: try main, then master
        if git ls-remote --heads origin main | grep -q main; then
            DEFAULT_BRANCH="main"
        elif git ls-remote --heads origin master | grep -q master; then
            DEFAULT_BRANCH="master"
        else
            echo "⚠️  Cannot detect default branch. Using current branch."
            DEFAULT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
        fi
    fi

    echo "Using branch: $DEFAULT_BRANCH"

    # Check for uncommitted changes
    if ! git diff-index --quiet HEAD --; then
        echo "⚠️  WARNING: You have uncommitted local changes!"
        echo "These will be lost if you continue. Press Ctrl+C to cancel."
        read -p "Press Enter to continue and discard local changes..."
    fi

    git fetch origin "$DEFAULT_BRANCH"
    git reset --hard "origin/$DEFAULT_BRANCH"
else
    echo "❌ Not a git repository."
    echo "Please clone from GitHub:"
    echo "  git clone https://github.com/NerdsCorp/gps-ntp-server.git"
    exit 1
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

# Update systemd service files if applicable
if [ "$SYSTEM_MODE" = true ]; then
    echo ""
    echo "🔧 Checking systemd service files..."

    # Update GPS/NTP server service
    if [ -f "gps-ntp-server.service" ]; then
        INSTALLED_GPS_SERVICE="/etc/systemd/system/$GPS_SERVICE.service"

        if [ -f "$INSTALLED_GPS_SERVICE" ]; then
            if ! diff -q "gps-ntp-server.service" "$INSTALLED_GPS_SERVICE" > /dev/null 2>&1; then
                echo "📝 GPS server service file has changed, updating..."
                sed "s|WorkingDirectory=.*|WorkingDirectory=$INSTALL_DIR|g; s|ExecStart=.*|ExecStart=$INSTALL_DIR/venv/bin/python3 $INSTALL_DIR/gps_ntp_server.py --serial /dev/ttyUSB0 --baudrate 9600 --ntp-port 123|g" \
                    gps-ntp-server.service > "$INSTALLED_GPS_SERVICE"
                echo "✅ GPS server service file updated"
            else
                echo "✅ GPS server service file is up to date"
            fi
        else
            echo "⚠️  GPS server service file not found, installing..."
            sed "s|WorkingDirectory=.*|WorkingDirectory=$INSTALL_DIR|g; s|ExecStart=.*|ExecStart=$INSTALL_DIR/venv/bin/python3 $INSTALL_DIR/gps_ntp_server.py --serial /dev/ttyUSB0 --baudrate 9600 --ntp-port 123|g" \
                gps-ntp-server.service > "$INSTALLED_GPS_SERVICE"
            systemctl enable "$GPS_SERVICE"
            echo "✅ GPS server service file installed"
        fi
    fi

    # Update web server service
    if [ -f "gps-ntp-webserver.service" ]; then
        INSTALLED_WEB_SERVICE="/etc/systemd/system/$WEB_SERVICE.service"

        if [ -f "$INSTALLED_WEB_SERVICE" ]; then
            if ! diff -q "gps-ntp-webserver.service" "$INSTALLED_WEB_SERVICE" > /dev/null 2>&1; then
                echo "📝 Web server service file has changed, updating..."
                sed "s|WorkingDirectory=.*|WorkingDirectory=$INSTALL_DIR|g; s|ExecStart=.*|ExecStart=$INSTALL_DIR/venv/bin/python3 $INSTALL_DIR/web_server.py --web-port 5000 --ntp-server localhost --ntp-port 123|g" \
                    gps-ntp-webserver.service > "$INSTALLED_WEB_SERVICE"
                echo "✅ Web server service file updated"
            else
                echo "✅ Web server service file is up to date"
            fi
        else
            echo "⚠️  Web server service file not found, installing..."
            sed "s|WorkingDirectory=.*|WorkingDirectory=$INSTALL_DIR|g; s|ExecStart=.*|ExecStart=$INSTALL_DIR/venv/bin/python3 $INSTALL_DIR/web_server.py --web-port 5000 --ntp-server localhost --ntp-port 123|g" \
                gps-ntp-webserver.service > "$INSTALLED_WEB_SERVICE"
            systemctl enable "$WEB_SERVICE"
            echo "✅ Web server service file installed"
        fi
    fi

    echo ""
    echo "🚀 Restarting systemd services..."
    systemctl daemon-reload
    systemctl restart "$GPS_SERVICE"
    systemctl restart "$WEB_SERVICE"

    # Wait a moment for services to start
    sleep 2

    echo ""
    echo "Service Status:"
    systemctl status "$GPS_SERVICE" --no-pager --lines=5
    echo ""
    systemctl status "$WEB_SERVICE" --no-pager --lines=5
else
    echo ""
    echo "✅ Update complete!"
    echo "To restart manually, run:"
    echo "  GPS/NTP Server: cd $INSTALL_DIR && sudo python3 gps_ntp_server.py"
    echo "  Web Interface:  cd $INSTALL_DIR && python3 web_server.py"
fi

echo ""
echo "================================"
echo "Update Complete!"
echo "================================"
