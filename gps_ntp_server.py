#!/usr/bin/env python3
"""
GPS Web Server and NTP Time Server
For Adafruit Ultimate GPS GNSS with USB (99 channel w/10 Hz updates)
"""

import serial
import serial.tools.list_ports
import threading
import time
import socket
import struct
import json
import logging
from datetime import datetime, timezone
from flask import Flask, render_template_string, jsonify, request
from flask_cors import CORS
import pynmea2
import sys
import os
import argparse

# Import NTP statistics module if available
try:
    from ntp_statistics import ntp_stats_bp, init_ntp_monitor
    NTP_STATS_AVAILABLE = True
except ImportError:
    NTP_STATS_AVAILABLE = False
    logger.warning("NTP statistics module not available")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Flask app
app = Flask(__name__)
CORS(app)

# Register NTP statistics blueprint if available
if NTP_STATS_AVAILABLE:
    app.register_blueprint(ntp_stats_bp)
    logger.info("NTP statistics module registered")

# Global GPS data storage with thread lock
gps_data_lock = threading.Lock()
gps_data = {
    'status': 'NO_FIX',
    'latitude': None,
    'longitude': None,
    'altitude': None,
    'speed': None,
    'course': None,
    'satellites': 0,
    'hdop': None,
    'vdop': None,
    'pdop': None,
    'timestamp': None,
    'date': None,
    'fix_quality': 'Invalid',
    'fix_type': 'No Fix',
    'last_update': None,
    'sentences_parsed': 0,
    'sentences_failed': 0,
    'ntp_clients_served': 0,
    'satellites_in_view': [],
    'signal_quality': 'Poor',
    'time_accuracy': 'Unknown'
}

# NTP server statistics with thread lock
ntp_stats_lock = threading.Lock()
ntp_stats = {
    'requests': 0,
    'last_request': None,
    'clients': {}
}

