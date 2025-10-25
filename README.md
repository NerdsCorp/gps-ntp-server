# GPS NTP Server with Web Dashboard

A comprehensive GPS time server solution for the **Adafruit Ultimate GPS GNSS with USB** (99 channel w/10 Hz updates). This application provides:

- 🛰️ Real-time GPS data monitoring via web dashboard
- ⏰ NTP time server functionality using GPS time (Stratum 1)
- 📍 Live position tracking with map visualization
- 📊 Detailed satellite and signal statistics
- 📈 NTP statistics monitoring with nanosecond precision
- ➕ Dynamic server management (add/remove NTP servers to monitor)
- 🔧 Auto-detection of GPS devices
- 🌐 RESTful API for integration
- ⚙️ GPS configuration tools included

## Features

### GPS Monitoring
- Real-time GPS status and fix quality
- Position data (latitude, longitude, altitude)
- Speed and course tracking
- Satellite constellation view with SNR values
- HDOP/VDOP/PDOP dilution values
- Automatic GPS device detection

### NTP Server
- Stratum 1 time server using GPS time
- Serves accurate time to network clients
- Client connection statistics
- Compatible with standard NTP clients
- Configurable port (default 123, requires sudo)

### NTP Statistics Monitor
- Real-time monitoring of multiple NTP servers
- Nanosecond precision time measurements (µs/ns display)
- Add/remove servers dynamically via web interface
- Quality scoring and availability tracking
- RTT (Round-Trip Time) and offset monitoring
- Live charts and historical data
- Server comparison and ranking
- CSV export of statistics

### Web Dashboard
- Beautiful, responsive web interface
- Live map showing current position (OpenStreetMap)
- Real-time data updates
- Satellite signal strength visualization
- NTP statistics dashboard at /stats/
- NTP client configuration instructions
- Mobile-friendly design

## Requirements

- Python 3.7 or higher
- Adafruit Ultimate GPS connected via USB
- Linux/Unix system (tested on Ubuntu/Debian/Raspberry Pi)
- Root/sudo access for NTP server on port 123

## Installation

### One-Line Install (Quick & Easy)

Install directly with a single command:
```bash
curl -fsSL https://raw.githubusercontent.com/NerdsCorp/gps-ntp-server/main/install.sh | sudo bash
```

Or for a specific branch:
```bash
curl -fsSL https://raw.githubusercontent.com/NerdsCorp/gps-ntp-server/claude/fix-install-script-011CUUQSLmp7GptvAymLjJYM/install.sh | sudo bash
```

This will:
- Clone the repository to `/opt/gps-ntp-server`
- Install all dependencies in a virtual environment
- Create and enable a systemd service
- Configure GPS serial port permissions

### Manual Install (Recommended for Development)

1. **Clone the repository:**
```bash
git clone https://github.com/NerdsCorp/gps-ntp-server.git
cd gps-ntp-server
```

2. **Run the installation script:**
```bash
sudo ./install.sh
```

3. **Connect your GPS device:**
- Plug in the Adafruit Ultimate GPS via USB
- The software will auto-detect it at `/dev/ttyUSB0` or `/dev/ttyACM0`

### Update Existing Installation

```bash
curl -fsSL https://raw.githubusercontent.com/NerdsCorp/gps-ntp-server/main/update.sh | sudo bash
```

Or if installed manually:
```bash
cd gps-ntp-server
git pull
sudo ./update.sh
```

### Uninstall

```bash
curl -fsSL https://raw.githubusercontent.com/NerdsCorp/gps-ntp-server/main/uninstall.sh | sudo bash
```

Or if installed manually:
```bash
cd gps-ntp-server
sudo ./uninstall.sh
```

### Manual Installation

If you prefer to install manually without the script:

1. **Clone the repository:**
```bash
git clone https://github.com/NerdsCorp/gps-ntp-server.git
cd gps-ntp-server
```

2. **Install system dependencies:**
```bash
sudo apt-get update
sudo apt-get install python3 python3-pip python3-venv git
```

3. **Create virtual environment:**
```bash
python3 -m venv venv
source venv/bin/activate
```

4. **Install Python packages:**
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

5. **Add your user to the dialout group (for serial port access):**
```bash
sudo usermod -a -G dialout $USER
```
Then logout and login again for the group change to take effect.

6. **Run the server:**
```bash
# For NTP on port 123 (requires root)
sudo ./venv/bin/python3 gps_ntp_server.py

# Or for testing on higher ports (no root needed)
./venv/bin/python3 gps_ntp_server.py --ntp-port 8123 --web-port 8080
```

## Usage

### Basic Usage

Run with default settings (auto-detect GPS, web on port 5000, NTP on port 123):
```bash
sudo python3 gps_ntp_server.py
```

### Command Line Options

