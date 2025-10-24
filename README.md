# GPS NTP Server with Web Dashboard

A comprehensive GPS time server solution for the **Adafruit Ultimate GPS GNSS with USB** (99 channel w/10 Hz updates). This application provides:

- 🛰️ Real-time GPS data monitoring via web dashboard
- ⏰ NTP time server functionality using GPS time
- 📍 Live position tracking with map visualization
- 📊 Detailed satellite and signal statistics
- 🔧 Auto-detection of GPS devices
- 🌐 RESTful API for integration

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

### Web Dashboard
- Beautiful, responsive web interface
- Live map showing current position (OpenStreetMap)
- Real-time data updates every second
- Satellite signal strength visualization
- NTP client configuration instructions
- Mobile-friendly design

## Requirements

- Python 3.7 or higher
- Adafruit Ultimate GPS connected via USB
- Linux/Unix system (tested on Ubuntu/Debian/Raspberry Pi)
- Root/sudo access for NTP server on port 123

## Installation

### Quick Install

1. **Clone or download the files:**
```bash
mkdir /opt/gps-ntp-server
cd /opt/gps-ntp-server
# Copy the files here
```

2. **Install Python dependencies:**
```bash
pip3 install -r requirements.txt
```

3. **Connect your GPS device:**
- Plug in the Adafruit Ultimate GPS via USB
- The software will auto-detect it, or you can specify the port

### Manual Installation

1. **Install system dependencies:**
```bash
sudo apt-get update
sudo apt-get install python3 python3-pip python3-venv
```

2. **Create virtual environment (optional but recommended):**
```bash
python3 -m venv venv
source venv/bin/activate
```

3. **Install Python packages:**
```bash
pip install flask flask-cors pyserial pynmea2 python-dateutil
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
  --gps-port PORT     GPS serial port (default: /dev/ttyUSB0, auto-detect if not found)
  --gps-baud RATE     GPS baud rate (default: 9600)
  --web-port PORT     Web server port (default: 5000)
  --ntp-port PORT     NTP server port (default: 123, requires sudo for <1024)
  --no-ntp           Disable NTP server
  --debug            Enable debug logging
```

### Examples

1. **Run with auto-detection (recommended):**
```bash
sudo python3 gps_ntp_server.py
```

2. **Specify GPS port explicitly:**
```bash
sudo python3 gps_ntp_server.py --gps-port /dev/ttyUSB0
```

3. **Use higher baud rate (if configured on GPS):**
```bash
sudo python3 gps_ntp_server.py --gps-baud 115200
```

4. **Run NTP on non-privileged port (no sudo needed):**
```bash
python3 gps_ntp_server.py --ntp-port 8123 --web-port 8080
```

5. **Web interface only (no NTP server):**
```bash
python3 gps_ntp_server.py --no-ntp
```

## Accessing the Dashboard

Once running, open your browser and navigate to:
```
http://localhost:5000
```

Or from another computer on the same network:
```
http://[SERVER-IP]:5000
```

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

- `GET /` - Web dashboard
- `GET /api/gps` - Current GPS data (JSON)
- `GET /api/ntp` - NTP server statistics (JSON)
- `GET /api/server-info` - Server configuration (JSON)
- `GET /api/config` - Get configuration
- `POST /api/config` - Update configuration (TODO)

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

The Adafruit Ultimate GPS uses the MTK3339 chipset. The server automatically configures it for optimal performance:

- **Update rate:** 10Hz (100ms)
- **NMEA sentences:** RMC, GGA, GSA, GSV, VTG
- **Baud rate:** Default 9600 (can be changed)

### Manual GPS Configuration (Optional)

Connect to GPS directly:
```bash
screen /dev/ttyUSB0 9600
```

Send PMTK commands:
```
$PMTK220,100*2F    # 10Hz update rate
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

### Version 1.0.0
- Initial release
- Full GPS monitoring
- NTP server implementation  
- Web dashboard with live map
- Auto-detection of GPS devices
- RESTful API
- Systemd service support

## Contributing

Contributions welcome! Areas for improvement:
- Authentication for web interface
- Historical data graphing
- RINEX data export
- RTK/DGPS support
- WebSocket for real-time updates
- Docker containerization