# GPS Serial Reader Class
class GPSReader(threading.Thread):
    def __init__(self, port='/dev/ttyUSB0', baudrate=9600):
        super().__init__(daemon=True)
        self.port = port
        self.baudrate = baudrate
        self.serial = None
        self.running = False
        
    def find_gps_port(self):
        """Auto-detect GPS device"""
        ports = serial.tools.list_ports.comports()
        for port in ports:
            if any(x in port.description.lower() for x in ['gps', 'gnss', 'adafruit', 'cp210', 'ft232', 'ch340']):
                logger.info(f"Found potential GPS device: {port.device} - {port.description}")
                return port.device
            if any(x in str(port.hwid).lower() for x in ['067b:2303', '10c4:ea60', '1a86:7523']):
                logger.info(f"Found USB-Serial device: {port.device} - {port.description}")
                return port.device
        return None
        
    def connect(self):
        """Connect to GPS device"""
        try:
            if not os.path.exists(self.port):
                detected_port = self.find_gps_port()
                if detected_port:
                    self.port = detected_port
                    logger.info(f"Auto-detected GPS port: {self.port}")
                else:
                    logger.warning("No GPS device auto-detected, trying default port")
            
            self.serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=1.0,
                xonxoff=False,
                rtscts=False,
                dsrdtr=False
            )
            logger.info(f"Connected to GPS on {self.port} at {self.baudrate} baud")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to GPS: {e}")
            return False
    
    def configure_gps(self):
        """Send configuration commands to GPS module"""
        try:
            commands = [
                b'$PMTK314,0,1,0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0*28\r\n',  # RMC & GGA only
                b'$PMTK220,100*2F\r\n',  # Set update rate to 10Hz (100ms)
                b'$PMTK251,115200*1F\r\n',  # Set baud rate to 115200 (optional)
            ]
            
            for cmd in commands:
                self.serial.write(cmd)
                time.sleep(0.1)
            logger.info("GPS configuration commands sent")
        except Exception as e:
            logger.error(f"Failed to configure GPS: {e}")
    
    def parse_nmea(self, sentence):
        """Parse NMEA sentence and update global GPS data"""
        global gps_data
        try:
            msg = pynmea2.parse(sentence)
            with gps_data_lock:
                gps_data['sentences_parsed'] += 1
                gps_data['last_update'] = datetime.now(timezone.utc).isoformat()
            
            if isinstance(msg, pynmea2.RMC):
                with gps_data_lock:
                    if msg.status == 'A':
                        gps_data['status'] = 'ACTIVE'
                        gps_data['latitude'] = msg.latitude
                        gps_data['longitude'] = msg.longitude
                        gps_data['speed'] = msg.spd_over_grnd
                        gps_data['course'] = msg.true_course
                        gps_data['date'] = msg.datestamp.isoformat() if msg.datestamp else None
                        gps_data['timestamp'] = msg.timestamp.isoformat() if msg.timestamp else None
                    else:
                        gps_data['status'] = 'NO_FIX'
            
            elif isinstance(msg, pynmea2.GGA):
                with gps_data_lock:
                    gps_data['fix_quality'] = self.get_fix_quality(msg.gps_qual)
                    gps_data['satellites'] = msg.num_sats
                    gps_data['hdop'] = msg.horizontal_dil
                    gps_data['altitude'] = msg.altitude
                    gps_data['timestamp'] = msg.timestamp.isoformat() if msg.timestamp else None
                    if msg.num_sats >= 8:
                        gps_data['signal_quality'] = 'Excellent'
                    elif msg.num_sats >= 6:
                        gps_data['signal_quality'] = 'Good'
                    elif msg.num_sats >= 4:
                        gps_data['signal_quality'] = 'Fair'
                    else:
                        gps_data['signal_quality'] = 'Poor'
            
            elif isinstance(msg, pynmea2.GSA):
                with gps_data_lock:
                    gps_data['fix_type'] = self.get_fix_type(msg.mode_fix_type)
                    gps_data['pdop'] = msg.pdop
                    gps_data['hdop'] = msg.hdop
                    gps_data['vdop'] = msg.vdop
            
            elif isinstance(msg, pynmea2.GSV):
                with gps_data_lock:
                    if msg.msg_num == '1':
                        gps_data['satellites_in_view'] = []
                    for i in range(4):
                        try:
                            sat_num = getattr(msg, f'sv_prn_num_{i+1}')
                            elevation = getattr(msg, f'elevation_deg_{i+1}')
                            azimuth = getattr(msg, f'azimuth_{i+1}')
                            snr = getattr(msg, f'snr_{i+1}')
                            if sat_num:
                                gps_data['satellites_in_view'].append({
                                    'prn': sat_num,
                                    'elevation': elevation,
                                    'azimuth': azimuth,
                                    'snr': snr
                                })
                        except AttributeError:
                            break
            
            elif isinstance(msg, pynmea2.VTG):
                with gps_data_lock:
                    gps_data['speed'] = msg.spd_over_grnd_kts
                    gps_data['course'] = msg.true_track
                
        except pynmea2.ParseError as e:
            with gps_data_lock:
                gps_data['sentences_failed'] += 1
            logger.debug(f"Failed to parse NMEA: {e}")
        except Exception as e:
            with gps_data_lock:
                gps_data['sentences_failed'] += 1
            logger.error(f"Error parsing NMEA: {e}")
    
    def get_fix_quality(self, qual):
        """Convert GPS quality indicator to readable string"""
        qualities = {
            0: 'Invalid',
            1: 'GPS fix',
            2: 'DGPS fix',
            3: 'PPS fix',
            4: 'RTK fixed',
            5: 'RTK float',
            6: 'Estimated',
            7: 'Manual',
            8: 'Simulation'
        }
        return qualities.get(qual, 'Unknown')
    
    def get_fix_type(self, fix):
        """Convert fix type to readable string"""
        fix_types = {
            '1': 'No Fix',
            '2': '2D Fix',
            '3': '3D Fix'
        }
        return fix_types.get(fix, 'Unknown')
    
    def run(self):
        """Main GPS reading loop"""
        self.running = True
        retry_count = 0
        max_retries = 5
        total_attempts = 0
        max_total_attempts = 20
        
        while self.running and total_attempts < max_total_attempts:
            if not self.serial or not self.serial.is_open:
                if retry_count < max_retries:
                    logger.info(f"Attempting to connect to GPS (attempt {retry_count + 1}/{max_retries})")
                    if self.connect():
                        self.configure_gps()
                        retry_count = 0
                    else:
                        retry_count += 1
                        total_attempts += 1
                        time.sleep(5)
                        continue
                else:
                    logger.error("Max retries reached. Waiting 30 seconds before trying again.")
                    time.sleep(30)
                    retry_count = 0
                    total_attempts += 1
                    continue
            
            try:
                if self.serial.in_waiting:
                    line = self.serial.readline()
                    if line:
                        try:
                            sentence = line.decode('ascii', errors='ignore').strip()
                            if sentence.startswith('$'):
                                self.parse_nmea(sentence)
                        except UnicodeDecodeError:
                            pass
            except serial.SerialException as e:
                logger.error(f"Serial error: {e}")
                if self.serial:
                    self.serial.close()
                time.sleep(5)
            except Exception as e:
                logger.error(f"Unexpected error in GPS reader: {e}")
                time.sleep(1)
        
        if total_attempts >= max_total_attempts:
            logger.error("Maximum total connection attempts reached. Exiting GPS reader.")
            self.running = False
    
    def stop(self):
        """Stop GPS reading"""
        self.running = False
        if self.serial and self.serial.is_open:
            self.serial.close()