```bash
python3 gps_ntp_server.py [OPTIONS]

Options:
  --serial PORT       GPS serial port (default: /dev/ttyUSB0)
  --baudrate RATE     GPS baud rate (default: 9600 for Adafruit)
  --web-port PORT     Web server port (default: 5000)
  --ntp-port PORT     NTP server port (default: 123, requires sudo)
  --help, -h          Show help message and exit
```

**Note:** Port 123 is the standard NTP port and requires root/sudo access. For testing without sudo, use a higher port like 8123.

### Examples

1. **Run with default settings (recommended):**
```bash
sudo python3 gps_ntp_server.py
```

2. **Specify GPS port explicitly:**
```bash
sudo python3 gps_ntp_server.py --serial /dev/ttyUSB0
```

3. **Use higher baud rate (if configured on GPS):**
```bash
sudo python3 gps_ntp_server.py --baudrate 115200
```

4. **Run NTP on non-privileged port (no sudo needed):**
```bash
python3 gps_ntp_server.py --ntp-port 8123 --web-port 8080
```

5. **Custom configuration:**
```bash
sudo python3 gps_ntp_server.py --serial /dev/ttyACM0 --baudrate 9600 --web-port 5000 --ntp-port 123
```

## Accessing the Dashboard

Once running, open your browser and navigate to:

**Main Dashboard (GPS Status):**
```
http://localhost:5000
```

**NTP Statistics Dashboard:**
```
http://localhost:5000/stats/
```

Or from another computer on the same network:
```
http://[SERVER-IP]:5000
http://[SERVER-IP]:5000/stats/
```

### NTP Statistics Features
The statistics dashboard allows you to:
- Monitor your GPS NTP server and other NTP servers
- Add new NTP servers to monitor (time.google.com, pool.ntp.org, etc.)
- Remove servers from monitoring
- View nanosecond precision measurements (µs/ns)
- Compare server performance and quality
- Export statistics to CSV

## Configuring NTP Clients

### Linux (chrony)
Edit `/etc/chrony/chrony.conf`:
```
server [YOUR-SERVER-IP] iburst prefer
```

### Linux (ntpd)
Edit `/etc/ntp.conf`:
```
server [YOUR-SERVER-IP] iburst prefer
```

### Windows
Open Command Prompt as Administrator:
```cmd
w32tm /config /manualpeerlist:"[YOUR-SERVER-IP]" /syncfromflags:manual
w32tm /resync
```

### macOS
```bash
sudo sntp -sS [YOUR-SERVER-IP]
```

### Testing NTP
```bash
ntpdate -q [YOUR-SERVER-IP]
# or
chronyc sources -v
```

## Running as a System Service

1. **Copy service file:**
```bash
sudo cp gps-ntp-server.service /etc/systemd/system/
```

2. **Modify paths in service file if needed:**
```bash
sudo nano /etc/systemd/system/gps-ntp-server.service
```

3. **Enable and start service:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable gps-ntp-server
sudo systemctl start gps-ntp-server
```

4. **Check status:**
```bash
sudo systemctl status gps-ntp-server
sudo journalctl -u gps-ntp-server -f
```

## API Endpoints

The server provides a RESTful API for integration:

### Main API
- `GET /` - Main web dashboard (GPS status)
- `GET /api/gps` - Current GPS data (JSON)
- `GET /api/ntp` - NTP server statistics (JSON)
- `GET /api/server-info` - Server configuration (JSON)

### NTP Statistics API
- `GET /stats/` - NTP statistics dashboard (HTML)
- `GET /stats/api/ntp/stats` - Current NTP statistics for all monitored servers (JSON)
- `POST /stats/api/ntp/add-server` - Add a new NTP server to monitor (JSON)
- `POST /stats/api/ntp/remove-server` - Remove an NTP server from monitoring (JSON)
- `GET /stats/api/ntp/export` - Export statistics as CSV

### Example API Response

```json
{
  "status": "ACTIVE",
  "latitude": 37.7749,
  "longitude": -122.4194,
  "altitude": 52.3,
  "satellites": 9,
  "fix_quality": "GPS fix",
  "timestamp": "14:23:45",
  "hdop": 0.9
}
```

## Troubleshooting

### GPS Not Detected

1. **Check USB connection:**
```bash
ls -la /dev/ttyUSB*
lsusb
dmesg | grep -i usb
```

2. **Check permissions:**
```bash
sudo usermod -a -G dialout $USER
# Logout and login again
```

3. **Try different ports:**
```bash
# Common GPS ports
/dev/ttyUSB0
/dev/ttyACM0
/dev/serial0
/dev/ttyAMA0  # Raspberry Pi
```

### No GPS Fix

1. **Ensure clear sky view** - GPS needs line of sight to satellites
2. **Wait for cold start** - First fix can take 30 seconds to 2 minutes
3. **Check antenna** - Ensure antenna is connected (if external)
4. **Move outdoors** - GPS doesn't work well indoors

### NTP Server Issues

1. **Permission denied on port 123:**
```bash
# Run with sudo
sudo python3 gps_ntp_server.py

