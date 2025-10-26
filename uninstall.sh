#!/bin/bash

# GPS NTP Server Uninstall Script
# Removes all files, virtualenv, and systemd services if installed

set -e

GPS_SERVICE="gps-ntp-server"
WEB_SERVICE="gps-ntp-webserver"
INSTALL_DIR="/opt/gps-ntp-server"
USER_INSTALL_DIR="$HOME/gps-ntp-server"
RUNTIME_DIR="/var/run/gps-ntp-server"

echo "================================"
echo "GPS NTP Server Uninstall Script"
echo "================================"
echo ""

# Check if running as root for system uninstall
if [ "$EUID" -eq 0 ]; then
    echo "🧹 Running as root - removing system installation..."
    SYSTEM_MODE=true
else
    echo "👤 Running as user - removing local installation..."
    SYSTEM_MODE=false
fi

# Stop and disable systemd services if root
if [ "$SYSTEM_MODE" = true ]; then
    echo ""
    echo "Stopping and disabling systemd services..."

    # Stop and disable web server service
    if systemctl list-units --full -all | grep -q "$WEB_SERVICE.service"; then
        echo "  Stopping $WEB_SERVICE..."
        systemctl stop $WEB_SERVICE 2>/dev/null || true
        systemctl disable $WEB_SERVICE 2>/dev/null || true
        rm -f /etc/systemd/system/$WEB_SERVICE.service
    fi

    # Stop and disable GPS/NTP server service
    if systemctl list-units --full -all | grep -q "$GPS_SERVICE.service"; then
        echo "  Stopping $GPS_SERVICE..."
        systemctl stop $GPS_SERVICE 2>/dev/null || true
        systemctl disable $GPS_SERVICE 2>/dev/null || true
        rm -f /etc/systemd/system/$GPS_SERVICE.service
    fi

    # Reload systemd
    systemctl daemon-reload
fi

# Remove installation directories
echo ""
if [ "$SYSTEM_MODE" = true ]; then
    if [ -d "$INSTALL_DIR" ]; then
        echo "Removing installation directory: $INSTALL_DIR"
        rm -rf "$INSTALL_DIR"
    else
        echo "No system installation found in $INSTALL_DIR"
    fi

    # Remove runtime directory
    if [ -d "$RUNTIME_DIR" ]; then
        echo "Removing runtime directory: $RUNTIME_DIR"
        rm -rf "$RUNTIME_DIR"
    fi
else
    if [ -d "$USER_INSTALL_DIR" ]; then
        echo "Removing local directory: $USER_INSTALL_DIR"
        rm -rf "$USER_INSTALL_DIR"
    else
        echo "No user installation found in $USER_INSTALL_DIR"
    fi
fi

# Optional: remove dialout group modification message
if [ "$SYSTEM_MODE" = true ]; then
    echo ""
    echo "Note: If you added your user to the 'dialout' group, that change is persistent."
    echo "You can remove it manually (optional):"
    echo "  sudo gpasswd -d $SUDO_USER dialout"
fi

echo ""
echo "✅ GPS NTP Server has been fully uninstalled."
echo ""

# Check for leftover processes
echo "Checking for leftover Python processes..."
FOUND_PROCESSES=false

if pgrep -f "gps_ntp_server.py" > /dev/null; then
    echo "⚠️  Some gps_ntp_server.py processes are still running. Killing them..."
    pkill -f "gps_ntp_server.py" || true
    FOUND_PROCESSES=true
fi

if pgrep -f "web_server.py" > /dev/null; then
    echo "⚠️  Some web_server.py processes are still running. Killing them..."
    pkill -f "web_server.py" || true
    FOUND_PROCESSES=true
fi

if [ "$FOUND_PROCESSES" = false ]; then
    echo "No running processes found."
fi

echo ""
echo "================================"
echo "Uninstall Complete!"
echo "================================"