# NTP Server Class
class NTPServer(threading.Thread):
    def __init__(self, port=123):
        super().__init__(daemon=True)
        self.port = port
        self.sock = None
        self.running = False
        
    def run(self):
        """Main NTP server loop"""
        self.running = True
        
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                self.sock.bind(('', self.port))
            except PermissionError:
                logger.error(f"Permission denied binding to port {self.port}. Run with sudo or use --ntp-port with a port > 1024 (e.g., 1234)")
                return
            self.sock.settimeout(1.0)
            logger.info(f"NTP server started on port {self.port}")
            
            while self.running:
                try:
                    data, addr = self.sock.recvfrom(1024)
                    if len(data) >= 48:
                        self.handle_ntp_request(data, addr)
                except socket.timeout:
                    continue
                except Exception as e:
                    logger.error(f"NTP server error: {e}")
                    
        except Exception as e:
            logger.error(f"Failed to start NTP server: {e}")
        finally:
            if self.sock:
                self.sock.close()
    
    def handle_ntp_request(self, data, addr):
        """Handle NTP client request"""
        global gps_data, ntp_stats
        
        with gps_data_lock:
            if not gps_data.get('timestamp') or not gps_data.get('date') or gps_data.get('status') != 'ACTIVE':
                logger.warning(f"NTP request from {addr[0]} rejected - no valid GPS time")
                return
        
        try:
            unpacked = struct.unpack('!B B B b 11I', data[:48])
            NTP_EPOCH = datetime(1900, 1, 1, tzinfo=timezone.utc)
            
            with gps_data_lock:
                gps_time_str = f"{gps_data['date']}T{gps_data['timestamp']}"
            try:
                gps_time = datetime.fromisoformat(gps_time_str).replace(tzinfo=timezone.utc)
            except (ValueError, TypeError) as e:
                logger.error(f"Error parsing GPS time: {e}")
                return
            
            ntp_timestamp = (gps_time - NTP_EPOCH).total_seconds()
            ntp_timestamp_int = int(ntp_timestamp)
            ntp_timestamp_frac = int((ntp_timestamp - ntp_timestamp_int) * 2**32)
            
            response = struct.pack('!B B B b 11I',
                0x1C, 1, 3, -6, 0, 0, 0x47505300,
                ntp_timestamp_int, ntp_timestamp_frac,
                unpacked[7], unpacked[8],
                ntp_timestamp_int, ntp_timestamp_frac,
                ntp_timestamp_int, ntp_timestamp_frac
            )
            
            self.sock.sendto(response, addr)
            
            with ntp_stats_lock:
                ntp_stats['requests'] += 1
                ntp_stats['last_request'] = datetime.now(timezone.utc).isoformat()
                if addr[0] not in ntp_stats['clients']:
                    ntp_stats['clients'][addr[0]] = 0
                ntp_stats['clients'][addr[0]] += 1
                with gps_data_lock:
                    gps_data['ntp_clients_served'] = ntp_stats['requests']
            
            logger.info(f"NTP request served to {addr[0]}")
            
        except Exception as e:
            logger.error(f"Error handling NTP request: {e}")
    
    def stop(self):
        """Stop NTP server"""
        self.running = False
        if self.sock:
            self.sock.close()

