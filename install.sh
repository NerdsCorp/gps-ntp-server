#!/bin/bash

# GPS NTP Server Installation Script
# For Adafruit Ultimate GPS GNSS

set -e

# --- System update & dependencies ---
echo "📦 Installing system dependencies Please Wait..."

# --- Clone or update repo ---
if [ ! -d "gps-ntp-server" ]; then
  git clone https://github.com/NerdsCorp/gps-ntp-server.git
  cd gps-ntp-server
else
  cd gps-ntp-server
  git pull
fi

echo "================================"
echo "GPS NTP Server Installation"
echo "================================"
echo ""

# Check if running as root for systemd service
if [ "$EUID" -eq 0 ]; then 
   echo "Running as root - will install as system service"
   INSTALL_SERVICE=true
else
   echo "Not running as root - will install for current user only"
   echo "Run with sudo to install as system service"
   INSTALL_SERVICE=false
fi

# Check Python version
echo "Checking Python version..."
if ! command -v python3 &> /dev/null; then
    echo "Python 3 is not installed. Please install Python 3.7 or higher."
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
echo "Python version: $PYTHON_VERSION"

# Install system dependencies
echo ""
echo "Installing system dependencies..."
if command -v apt-get &> /dev/null; then
    if [ "$EUID" -eq 0 ]; then
        apt-get update
        apt-get install -y python3-pip python3-venv
    else
        echo "Please run: sudo apt-get install python3-pip python3-venv"
    fi
elif command -v yum &> /dev/null; then
    if [ "$EUID" -eq 0 ]; then
        yum install -y python3-pip
    else
        echo "Please run: sudo yum install python3-pip"
    fi
fi

# Create installation directory
INSTALL_DIR="/opt/gps-ntp-server"
if [ "$INSTALL_SERVICE" = true ]; then
    echo ""
    echo "Creating installation directory: $INSTALL_DIR"
    mkdir -p $INSTALL_DIR
    
    # Copy files
    echo "Copying files..."
    cp gps_ntp_server.py $INSTALL_DIR/
    cp ntp_statistics.py $INSTALL_DIR/
    cp adafruit_gps_config.py $INSTALL_DIR/ 2>/dev/null || true
    cp ntp_test_tool.py $INSTALL_DIR/ 2>/dev/null || true
    cp requirements.txt $INSTALL_DIR/
    cp README.md $INSTALL_DIR/ 2>/dev/null || true

    cd $INSTALL_DIR
else
    INSTALL_DIR=$(pwd)
    echo "Installing in current directory: $INSTALL_DIR"
fi

# Create virtual environment
echo ""
echo "Creating Python virtual environment..."
python3 -m venv venv

# Activate virtual environment and install packages
echo "Installing Python packages..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Create start script
echo ""
echo "Creating start script..."
cat > start_gps_server.sh << 'EOF'
#!/bin/bash
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"
source venv/bin/activate
python3 gps_ntp_server.py "$@"
EOF
chmod +x start_gps_server.sh

# Install systemd service if running as root
if [ "$INSTALL_SERVICE" = true ]; then
    echo ""
    echo "Installing systemd service..."
    
    # Create service file
    cat > /etc/systemd/system/gps-ntp-server.service << EOF
[Unit]
Description=GPS NTP Time Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python3 $INSTALL_DIR/gps_ntp_server.py --serial /dev/ttyUSB0 --baudrate 9600 --web-port 5000 --ntp-port 123
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
    
    # Reload systemd and enable service
    systemctl daemon-reload
    systemctl enable gps-ntp-server
    
    echo ""
    echo "Service installed! Commands:"
    echo "  Start:   sudo systemctl start gps-ntp-server"
    echo "  Stop:    sudo systemctl stop gps-ntp-server"
    echo "  Status:  sudo systemctl status gps-ntp-server"
    echo "  Logs:    sudo journalctl -u gps-ntp-server -f"
fi

# Add user to dialout group for serial port access
if [ "$INSTALL_SERVICE" = false ]; then
    if groups $USER | grep -q '\bdialout\b'; then
        echo "User already in dialout group"
    else
        echo ""
        echo "Adding user to dialout group for serial port access..."
        if [ "$EUID" -eq 0 ]; then
            usermod -a -G dialout $SUDO_USER
            echo "Please logout and login again for group changes to take effect"
        else
            echo "Please run: sudo usermod -a -G dialout $USER"
            echo "Then logout and login again"
        fi
    fi
fi

# Check for GPS device
echo ""
echo "Checking for GPS devices..."
if ls /dev/ttyUSB* 2>/dev/null || ls /dev/ttyACM* 2>/dev/null; then
    echo "Found potential GPS devices:"
    ls -la /dev/ttyUSB* 2>/dev/null || true
    ls -la /dev/ttyACM* 2>/dev/null || true
else
    echo "No GPS devices detected. Please connect your Adafruit GPS."
fi

echo ""
echo "================================"
echo "Installation Complete!"
echo "================================"
echo ""
echo "To start the server:"

if [ "$INSTALL_SERVICE" = true ]; then
    echo "  sudo systemctl start gps-ntp-server"
    echo ""
    echo "To start manually:"
    echo "  cd $INSTALL_DIR"
    echo "  sudo ./start_gps_server.sh"
else
    echo "  cd $INSTALL_DIR"
    echo "  ./start_gps_server.sh"
    echo ""
    echo "For NTP server on port 123 (requires sudo):"
    echo "  sudo ./start_gps_server.sh"
    echo ""
    echo "For testing (higher ports, no sudo):"
    echo "  ./start_gps_server.sh --ntp-port 8123 --web-port 8080"
fi

echo ""
echo "Access the web interface at:"
echo "  http://localhost:5000"
echo ""
echo "Access the NTP statistics dashboard at:"
echo "  http://localhost:5000/stats/"
echo ""
echo "For help and options:"
echo "  python3 gps_ntp_server.py --help"
echo ""
