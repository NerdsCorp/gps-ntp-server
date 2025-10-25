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
        
    def read_gps(self):
        """Read GPS data from serial port"""
        try:
            self.serial = serial.Serial(self.serial_port, self.baudrate, timeout=1)
            logger.info(f"Connected to GPS on {self.serial_port}")
            
            while self.running:
                try:
                    line = self.serial.readline().decode('ascii', errors='ignore').strip()
                    if line.startswith('$G'):
                        msg = pynmea2.parse(line)
                        if isinstance(msg, pynmea2.types.talker.GGA) and msg.gps_qual > 0:
                            with self.gps_lock:
                                if msg.timestamp:
                                    self.gps_time = datetime.combine(
                                        msg.datestamp,
                                        msg.timestamp,
                                        tzinfo=timezone.utc
                                    )
                                    logger.debug(f"GPS time updated: {self.gps_time}")
                except (pynmea2.ParseError, UnicodeDecodeError, serial.SerialException) as e:
                    logger.error(f"GPS read error: {e}")
                    time.sleep(1)
                except Exception as e:
                    logger.error(f"Unexpected GPS error: {e}")
                    time.sleep(1)
                    
        except serial.SerialException as e:
            logger.error(f"Failed to open serial port {self.serial_port}: {e}")
            time.sleep(5)
        finally:
            if self.serial and self.serial.is_open:
                self.serial.close()
                logger.info("Serial port closed")

    def ntp_response(self, data, client_addr):
        """Generate NTP response packet"""
        try:
            received = time.time()
            with self.gps_lock:
                if not self.gps_time:
                    logger.warning("No GPS time available")
                    return None
                
                # NTP epoch is 1900-01-01
                ntp_epoch = datetime(1900, 1, 1, tzinfo=timezone.utc)
                gps_timestamp = (self.gps_time - ntp_epoch).total_seconds()
                
                # Unpack client request
                unpacked = struct.unpack('!B B B b 11I', data[:48])
                client_transmit = unpacked[10] + (unpacked[11] / 2**32)
                
                # Create response packet
                response = bytearray(48)
                response[0] = 0x24  # LI=0, VN=4, Mode=4 (server)
                response[1] = 1     # Stratum 1 (GPS)
                response[2] = 6     # Poll interval
                response[3] = -20   # Precision (~1us)
                
                # Reference ID: GPS
                struct.pack_into('!4s', response, 12, b'GPS ')
                
                # Timestamps
                ref_timestamp = gps_timestamp
                recv_timestamp = received + (datetime(1970, 1, 1, tzinfo=timezone.utc) - ntp_epoch).total_seconds()
                trans_timestamp = time.time() + (datetime(1970, 1, 1, tzinfo=timezone.utc) - ntp_epoch).total_seconds()
                
                struct.pack_into('!I', response, 24, int(ref_timestamp))
                struct.pack_into('!I', response, 28, int((ref_timestamp % 1) * 2**32))
                struct.pack_into('!I', response, 32, int(recv_timestamp))
                struct.pack_into('!I', response, 36, int((recv_timestamp % 1) * 2**32))
                struct.pack_into('!I', response, 40, int(client_transmit))
                struct.pack_into('!I', response, 44, int((client_transmit % 1) * 2**32))
                struct.pack_into('!I', response, 48, int(trans_timestamp))
                struct.pack_into('!I', response, 52, int((trans_timestamp % 1) * 2**32))
                
                return response
                
        except Exception as e:
            logger.error(f"Error generating NTP response: {e}")
            return None

    def ntp_server(self):
        """Run NTP server"""
        try:
            self.ntp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.ntp_socket.bind(('', self.ntp_port))
            logger.info(f"NTP server listening on port {self.ntp_port}")
            
            while self.running:
                try:
                    data, client_addr = self.ntp_socket.recvfrom(1024)
                    response = self.ntp_response(data, client_addr)
                    if response:
                        self.ntp_socket.sendto(response, client_addr)
                        logger.debug(f"Sent NTP response to {client_addr}")
                except socket.timeout:
                    continue
                except Exception as e:
                    logger.error(f"NTP server error: {e}")
                    
        except Exception as e:
            logger.error(f"Failed to start NTP server: {e}")
        finally:
            if self.ntp_socket:
                self.ntp_socket.close()
                logger.info("NTP socket closed")

    def start(self):
        """Start GPS and NTP services"""
        self.running = True
        
        # Start GPS reader thread
        gps_thread = threading.Thread(target=self.read_gps, daemon=True)
        gps_thread.start()
        
        # Start NTP server thread
        ntp_thread = threading.Thread(target=self.ntp_server, daemon=True)
        ntp_thread.start()
        
        # Initialize NTP monitor if available
        if init_ntp_monitor:
            try:
                init_ntp_monitor([
                    {'address': 'localhost', 'port': self.ntp_port, 'name': 'Local GPS NTP'}
                ])
                logger.info("NTP monitor initialized with local server")
            except Exception as e:
                logger.error(f"Failed to initialize NTP monitor: {e}")

    def stop(self):
        """Stop GPS and NTP services"""
        self.running = False
        if self.serial and self.serial.is_open:
            self.serial.close()
        if self.ntp_socket:
            self.ntp_socket.close()
        logger.info("GPS NTP server stopped")

@app.route('/')
def index():
    """Serve basic status page"""
    return Response(
        "GPS NTP Server Running\nAccess /stats for detailed statistics",
        mimetype='text/plain'
    )

if __name__ == '__main__':
    server = GPSNTP()
    try:
        server.start()
        app.run(host='0.0.0.0', port=5000, debug=False)
    except KeyboardInterrupt:
        logger.info("Shutting down server...")
        server.stop()
    except Exception as e:
        logger.error(f"Server error: {e}")
        server.stop()