# Web Interface HTML Template
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>GPS NTP Server Dashboard</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        h1 {
            color: white;
            text-align: center;
            margin-bottom: 30px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }
        .card {
            background: white;
            border-radius: 10px;
            padding: 20px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
        }
        .card h2 {
            color: #333;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 2px solid #667eea;
        }
        .status-indicator {
            display: inline-block;
            width: 12px;
            height: 12px;
            border-radius: 50%;
            margin-right: 8px;
        }
        .status-active { background: #4caf50; animation: pulse 2s infinite; }
        .status-waiting { background: #ff9800; animation: pulse 2s infinite; }
        .status-error { background: #f44336; }
        @keyframes pulse {
            0% { opacity: 1; }
            50% { opacity: 0.6; }
            100% { opacity: 1; }
        }
        .data-row {
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid #eee;
        }
        .data-label {
            font-weight: 600;
            color: #666;
        }
        .data-value {
            color: #333;
            font-family: 'Courier New', monospace;
        }
        .map-container {
            height: 400px;
            border-radius: 10px;
            overflow: hidden;
            margin-top: 20px;
        }
        #map {
            width: 100%;
            height: 100%;
        }
        .satellite-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(80px, 1fr));
            gap: 10px;
            margin-top: 15px;
        }
        .satellite-item {
            background: #f5f5f5;
            padding: 8px;
            border-radius: 5px;
            text-align: center;
            font-size: 12px;
        }
        .satellite-snr {
            font-weight: bold;
            color: #667eea;
        }
        .alert {
            padding: 12px;
            border-radius: 5px;
            margin-bottom: 20px;
            text-align: center;
            font-weight: 600;
        }
        .alert-warning {
            background: #fff3cd;
            color: #856404;
            border: 1px solid #ffeeba;
        }
        .alert-success {
            background: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
        }
        .instructions {
            background: #e3f2fd;
            border: 1px solid #90caf9;
            color: #0d47a1;
            padding: 15px;
            border-radius: 5px;
            margin-top: 20px;
        }
        .instructions h3 {
            margin-bottom: 10px;
        }
        .instructions code {
            background: white;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: monospace;
        }
    </style>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.7.1/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.7.1/dist/leaflet.js"></script>
