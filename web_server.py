#!/usr/bin/env python3
"""
GPS NTP Web Server
Separate web interface service for GPS NTP Server
"""

import json
import logging
import signal
import sys
import os
import time
from datetime import datetime, timezone
from flask import Flask, Response
from flask_cors import CORS

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Try to import ntp_statistics
try:
    from ntp_statistics import ntp_stats_bp, init_ntp_monitor
except ImportError as e:
    logger.warning(f"NTP statistics module not available: {e}")
    ntp_stats_bp = None
    init_ntp_monitor = None

app = Flask(__name__)
CORS(app)

# Register stats blueprint if available
if ntp_stats_bp:
    app.register_blueprint(ntp_stats_bp, url_prefix='/stats')
    logger.info("Registered NTP statistics blueprint")

# Status file path (shared with GPS/NTP server)
STATUS_FILE = '/var/run/gps-ntp-server/status.json'

class WebServer:
    """Web server for GPS NTP status and statistics"""

    def __init__(self, status_file=STATUS_FILE, ntp_server='localhost', ntp_port=123):
        self.status_file = status_file
        self.ntp_server = ntp_server
        self.ntp_port = ntp_port

    def get_status(self):
        """Read status from shared file"""
        try:
            if not os.path.exists(self.status_file):
                logger.debug(f"Status file not found: {self.status_file}")
                return None

            with open(self.status_file, 'r') as f:
                status = json.load(f)
                return status
        except Exception as e:
            logger.error(f"Error reading status file: {e}")
            return None

# Global web server instance
web_server = None

