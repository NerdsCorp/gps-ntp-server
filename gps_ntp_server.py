#!/usr/bin/env python3
"""
GPS-based NTP Server
Serves NTP responses using GPS time from a serial GPS module
"""

import socket
import struct
import time
import threading
import serial
import pynmea2
import logging
from datetime import datetime, timezone
from flask import Flask, Response
from flask_cors import CORS

# Configure logging before imports that might fail
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

class GPSNTP:
    """GPS-based NTP Server"""
    
    def __init__(self, serial_port='/dev/ttyUSB0', baudrate=9600, ntp_port=123):
        self.serial_port = serial_port
        self.baudrate = baudrate
        self.ntp_port = ntp_port
        self.running = False
        self.gps_time = None
        self.gps_lock = threading.Lock()
        self.serial = None
        self.ntp_socket = None
        # Add tracking for GPS fix quality
        self.last_gps_update = None
        self.gps_fix_quality = 0
        
    def read_gps(self):
        """Read GPS data from serial port"""
        while self.running:
            try:
                if not self.serial or not self.serial.is_open:
                    self.serial = serial.Serial(self.serial_port, self.baudrate, timeout=1)
                    logger.info(f"Connected to GPS on {self.serial_port}")
                
                line = self.serial.readline().decode('ascii', errors='ignore').strip()
                if not line:
                    continue
                    
                if line.startswith('$G'):
                    try:
                        msg = pynmea2.parse(line)
                        
                        # Process different message types
                        if isinstance(msg, pynmea2.types.talker.RMC):
                            # RMC messages contain date and time
                            if msg.status == 'A' and msg.datetime:  # A = valid data
                                with self.gps_lock:
                                    self.gps_time = msg.datetime.replace(tzinfo=timezone.utc)
                                    self.last_gps_update = time.time()
                                    logger.debug(f"GPS time updated from RMC: {self.gps_time}")
                                    
                        elif isinstance(msg, pynmea2.types.talker.GGA):
                            # GGA messages contain fix quality
                            if msg.gps_qual > 0:
                                with self.gps_lock:
                                    self.gps_fix_quality = msg.gps_qual
                                    # Only update time if we have valid timestamp AND date
                                    if msg.timestamp and self.gps_time:
                                        # Update time portion from more precise GGA
                                        current_date = self.gps_time.date()
                                        self.gps_time = datetime.combine(
                                            current_date,
                                            msg.timestamp,
                                            tzinfo=timezone.utc
                                        )
                                        self.last_gps_update = time.time()
                                        logger.debug(f"GPS time refined from GGA: {self.gps_time}")
                                        
                    except pynmea2.ParseError as e:
                        logger.debug(f"Failed to parse NMEA sentence: {line[:50]}...")
                    except AttributeError as e:
                        logger.debug(f"NMEA message missing expected attributes: {e}")
                        
            except serial.SerialException as e:
                logger.error(f"Serial port error: {e}")
                if self.serial and self.serial.is_open:
                    self.serial.close()
                self.serial = None
                time.sleep(5)  # Wait before reconnecting
                
            except Exception as e:
                logger.error(f"Unexpected GPS error: {e}")
                time.sleep(1)
                
        # Cleanup on exit
        if self.serial and self.serial.is_open:
            self.serial.close()
            logger.info("Serial port closed")

    def ntp_response(self, data, client_addr):
        """Generate NTP response packet"""
        try:
            # Record when we received the request
            receive_timestamp = time.time()
            
            # Check if we have valid GPS time
            with self.gps_lock:
                if not self.gps_time:
                    logger.warning("No GPS time available")
                    return None
                    
                # Check if GPS time is stale (>10 seconds old)
                if self.last_gps_update and (time.time() - self.last_gps_update) > 10:
                    logger.warning("GPS time is stale")
                    return None
                
                # Get current GPS time (with system clock offset since last update)
                time_since_update = time.time() - self.last_gps_update if self.last_gps_update else 0
                current_gps_time = self.gps_time + timedelta(seconds=time_since_update)
                
            # Check packet is valid NTP request
            if len(data) < 48:
                logger.warning(f"Invalid NTP packet size: {len(data)}")
                return None
                
            # Unpack client request
            unpacked = struct.unpack('!B B B b 11I', data[:48])
            
            # Extract client transmit timestamp
            client_transmit_int = unpacked[10]
            client_transmit_frac = unpacked[11]
            
            # NTP epoch is 1900-01-01
            ntp_epoch = datetime(1900, 1, 1, tzinfo=timezone.utc)
            unix_epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
            
            # Convert timestamps to NTP format
            # GPS time to NTP timestamp
            gps_ntp_timestamp = (current_gps_time - ntp_epoch).total_seconds()
            
            # Convert receive and transmit times from Unix to NTP
            ntp_unix_offset = (unix_epoch - ntp_epoch).total_seconds()
            receive_ntp_timestamp = receive_timestamp + ntp_unix_offset
            transmit_timestamp = time.time()
            transmit_ntp_timestamp = transmit_timestamp + ntp_unix_offset
            
            # Create response packet
            response = bytearray(48)
            
            # Header: LI=0, VN=4, Mode=4 (server)
            response[0] = 0x24  # 00 100 100 = LI=0, VN=4, Mode=4
            response[1] = 1     # Stratum 1 (GPS)
            response[2] = 6     # Poll interval (2^6 = 64 seconds)
            response[3] = 0xEC  # Precision (2^-20 ≈ 1 microsecond)
            
            # Root delay and dispersion (both 0 for stratum 1)
            struct.pack_into('!I', response, 4, 0)  # Root delay
            struct.pack_into('!I', response, 8, 0)  # Root dispersion
            
            # Reference ID: 'GPS ' for GPS source
            response[12:16] = b'GPS '
            
            # Reference timestamp (last GPS update)
            struct.pack_into('!I', response, 16, int(gps_ntp_timestamp))
            struct.pack_into('!I', response, 20, int((gps_ntp_timestamp % 1) * 2**32))
            
            # Originate timestamp (copy from client transmit timestamp)
            struct.pack_into('!I', response, 24, client_transmit_int)
            struct.pack_into('!I', response, 28, client_transmit_frac)
            
            # Receive timestamp (when we received the request)
            struct.pack_into('!I', response, 32, int(receive_ntp_timestamp))
            struct.pack_into('!I', response, 36, int((receive_ntp_timestamp % 1) * 2**32))
            
            # Transmit timestamp (when we're sending the response)
            struct.pack_into('!I', response, 40, int(transmit_ntp_timestamp))
            struct.pack_into('!I', response, 44, int((transmit_ntp_timestamp % 1) * 2**32))
            
            return response
            
        except Exception as e:
            logger.error(f"Error generating NTP response: {e}")
            return None

    def ntp_server(self):
        """Run NTP server"""
        while self.running:
            try:
                if not self.ntp_socket:
                    self.ntp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    self.ntp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    self.ntp_socket.settimeout(1.0)  # Add timeout for clean shutdown
                    self.ntp_socket.bind(('', self.ntp_port))
                    logger.info(f"NTP server listening on port {self.ntp_port}")
                
                try:
                    data, client_addr = self.ntp_socket.recvfrom(1024)
                    logger.debug(f"Received NTP request from {client_addr}")
                    
                    response = self.ntp_response(data, client_addr)
                    if response:
                        self.ntp_socket.sendto(response, client_addr)
                        logger.debug(f"Sent NTP response to {client_addr}")
                    else:
                        logger.warning(f"Failed to generate response for {client_addr}")
                        
                except socket.timeout:
                    continue  # Normal timeout, check if still running
                    
            except OSError as e:
                if e.errno == 13:  # Permission denied
                    logger.error(f"Permission denied on port {self.ntp_port}. Try a port > 1024 or run with sudo")
                    break
                elif e.errno == 98:  # Address already in use
                    logger.error(f"Port {self.ntp_port} is already in use")
                    break
                else:
                    logger.error(f"Socket error: {e}")
                    time.sleep(5)
                    
            except Exception as e:
                logger.error(f"NTP server error: {e}")
                time.sleep(1)
                
        # Cleanup
        if self.ntp_socket:
            self.ntp_socket.close()
            self.ntp_socket = None
            logger.info("NTP socket closed")

    def start(self):
        """Start GPS and NTP services"""
        self.running = True
        
        # Start GPS reader thread
        gps_thread = threading.Thread(target=self.read_gps, daemon=True)
        gps_thread.start()
        logger.info("Started GPS reader thread")
        
        # Start NTP server thread
        ntp_thread = threading.Thread(target=self.ntp_server, daemon=True)
        ntp_thread.start()
        logger.info("Started NTP server thread")
        
        # Initialize NTP monitor if available
        if init_ntp_monitor:
            try:
                # Use port 1123 if running on standard NTP port fails
                monitor_port = self.ntp_port if self.ntp_port != 123 else 1123
                init_ntp_monitor([
                    {'address': 'localhost', 'port': monitor_port, 'name': 'Local GPS NTP'}
                ])
                logger.info(f"NTP monitor initialized with local server on port {monitor_port}")
            except Exception as e:
                logger.error(f"Failed to initialize NTP monitor: {e}")

    def stop(self):
        """Stop GPS and NTP services"""
        logger.info("Stopping GPS NTP server...")
        self.running = False
        
        # Give threads time to exit cleanly
        time.sleep(2)
        
        # Close connections
        if self.serial and self.serial.is_open:
            self.serial.close()
        if self.ntp_socket:
            self.ntp_socket.close()
            
        logger.info("GPS NTP server stopped")
        
    def get_status(self):
        """Get current server status"""
        with self.gps_lock:
            return {
                'running': self.running,
                'gps_time': self.gps_time.isoformat() if self.gps_time else None,
                'gps_fix_quality': self.gps_fix_quality,
                'last_update': self.last_gps_update,
                'time_since_update': time.time() - self.last_gps_update if self.last_gps_update else None
            }