</head>
<body>
    <div class="container">
        <h1>🛰️ GPS NTP Server Dashboard</h1>
        
        {% if ntp_stats_available %}
        <div style="text-align: center; margin-bottom: 20px;">
            <a href="/stats" style="background: white; color: #667eea; padding: 10px 20px; border-radius: 5px; text-decoration: none; font-weight: bold; display: inline-block; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
                📊 View NTP Statistics & Server Comparison
            </a>
        </div>
        {% endif %}
        
        <div id="status-alert" class="alert alert-warning">
            <span class="status-indicator status-waiting"></span>
            Waiting for GPS signal...
        </div>
        
        <div class="grid">
            <div class="card">
                <h2>📍 GPS Status</h2>
                <div class="data-row">
                    <span class="data-label">Status:</span>
                    <span class="data-value" id="status">NO_FIX</span>
                </div>
                <div class="data-row">
                    <span class="data-label">Fix Quality:</span>
                    <span class="data-value" id="fix-quality">Invalid</span>
                </div>
                <div class="data-row">
                    <span class="data-label">Fix Type:</span>
                    <span class="data-value" id="fix-type">No Fix</span>
                </div>
                <div class="data-row">
                    <span class="data-label">Satellites:</span>
                    <span class="data-value" id="satellites">0</span>
                </div>
                <div class="data-row">
                    <span class="data-label">Signal Quality:</span>
                    <span class="data-value" id="signal-quality">Poor</span>
                </div>
                <div class="data-row">
                    <span class="data-label">HDOP:</span>
                    <span class="data-value" id="hdop">--</span>
                </div>
            </div>
            
            <div class="card">
                <h2>🌍 Position</h2>
                <div class="data-row">
                    <span class="data-label">Latitude:</span>
                    <span class="data-value" id="latitude">--</span>
                </div>
                <div class="data-row">
                    <span class="data-label">Longitude:</span>
                    <span class="data-value" id="longitude">--</span>
                </div>
                <div class="data-row">
                    <span class="data-label">Altitude:</span>
                    <span class="data-value" id="altitude">--</span>
                </div>
                <div class="data-row">
                    <span class="data-label">Speed:</span>
                    <span class="data-value" id="speed">--</span>
                </div>
                <div class="data-row">
                    <span class="data-label">Course:</span>
                    <span class="data-value" id="course">--</span>
                </div>
            </div>
            
            <div class="card">
                <h2>⏰ Time Information</h2>
                <div class="data-row">
                    <span class="data-label">GPS Time:</span>
                    <span class="data-value" id="gps-time">--</span>
                </div>
                <div class="data-row">
                    <span class="data-label">GPS Date:</span>
                    <span class="data-value" id="gps-date">--</span>
                </div>
                <div class="data-row">
                    <span class="data-label">Last Update:</span>
                    <span class="data-value" id="last-update">--</span>
                </div>
                <div class="data-row">
                    <span class="data-label">System Time:</span>
                    <span class="data-value" id="system-time">--</span>
                </div>
            </div>
            
            <div class="card">
                <h2>📊 Statistics</h2>
                <div class="data-row">
                    <span class="data-label">Sentences Parsed:</span>
                    <span class="data-value" id="sentences-parsed">0</span>
                </div>
                <div class="data-row">
                    <span class="data-label">Parse Errors:</span>
                    <span class="data-value" id="sentences-failed">0</span>
                </div>
                <div class="data-row">
                    <span class="data-label">NTP Requests:</span>
                    <span class="data-value" id="ntp-requests">0</span>
                </div>
                <div class="data-row">
                    <span class="data-label">NTP Clients:</span>
                    <span class="data-value" id="ntp-clients">0</span>
                </div>
            </div>
        </div>
        
        <div class="card">
            <h2>🛰️ Satellites in View</h2>
            <div id="satellite-grid" class="satellite-grid"></div>
        </div>
        
        <div class="map-container">
            <div id="map"></div>
        </div>
        
        <div class="card instructions">
            <h3>🔧 NTP Client Configuration</h3>
            <p>To use this GPS NTP server, configure your systems with:</p>
            <ul style="margin: 10px 0 10px 30px;">
                <li>Server: <code id="server-ip">detecting...</code></li>
                <li>Port: <code>{{ ntp_port }}</code></li>
            </ul>
            <p><strong>Linux:</strong> Add <code>server <span class="server-ip-text">YOUR_SERVER_IP</span> iburst</code> to /etc/ntp.conf</p>
            <p><strong>Windows:</strong> <code>w32tm /config /manualpeerlist:"<span class="server-ip-text">YOUR_SERVER_IP</span>" /syncfromflags:manual</code></p>
            <p><strong>Test:</strong> <code>ntpdate -q <span class="server-ip-text">YOUR_SERVER_IP</span></code></p>
        </div>
    </div>
    
    <script>
        let map = null;
        let marker = null;
        
        function initMap() {
            map = L.map('map').setView([0, 0], 2);
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '© OpenStreetMap contributors'
            }).addTo(map);
        }
        
        function updateMap(lat, lon) {
            if (map && lat && lon) {
                const position = [lat, lon];
                if (marker) {
                    marker.setLatLng(position);
                } else {
                    marker = L.marker(position).addTo(map);
                }
                map.setView(position, 15);
            }
        }
        
        function formatValue(value, suffix = '') {
            if (value === null || value === undefined) return '--';
            if (suffix) return value + suffix;
            return value;
        }
        
        function updateDashboard() {
            fetch('/api/gps')
                .then(response => {
                    if (!response.ok) throw new Error('Failed to fetch GPS data');
                    return response.json();
                })
                .then(data => {
                    const alertDiv = document.getElementById('status-alert');
                    const statusIndicator = alertDiv.querySelector('.status-indicator');
                    
                    if (data.status === 'ACTIVE') {
                        alertDiv.className = 'alert alert-success';
                        statusIndicator.className = 'status-indicator status-active';
                        alertDiv.innerHTML = '<span class="status-indicator status-active"></span>GPS Active - ' + 
                                           data.satellites + ' satellites in use';
                    } else {
                        alertDiv.className = 'alert alert-warning';
                        statusIndicator.className = 'status-indicator status-waiting';
                        alertDiv.innerHTML = '<span class="status-indicator status-waiting"></span>Waiting for GPS signal...';
                    }
                    
                    document.getElementById('status').textContent = data.status;
                    document.getElementById('fix-quality').textContent = data.fix_quality;
                    document.getElementById('fix-type').textContent = data.fix_type;
                    document.getElementById('satellites').textContent = data.satellites;
                    document.getElementById('signal-quality').textContent = data.signal_quality;
                    document.getElementById('hdop').textContent = formatValue(data.hdop);
                    document.getElementById('latitude').textContent = formatValue(data.latitude, '°');
                    document.getElementById('longitude').textContent = formatValue(data.longitude, '°');
                    document.getElementById('altitude').textContent = formatValue(data.altitude, ' m');
                    document.getElementById('speed').textContent = formatValue(data.speed, ' knots');
                    document.getElementById('course').textContent = formatValue(data.course, '°');
                    document.getElementById('gps-time').textContent = formatValue(data.timestamp);
                    document.getElementById('gps-date').textContent = formatValue(data.date);
                    document.getElementById('last-update').textContent = formatValue(data.last_update);
                    document.getElementById('sentences-parsed').textContent = data.sentences_parsed;
                    document.getElementById('sentences-failed').textContent = data.sentences_failed;
                    document.getElementById('ntp-requests').textContent = data.ntp_clients_served;
                    
                    const satGrid = document.getElementById('satellite-grid');
                    if (data.satellites_in_view && data.satellites_in_view.length > 0) {
                        satGrid.innerHTML = data.satellites_in_view.map(sat => `
                            <div class="satellite-item">
                                <div>PRN ${sat.prn}</div>
                                <div class="satellite-snr">${sat.snr || '--'} dB</div>
                                <div style="font-size: 10px;">El: ${sat.elevation || '--'}°</div>
                            </div>
                        `).join('');
                    } else {
                        satGrid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; color: #999;">No satellites in view</div>';
                    }
                    
                    if (data.latitude && data.longitude) {
                        updateMap(data.latitude, data.longitude);
                    }
                })
                .catch(error => {
                    console.error('Error fetching GPS data:', error);
                    document.getElementById('status-alert').className = 'alert alert-warning';
                    document.getElementById('status-alert').innerHTML = '<span class="status-indicator status-error"></span>Error fetching GPS data';
                });
            
            fetch('/api/ntp')
                .then(response => {
                    if (!response.ok) throw new Error('Failed to fetch NTP stats');
                    return response.json();
                })
                .then(data => {
                    document.getElementById('ntp-clients').textContent = Object.keys(data.clients).length;
                })
                .catch(error => {
                    console.error('Error fetching NTP stats:', error);
                });
        }
        
        function updateSystemTime() {
            const now = new Date();
            document.getElementById('system-time').textContent = now.toISOString();
        }
        
        function getServerIP() {
            fetch('/api/server-info')
                .then(response => {
                    if (!response.ok) throw new Error('Failed to fetch server info');
                    return response.json();
                })
                .then(data => {
                    document.getElementById('server-ip').textContent = data.ip + ':' + data.ntp_port;
                    document.querySelectorAll('.server-ip-text').forEach(el => {
                        el.textContent = data.ip;
                    });
                })
                .catch(error => console.error('Error fetching server info:', error));
        }
        
        initMap();
        getServerIP();
        updateDashboard();
        updateSystemTime();
        
        setInterval(updateDashboard, 1000);
        setInterval(updateSystemTime, 1000);
    </script>
