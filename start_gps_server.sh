#!/bin/bash

# GPS NTP Server Startup Script
# This script handles starting the GPS NTP server with the web interface

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "================================"
echo "GPS NTP Server Startup"
echo "================================"

# Check if virtual environment exists
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
else
    echo "Warning: No virtual environment found"
    echo "Checking if dependencies are installed system-wide..."

    # Check for required Python packages
    if ! python3 -c "import flask" 2>/dev/null; then
        echo "Error: Flask is not installed"
        echo "Please run: pip3 install -r requirements.txt"
        echo "Or create a virtual environment with: python3 -m venv venv"
        exit 1
    fi
fi

# Default arguments if none provided
if [ $# -eq 0 ]; then
    echo "Starting with default configuration..."
    echo "  Serial port: /dev/ttyUSB0"
    echo "  Baud rate: 9600"
    echo "  NTP port: 123 (requires sudo)"
    echo "  Web port: 5000"
    echo ""
    echo "To customize, use:"
    echo "  $0 --serial /dev/ttyUSB0 --baudrate 9600 --ntp-port 123 --web-port 5000"
    echo ""
fi

# Check if running as root for port 123
if [ "$EUID" -ne 0 ] && [[ "$*" != *"--ntp-port"* ]]; then
    echo "Warning: Not running as root. NTP port 123 requires sudo."
    echo "Consider running: sudo $0"
    echo "Or use a higher port: $0 --ntp-port 8123 --web-port 8080"
    echo ""
fi

echo "Starting GPS NTP Server..."
echo ""

# Start the server
exec python3 gps_ntp_server.py "$@"
