#!/bin/bash

# GPS NTP Server Uninstall Script
# Removes all files, virtualenv, and systemd service if installed

set -e

SERVICE_NAME="gps-ntp-server"
INSTALL_DIR="/opt/gps-ntp-server"
USER_INSTALL_DIR="$HOME/gps-ntp-server"

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

# Stop and disable systemd service if root
if [ "$SYSTEM_MODE" = true ]; then
    if systemctl list-units --full -all | grep -q "$SERVICE_NAME.service"; then
        echo ""
        echo "Stopping and disabling systemd service..."
        systemctl stop $SERVICE_NAME 2>/dev/null || true
        systemctl disable $SERVICE_NAME 2>/dev/null || true
        systemctl daemon-reload
        rm -f /etc/systemd/system/$SERVICE_NAME.service
    else
        echo "Service not found — skipping systemd cleanup."
    fi
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
if pgrep -f "gps_ntp_server.py" > /dev/null; then
    echo "⚠️  Some gps_ntp_server.py processes are still running. Killing them..."
    pkill -f "gps_ntp_server.py" || true
else
    echo "No running processes found."
fi

echo ""
echo "================================"
echo "Uninstall Complete!"
echo "================================"