@app.route('/')
def index():
    """Serve HTML status page"""
    if web_server:
        status = web_server.get_status()

        if status:
            # Determine GPS status color
            if status['gps_time'] and status['gps_fix_quality'] > 0:
                gps_status_color = '#28a745'  # green
                gps_status_text = 'GPS LOCKED'
            elif status['gps_time']:
                gps_status_color = '#ffc107'  # yellow
                gps_status_text = 'GPS ACTIVE'
            else:
                gps_status_color = '#dc3545'  # red
                gps_status_text = 'NO GPS SIGNAL'

            # Calculate time since update display
            time_since_update = status['time_since_update'] if status['time_since_update'] else 0

            html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="refresh" content="5">
    <title>GPS NTP Server</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            margin: 0;
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            color: white;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        .header {{
            text-align: center;
            margin-bottom: 30px;
        }}
        .header h1 {{
            font-size: 3em;
            margin: 0;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }}
        .status-badge {{
            display: inline-block;
            padding: 10px 30px;
            background: {gps_status_color};
            border-radius: 25px;
            font-weight: bold;
            font-size: 1.2em;
            margin-top: 20px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.2);
        }}
        .cards {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}
        .card {{
            background: white;
            color: #333;
            padding: 25px;
            border-radius: 15px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
        }}
        .card h2 {{
            margin: 0 0 15px 0;
            font-size: 1.2em;
            color: #667eea;
            border-bottom: 2px solid #667eea;
            padding-bottom: 10px;
        }}
        .metric {{
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid #eee;
        }}
        .metric:last-child {{
            border-bottom: none;
        }}
        .metric-label {{
            color: #666;
            font-weight: 500;
        }}
        .metric-value {{
            font-weight: bold;
            color: #333;
        }}
        .big-number {{
            font-size: 3em;
            font-weight: bold;
            color: #667eea;
            text-align: center;
            margin: 20px 0;
        }}
        .link-card {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            text-align: center;
            padding: 30px;
            border-radius: 15px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            cursor: pointer;
            transition: transform 0.3s, box-shadow 0.3s;
            text-decoration: none;
            display: block;
        }}
        .link-card:hover {{
            transform: translateY(-5px);
            box-shadow: 0 15px 40px rgba(0,0,0,0.3);
        }}
        .link-card h2 {{
            margin: 0;
            color: white;
            border: none;
        }}
        .link-card p {{
            margin: 10px 0 0 0;
            opacity: 0.9;
        }}
        .footer {{
            text-align: center;
            margin-top: 30px;
            opacity: 0.8;
            font-size: 0.9em;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>GPS NTP Server</h1>
            <div class="status-badge">{gps_status_text}</div>
        </div>

        <div class="cards">
            <div class="card">
                <h2>GPS Status</h2>
                <div class="metric">
                    <span class="metric-label">GPS Time:</span>
                    <span class="metric-value">{status['gps_time'] or 'Waiting...'}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Fix Quality:</span>
                    <span class="metric-value">{['No fix', 'GPS', 'DGPS', 'PPS', 'RTK', 'RTK float'][status['gps_fix_quality']] if status['gps_fix_quality'] < 6 else 'Unknown'}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Satellites:</span>
                    <span class="metric-value">{status['satellites']}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Firmware:</span>
                    <span class="metric-value">{status['firmware']}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Last Update:</span>
                    <span class="metric-value">{time_since_update:.1f}s ago</span>
                </div>
            </div>

            <div class="card">
                <h2>NTP Server</h2>
                <div class="big-number">{status['stats']['ntp_responses']}</div>
                <div style="text-align: center; color: #666; margin-bottom: 20px;">NTP Responses Sent</div>
                <div class="metric">
                    <span class="metric-label">Requests Received:</span>
                    <span class="metric-value">{status['stats']['ntp_requests']}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Success Rate:</span>
                    <span class="metric-value">{(status['stats']['ntp_responses'] / status['stats']['ntp_requests'] * 100) if status['stats']['ntp_requests'] > 0 else 0:.1f}%</span>
                </div>
            </div>

            <div class="card">
                <h2>GPS Messages</h2>
                <div class="metric">
                    <span class="metric-label">Total Messages:</span>
                    <span class="metric-value">{status['stats']['nmea_total']}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">RMC (Time):</span>
                    <span class="metric-value">{status['stats']['rmc_count']} ({status['stats']['rmc_valid']} valid)</span>
                </div>
                <div class="metric">
                    <span class="metric-label">GGA (Position):</span>
                    <span class="metric-value">{status['stats']['gga_count']} ({status['stats']['gga_valid']} valid)</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Valid Data Rate:</span>
                    <span class="metric-value">{(status['stats']['rmc_valid'] / status['stats']['rmc_count'] * 100) if status['stats']['rmc_count'] > 0 else 0:.1f}%</span>
                </div>
            </div>
        </div>

        <a href="/stats/" class="link-card">
            <h2>View Detailed Statistics Dashboard</h2>
            <p>Real-time monitoring, charts, and NTP server comparison</p>
        </a>

        <div class="footer">
            <p>Page auto-refreshes every 5 seconds</p>
            <p>Adafruit Ultimate GPS NTP Server | Stratum 1 GPS Time Source</p>
        </div>
    </div>
</body>
</html>'''
            return html

    return '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="refresh" content="5">
    <title>GPS NTP Server</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            margin: 0;
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            color: white;
            display: flex;
            align-items: center;
            justify-content: center;
            text-align: center;
        }}
        h1 {{ font-size: 3em; margin: 0; }}
        p {{ font-size: 1.2em; opacity: 0.9; }}
    </style>
</head>
<body>
    <div>
        <h1>GPS NTP Web Interface</h1>
        <p>Waiting for GPS/NTP server connection...</p>
        <p><a href="/stats/" style="color: white;">View Statistics</a></p>
    </div>
</body>
</html>'''

@app.route('/api/gps')
def api_gps():
    """Get GPS data as JSON"""
    if web_server:
        status = web_server.get_status()
        if status:
            return {
                'gps_time': status['gps_time'],
                'gps_fix_quality': status['gps_fix_quality'],
                'satellites': status['satellites'],
                'firmware': status['firmware'],
                'last_update': status['last_update'],
                'time_since_update': status['time_since_update']
            }
    return {'error': 'GPS server not available'}, 503

@app.route('/api/ntp')
def api_ntp():
    """Get NTP statistics as JSON"""
    if web_server:
        status = web_server.get_status()
        if status:
            return status['stats']
    return {'error': 'NTP server not available'}, 503

@app.route('/api/server-info')
def api_server_info():
    """Get server configuration info"""
    if web_server:
        status = web_server.get_status()
        if status:
            return {
                'ntp_server': web_server.ntp_server,
                'ntp_port': web_server.ntp_port,
                'status_file': web_server.status_file,
                'running': status['running']
            }
    return {'error': 'Server not available'}, 503

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='GPS NTP Web Server')
    parser.add_argument('--web-port', type=int, default=5000,
                       help='Web interface port (default: 5000)')
    parser.add_argument('--status-file', default=STATUS_FILE,
                       help=f'Status file path (default: {STATUS_FILE})')
    parser.add_argument('--ntp-server', default='localhost',
                       help='NTP server address for monitoring (default: localhost)')
    parser.add_argument('--ntp-port', type=int, default=123,
                       help='NTP server port (default: 123)')

    args = parser.parse_args()

    # Create web server instance
    web_server = WebServer(
        status_file=args.status_file,
        ntp_server=args.ntp_server,
        ntp_port=args.ntp_port
    )

    # Try to initialize NTP monitor with GPS server if available
    # The NTP monitor will be lazily initialized on first API call if this fails
    if init_ntp_monitor:
        try:
            init_ntp_monitor([
                {'address': args.ntp_server, 'port': args.ntp_port, 'name': 'GPS NTP Server'}
            ])
            logger.info("NTP monitor initialized with GPS server")
        except Exception as e:
            logger.warning(f"Could not initialize NTP monitor with GPS server (will initialize on first use): {e}")

    # Set up signal handlers for graceful shutdown
    def signal_handler(signum, frame):
        """Handle shutdown signals gracefully"""
        signal_name = 'SIGTERM' if signum == signal.SIGTERM else 'SIGINT'
        logger.info(f"\nReceived {signal_name}, shutting down gracefully...")
        sys.exit(0)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        logger.info("=" * 60)
        logger.info("Starting GPS NTP Web Server...")
        logger.info("=" * 60)
        logger.info(f"  Web Port: {args.web_port}")
        logger.info(f"  Status File: {args.status_file}")
        logger.info(f"  Monitoring NTP: {args.ntp_server}:{args.ntp_port}")
        logger.info("-" * 60)

        # Check if port is available
        import socket as sock_test
        test_sock = sock_test.socket(sock_test.AF_INET, sock_test.SOCK_STREAM)
        try:
            test_sock.bind(('0.0.0.0', args.web_port))
            test_sock.close()
            logger.info(f"✅ Port {args.web_port} is available")
        except OSError as e:
            logger.error(f"❌ Port {args.web_port} is already in use or unavailable: {e}")
            raise

        logger.info(f"🌐 Starting web interface on port {args.web_port}...")
        logger.info(f"   View status at: http://localhost:{args.web_port}/")
        logger.info(f"   Statistics at: http://localhost:{args.web_port}/stats/")
        logger.info("-" * 60)

        # Start Flask web server (blocking call)
        app.run(host='0.0.0.0', port=args.web_port, debug=False, use_reloader=False)

    except KeyboardInterrupt:
        logger.info("\n🛑 Received KeyboardInterrupt, shutting down...")
    except Exception as e:
        logger.error(f"❌ Web server error: {e}")
        logger.error(f"   Exception type: {type(e).__name__}")
        import traceback
        logger.error(f"   Traceback:\n{traceback.format_exc()}")
    finally:
        logger.info("Shutdown complete")
        sys.exit(0)