@app.route('/')
def index():
    """Serve basic status page"""
    if 'server' in globals():
        status = server.get_status()
        return Response(
            f"GPS NTP Server Status:\n"
            f"Running: {status['running']}\n"
            f"GPS Time: {status['gps_time']}\n"
            f"Fix Quality: {status['gps_fix_quality']}\n"
            f"Time Since Last Update: {status['time_since_update']:.1f}s\n\n"
            f"Access /stats for detailed statistics",
            mimetype='text/plain'
        )
    return Response("GPS NTP Server\nAccess /stats for statistics", mimetype='text/plain')

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='GPS-based NTP Server')
    parser.add_argument('--serial', default='/dev/ttyUSB0', help='GPS serial port')
    parser.add_argument('--baudrate', type=int, default=9600, help='GPS baudrate')
    parser.add_argument('--ntp-port', type=int, default=1123, help='NTP server port (use 1123 to avoid needing root)')
    parser.add_argument('--web-port', type=int, default=5000, help='Web interface port')
    args = parser.parse_args()
    
    # Create and start server
    server = GPSNTP(serial_port=args.serial, baudrate=args.baudrate, ntp_port=args.ntp_port)
    
    try:
        server.start()
        logger.info(f"Starting web interface on port {args.web_port}")
        app.run(host='0.0.0.0', port=args.web_port, debug=False)
    except KeyboardInterrupt:
        logger.info("Shutting down server...")
    except Exception as e:
        logger.error(f"Server error: {e}")
    finally:
        server.stop()