</body>
</html>
'''

# Flask Routes
@app.route('/')
def index():
    """Serve main dashboard"""
    return render_template_string(HTML_TEMPLATE, ntp_port=app.config.get('NTP_PORT', 123), ntp_stats_available=NTP_STATS_AVAILABLE)

@app.route('/api/gps')
def api_gps():
    """Return GPS data as JSON"""
    with gps_data_lock:
        return jsonify(gps_data)

@app.route('/api/ntp')
def api_ntp():
    """Return NTP statistics as JSON"""
    with ntp_stats_lock:
        return jsonify(ntp_stats)

@app.route('/api/server-info')
def api_server_info():
    """Return server information"""
    hostname = socket.gethostname()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]  # Fixed: Use getsockname() instead of getvalue()
        s.close()
    except Exception:
        ip = socket.gethostbyname(hostname)
    
    return jsonify({
        'hostname': hostname,
        'ip': ip,
        'ntp_port': app.config.get('NTP_PORT', 123),
        'web_port': app.config.get('WEB_PORT', 5000)
    })

@app.route('/api/config', methods=['GET'])
def api_config():
    """Get configuration"""
    return jsonify({
        'gps_port': gps_reader.port if 'gps_reader' in globals() else '/dev/ttyUSB0',
        'gps_baudrate': gps_reader.baudrate if 'gps_reader' in globals() else 9600,
        'ntp_port': app.config.get('NTP_PORT', 123),
        'web_port': app.config.get('WEB_PORT', 5000)
    })

def validate_port(port, name):
    """Validate port number"""
    if not (0 < port <= 65535):
        parser.error(f"{name} must be between 1 and 65535")
    return port

def main():
    """Main function"""
    global gps_reader, ntp_server
    
    parser = argparse.ArgumentParser(description='GPS Web Server and NTP Time Server')
    parser.add_argument('--gps-port', default='/dev/ttyUSB0', help='GPS serial port (default: /dev/ttyUSB0)')
    parser.add_argument('--gps-baud', type=int, default=9600, help='GPS baud rate (default: 9600)')
    parser.add_argument('--web-port', type=lambda x: validate_port(int(x), 'Web port'), default=5000, help='Web server port (default: 5000)')
    parser.add_argument('--ntp-port', type=lambda x: validate_port(int(x), 'NTP port'), default=123, help='NTP server port (default: 123)')
    parser.add_argument('--no-ntp', action='store_true', help='Disable NTP server')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    app.config['NTP_PORT'] = args.ntp_port
    app.config['WEB_PORT'] = args.web_port
    
    logger.info("Starting GPS reader...")
    gps_reader = GPSReader(port=args.gps_port, baudrate=args.gps_baud)
    gps_reader.start()
    
    if not args.no_ntp:
        logger.info("Starting NTP server...")
        ntp_server = NTPServer(port=args.ntp_port)
        ntp_server.start()
        
        if NTP_STATS_AVAILABLE:
            logger.info("Initializing NTP monitoring...")
            custom_servers = [
                {'address': '127.0.0.1', 'port': args.ntp_port, 'name': 'Local GPS (This Server)'}
            ]
            init_ntp_monitor(custom_servers)
    
    logger.info(f"Starting web server on port {args.web_port}...")
    logger.info(f"Open http://localhost:{args.web_port} in your browser")
    
    try:
        app.run(host='0.0.0.0', port=args.web_port, debug=False)
    except OSError as e:
        logger.error(f"Failed to start web server: {e}")
        gps_reader.stop()
        if not args.no_ntp:
            ntp_server.stop()
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        gps_reader.stop()
        if not args.no_ntp:
            ntp_server.stop()
        sys.exit(0)

if __name__ == '__main__':
    main()