# Or use higher port
python3 gps_ntp_server.py --ntp-port 8123
```

2. **Port already in use:**
```bash
# Check what's using the port
sudo lsof -i :123
sudo systemctl stop ntp  # Stop system NTP if running
```

### Web Interface Not Loading

1. **Check firewall:**
```bash
sudo ufw allow 5000/tcp  # Allow web port
sudo ufw allow 123/udp   # Allow NTP port
```

2. **Check if service is running:**
```bash
curl http://localhost:5000/api/gps
```

## GPS Module Configuration

The Adafruit Ultimate GPS uses the MTK3339 chipset. The server automatically configures it for optimal NTP performance:

- **Update rate:** 1Hz (1000ms) - optimal for NTP time synchronization
- **NMEA sentences:** RMC and GGA only (minimal overhead)
- **Baud rate:** Default 9600 (can be changed)
- **SBAS:** Enabled for better accuracy

### Configuration Tool

The package includes `adafruit_gps_config.py` for advanced GPS configuration:

```bash
# Interactive configuration menu
python3 adafruit_gps_config.py

# Quick NTP configuration
python3 adafruit_gps_config.py --configure-ntp

# Monitor GPS output
python3 adafruit_gps_config.py --monitor 30

# Factory reset
python3 adafruit_gps_config.py --reset
```

### NTP Testing Tool

The package includes `ntp_test_tool.py` for testing and comparing NTP servers:

```bash
# Test a single server
python3 ntp_test_tool.py --server time.google.com

# Compare multiple servers
python3 ntp_test_tool.py --compare --server time.google.com time.cloudflare.com pool.ntp.org

# Test custom port
python3 ntp_test_tool.py --server localhost:8123

# Monitor servers over time
python3 ntp_test_tool.py --monitor --duration 300 --server time.google.com time.nist.gov

# Export results to JSON
python3 ntp_test_tool.py --server time.google.com --export results.json
```

### Manual GPS Configuration (Optional)

Connect to GPS directly:
```bash
screen /dev/ttyUSB0 9600
```

Send PMTK commands:
```
$PMTK220,1000*1F   # 1Hz update rate (recommended for NTP)
$PMTK220,100*2F    # 10Hz update rate (high precision)
$PMTK251,115200*1F # Change baud to 115200
```

## Performance Considerations

- **Raspberry Pi:** Works excellently, recommended platform
- **CPU Usage:** Minimal (<5% on Pi 3B+)
- **Memory:** ~50MB RAM
- **Network:** Minimal bandwidth required
- **Storage:** Logs can be rotated to prevent filling disk

## Security Notes

1. **NTP Amplification:** Consider rate limiting if exposed to internet
2. **Web Interface:** Add authentication if exposed publicly
3. **GPS Spoofing:** Use in trusted environment
4. **Firewall:** Restrict access to trusted networks

## Advanced Features

### High Precision Mode

For maximum time accuracy:
```bash
sudo python3 gps_ntp_server.py --gps-baud 115200
```

### Multi-GPS Support

Modify code to read from multiple GPS devices for redundancy.

### Database Logging

Add SQLite/PostgreSQL logging for long-term position/time tracking.

## License

MIT License - Feel free to use and modify!

## Support

- Adafruit GPS Guide: https://learn.adafruit.com/adafruit-ultimate-gps
- NMEA Protocol: https://www.nmea.org/
- NTP Protocol: https://www.ntp.org/

## Changelog

### Version 2.0.0 (Latest)
- **NTP Statistics Monitor**: Real-time monitoring of multiple NTP servers
- **Nanosecond Precision**: Display time measurements in µs and ns
- **Dynamic Server Management**: Add/remove NTP servers via web UI
- **Quality Scoring**: Automated quality assessment for monitored servers
- **Live Charts**: Historical RTT visualization
- **CSV Export**: Export statistics for analysis
- **API Enhancements**: New endpoints for server management
- **Graceful Shutdown**: Proper signal handling for SIGTERM/SIGINT
- **Bug Fixes**:
  - Fixed NTP port default mismatch
  - Fixed quality score calculation
  - Improved error handling and resource cleanup
  - Fixed serial port cleanup on errors
  - Added device existence validation
- **Configuration Tools**: Added GPS configuration and NTP testing utilities
- **Improved Documentation**: Updated README with all new features

### Version 1.0.0
- Initial release
- Full GPS monitoring
- NTP server implementation
- Web dashboard with live map
- Auto-detection of GPS devices
- RESTful API
- Systemd service support

## Contributing

Contributions welcome! Future enhancement ideas:
- ✅ ~~NTP statistics monitoring~~ (Implemented in v2.0)
- ✅ ~~Server management UI~~ (Implemented in v2.0)
- Authentication for web interface
- RINEX data export for scientific analysis
- RTK/DGPS support for centimeter-level accuracy
- WebSocket for real-time updates
- Docker containerization
- Prometheus metrics export
- Email/SMS alerts for GPS/NTP failures
- Multi-GPS redundancy support
