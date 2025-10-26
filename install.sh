#!/bin/bash

# GPS NTP Server Installation Script
# For Adafruit Ultimate GPS GNSS
# Can be run via curl pipe or from within the repository directory

set -e

echo "================================"
echo "GPS NTP Server Installation"
echo "================================"
echo ""

# Detect if we're running via curl pipe or from repo
IN_REPO=false
if [ -f "gps_ntp_server.py" ] && [ -f "requirements.txt" ]; then
    IN_REPO=true
fi

# Check for required commands
echo "Checking prerequisites..."
for cmd in git python3; do
    if ! command -v $cmd &> /dev/null; then
        echo "❌ Error: $cmd is not installed. Please install it first."
        exit 1
    fi
done
echo "✓ Prerequisites met"
echo ""

# If not in repo, clone it
if [ "$IN_REPO" = false ]; then
    echo "Not running from repository - will clone to /opt/gps-ntp-server"

    # Check if destination already exists
    if [ -d "/opt/gps-ntp-server" ]; then
        echo "⚠️  /opt/gps-ntp-server already exists"
        read -p "Remove and reinstall? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Installation cancelled"
            exit 1
        fi
        rm -rf /opt/gps-ntp-server
    fi

    # Clone the repository
    echo "Cloning repository..."
    git clone https://github.com/NerdsCorp/gps-ntp-server.git /opt/gps-ntp-server
    cd /opt/gps-ntp-server
    echo "✓ Repository cloned"
    echo ""

    # Force system installation mode
    FORCE_SYSTEM_INSTALL=true
else
    echo "Running from repository directory"
    FORCE_SYSTEM_INSTALL=false
fi

# Check if running as root for systemd service
if [ "$EUID" -eq 0 ]; then
   echo "Running as root - will install as system service"
   INSTALL_SERVICE=true
elif [ "$FORCE_SYSTEM_INSTALL" = true ]; then
   echo "❌ Error: Curl pipe installation requires root privileges"
   echo "Please run: curl -fsSL https://raw.githubusercontent.com/NerdsCorp/gps-ntp-server/main/install.sh | sudo bash"
   exit 1
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
        echo "Updating package lists..."
        apt-get update -qq
        echo "Installing Python packages (python3-pip, python3-venv)..."
        apt-get install -y python3-pip python3-venv
        echo "✓ System dependencies installed"
    else
        echo "⚠️  Not running as root. Please install dependencies manually:"
        echo "  sudo apt-get update"
        echo "  sudo apt-get install -y python3-pip python3-venv"
        exit 1
    fi
elif command -v yum &> /dev/null; then
    if [ "$EUID" -eq 0 ]; then
        echo "Installing Python packages (python3-pip)..."
        yum install -y python3-pip
        echo "✓ System dependencies installed"
    else
        echo "⚠️  Not running as root. Please install dependencies manually:"
        echo "  sudo yum install -y python3-pip"
        exit 1
    fi
else
    echo "⚠️  Could not detect package manager (apt-get or yum)"
    echo "Please install python3-pip and python3-venv manually"
fi

# Create installation directory
INSTALL_DIR="/opt/gps-ntp-server"
if [ "$INSTALL_SERVICE" = true ]; then
    if [ "$FORCE_SYSTEM_INSTALL" = true ]; then
        # Already cloned and in /opt/gps-ntp-server
        INSTALL_DIR=$(pwd)
        echo ""
        echo "Using installation directory: $INSTALL_DIR"
    else
        # Running locally as root, need to copy to /opt
        echo ""
        echo "Creating installation directory: $INSTALL_DIR"
        mkdir -p $INSTALL_DIR

        # Copy files
        echo "Copying files..."
        cp gps_ntp_server.py $INSTALL_DIR/
        cp web_server.py $INSTALL_DIR/
        cp requirements.txt $INSTALL_DIR/
        cp README.md $INSTALL_DIR/ 2>/dev/null || true
        cp ntp_statistics.py $INSTALL_DIR/ 2>/dev/null || true
        cp adafruit_gps_config.py $INSTALL_DIR/ 2>/dev/null || true
        cp ntp_test_tool.py $INSTALL_DIR/ 2>/dev/null || true

        cd $INSTALL_DIR
    fi
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

# Create start scripts
echo ""
echo "Creating start scripts..."

# GPS/NTP server start script
cat > start_gps_server.sh << 'EOF'
#!/bin/bash
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"
source venv/bin/activate
python3 gps_ntp_server.py "$@"
EOF
chmod +x start_gps_server.sh

# Web server start script
cat > start_web_server.sh << 'EOF'
#!/bin/bash
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"
source venv/bin/activate
python3 web_server.py "$@"
EOF
chmod +x start_web_server.sh

# Install systemd services if running as root
if [ "$INSTALL_SERVICE" = true ]; then
    echo ""
    echo "Installing systemd services..."

    # Create runtime directory for status file
    echo "Creating runtime directory..."
    mkdir -p /var/run/gps-ntp-server
    chmod 755 /var/run/gps-ntp-server

    # Create GPS NTP server service file
    cat > /etc/systemd/system/gps-ntp-server.service << EOF
[Unit]
Description=GPS NTP Time Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python3 $INSTALL_DIR/gps_ntp_server.py --serial /dev/ttyUSB0 --baudrate 9600 --ntp-port 123
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

    # Create web server service file
    cat > /etc/systemd/system/gps-ntp-webserver.service << EOF
[Unit]
Description=GPS NTP Web Interface
After=network.target gps-ntp-server.service
Requires=gps-ntp-server.service

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python3 $INSTALL_DIR/web_server.py --web-port 5000 --ntp-server localhost --ntp-port 123
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

    # Reload systemd and enable services
    systemctl daemon-reload
    systemctl enable gps-ntp-server
    systemctl enable gps-ntp-webserver

    echo ""
    echo "Services installed! Commands:"
    echo "  GPS/NTP Server:"
    echo "    Start:   sudo systemctl start gps-ntp-server"
    echo "    Stop:    sudo systemctl stop gps-ntp-server"
    echo "    Status:  sudo systemctl status gps-ntp-server"
    echo "    Logs:    sudo journalctl -u gps-ntp-server -f"
    echo ""
    echo "  Web Interface:"
    echo "    Start:   sudo systemctl start gps-ntp-webserver"
    echo "    Stop:    sudo systemctl stop gps-ntp-webserver"
    echo "    Status:  sudo systemctl status gps-ntp-webserver"
    echo "    Logs:    sudo journalctl -u gps-ntp-webserver -f"
    echo ""
    echo "  Both services:"
    echo "    Start:   sudo systemctl start gps-ntp-server gps-ntp-webserver"
    echo "    Stop:    sudo systemctl stop gps-ntp-server gps-ntp-webserver"
    echo "    Restart: sudo systemctl restart gps-ntp-server gps-ntp-webserver"
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
echo "To start the servers:"

if [ "$INSTALL_SERVICE" = true ]; then
    echo "  sudo systemctl start gps-ntp-server gps-ntp-webserver"
    echo ""
    echo "To start services individually:"
    echo "  GPS/NTP: sudo systemctl start gps-ntp-server"
    echo "  Web:     sudo systemctl start gps-ntp-webserver"
else
    echo "  GPS/NTP Server:"
    echo "    cd $INSTALL_DIR"
    echo "    sudo python3 gps_ntp_server.py"
    echo ""
    echo "  Web Interface (in another terminal):"
    echo "    cd $INSTALL_DIR"
    echo "    python3 web_server.py"
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
echo "  python3 web_server.py --help"
echo ""
