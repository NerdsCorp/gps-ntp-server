#!/usr/bin/env python3
"""
Adafruit Ultimate GPS NTP Server
Specifically configured for Adafruit Ultimate GPS with USB
"""

import socket
import struct
import time
import threading
import serial
import pynmea2
import logging
from datetime import datetime, timezone, timedelta
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
    from ntp_statistics_fixed import ntp_stats_bp, init_ntp_monitor
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

class AdafruitGPSNTP:
    """NTP Server for Adafruit Ultimate GPS"""
    
    # PMTK commands for Adafruit Ultimate GPS
    PMTK_SET_NMEA_UPDATE_1HZ = b'$PMTK220,1000*1F\r\n'
    PMTK_SET_NMEA_UPDATE_5HZ = b'$PMTK220,200*2C\r\n'
    PMTK_SET_NMEA_UPDATE_10HZ = b'$PMTK220,100*2F\r\n'
    
    # Enable RMC and GGA only (for NTP we need both)
    PMTK_SET_NMEA_OUTPUT_RMCGGA = b'$PMTK314,0,1,0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0*28\r\n'
    
    # Request firmware version
    PMTK_Q_RELEASE = b'$PMTK605*31\r\n'
    
    def __init__(self, serial_port='/dev/ttyUSB0', baudrate=9600, ntp_port=1123):
        self.serial_port = serial_port
        self.baudrate = baudrate
        self.ntp_port = ntp_port
        self.running = False
        self.gps_time = None
        self.gps_lock = threading.Lock()
        self.serial = None
        self.ntp_socket = None
        self.last_gps_update = None
        self.gps_fix_quality = 0
        self.satellites = 0
        self.firmware_version = "Unknown"
        
        # Statistics
        self.stats = {
            'nmea_total': 0,
            'rmc_count': 0,
            'gga_count': 0,
            'rmc_valid': 0,
            'gga_valid': 0,
            'ntp_requests': 0,
            'ntp_responses': 0
        }
        
    def configure_gps(self):
        """Configure Adafruit Ultimate GPS for optimal NTP operation"""
        if not self.serial or not self.serial.is_open:
            logger.error("Serial port not open for GPS configuration")
            return False
            
        try:
            logger.info("Configuring Adafruit Ultimate GPS...")
            
            # Clear any pending data
            self.serial.reset_input_buffer()
            self.serial.reset_output_buffer()
            
            # Request firmware version
            self.serial.write(self.PMTK_Q_RELEASE)
            time.sleep(0.1)
            
            # Set update rate to 1Hz (good for NTP, saves power)
            logger.info("Setting update rate to 1Hz...")
            self.serial.write(self.PMTK_SET_NMEA_UPDATE_1HZ)
            time.sleep(0.1)
            
            # Enable only RMC and GGA messages (all we need for NTP)
            logger.info("Configuring NMEA output for RMC and GGA only...")
            self.serial.write(self.PMTK_SET_NMEA_OUTPUT_RMCGGA)
            time.sleep(0.1)
            
            # Read response
            start_time = time.time()
            while time.time() - start_time < 2:
                line = self.serial.readline().decode('ascii', errors='ignore').strip()
                if line.startswith('$PMTK'):
                    logger.info(f"GPS Response: {line}")
                    if 'PMTK705' in line:  # Firmware version response
                        parts = line.split(',')
                        if len(parts) > 1:
                            self.firmware_version = parts[1].split('*')[0]
                            logger.info(f"Firmware version: {self.firmware_version}")
            
            logger.info("✅ Adafruit GPS configuration complete")
            return True
            
        except Exception as e:
            logger.error(f"Failed to configure GPS: {e}")
            return False
    
    def read_gps(self):
        """Read GPS data from Adafruit Ultimate GPS"""
        retry_count = 0
        max_retries = 3
        
        while self.running:
            try:
                if not self.serial or not self.serial.is_open:
                    logger.info(f"Opening Adafruit GPS on {self.serial_port} at {self.baudrate} baud...")
                    self.serial = serial.Serial(self.serial_port, self.baudrate, timeout=1)
                    logger.info("✅ Serial port opened")
                    
                    # Configure the GPS module
                    if not self.configure_gps():
                        logger.warning("GPS configuration failed, continuing anyway...")
                    
                    retry_count = 0  # Reset retry count on successful connection
                
                line = self.serial.readline().decode('ascii', errors='ignore').strip()
                if not line:
                    continue
                    
                # Only process NMEA sentences
                if not line.startswith('$'):
                    continue
                
                self.stats['nmea_total'] += 1
                
                # Log first few sentences for debugging
                if self.stats['nmea_total'] <= 5:
                    logger.debug(f"NMEA: {line}")
                
                try:
                    msg = pynmea2.parse(line)
                    
                    # Process RMC (Recommended Minimum) - has date and time
                    if isinstance(msg, pynmea2.types.talker.RMC):
                        self.stats['rmc_count'] += 1
                        
                        # Check if data is valid (A = active/valid, V = void/invalid)
                        if msg.status == 'A':
                            self.stats['rmc_valid'] += 1
                            
                            if msg.datetime:
                                with self.gps_lock:
                                    old_time = self.gps_time
                                    self.gps_time = msg.datetime.replace(tzinfo=timezone.utc)
                                    self.last_gps_update = time.time()
                                    
                                    # Log when time changes
                                    if old_time != self.gps_time:
                                        logger.info(f"✅ GPS time updated: {self.gps_time.isoformat()}")
                                        logger.info(f"   Status: Active | Speed: {msg.spd_over_grnd:.1f} knots" if msg.spd_over_grnd else "   Status: Active")
                        else:
                            # GPS doesn't have a fix yet
                            if self.stats['rmc_count'] % 10 == 0:  # Log every 10th invalid RMC
                                logger.warning(f"⚠️  GPS waiting for fix (RMC status = Void)")
                    
                    # Process GGA (Global Positioning System Fix Data) - has fix quality
                    elif isinstance(msg, pynmea2.types.talker.GGA):
                        self.stats['gga_count'] += 1
                        
                        # Update fix quality and satellite count
                        self.gps_fix_quality = msg.gps_qual
                        self.satellites = msg.num_sats if msg.num_sats else 0
                        
                        if msg.gps_qual > 0:  # Has fix
                            self.stats['gga_valid'] += 1
                            
                            # Log fix quality changes
                            if self.stats['gga_valid'] == 1 or self.stats['gga_valid'] % 30 == 0:
                                fix_types = {
                                    0: "No fix",
                                    1: "GPS fix",
                                    2: "DGPS fix",
                                    3: "PPS fix",
                                    4: "RTK fixed",
                                    5: "RTK float",
                                    6: "Estimated",
                                    7: "Manual",
                                    8: "Simulation"
                                }
                                logger.info(f"📡 GPS Fix: {fix_types.get(msg.gps_qual, 'Unknown')} | Satellites: {self.satellites} | HDOP: {msg.horizontal_dil}")
                                
                                if msg.latitude and msg.longitude:
                                    logger.info(f"   Position: {msg.latitude:.6f}°{msg.lat_dir}, {msg.longitude:.6f}°{msg.lon_dir}")
                        else:
                            # No fix yet
                            if self.stats['gga_count'] % 10 == 0:  # Log every 10th no-fix GGA
                                logger.debug(f"Waiting for GPS fix... (satellites visible: {self.satellites})")
                    
                    # Handle PMTK responses (Adafruit GPS commands)
                    elif line.startswith('$PMTK'):
                        logger.debug(f"GPS Command Response: {line}")
                        
                except pynmea2.ParseError as e:
                    # Some parse errors are normal, especially during startup
                    if self.stats['nmea_total'] % 100 == 0:
                        logger.debug(f"Parse error (normal during startup): {e}")
                
                # Print status every 30 seconds
                if self.stats['nmea_total'] % 30 == 0 and self.stats['nmea_total'] > 0:
                    self.print_status()
                    
            except serial.SerialException as e:
                retry_count += 1
                logger.error(f"❌ Serial port error (attempt {retry_count}/{max_retries}): {e}")
                
                if self.serial and self.serial.is_open:
                    self.serial.close()
                self.serial = None
                
                if retry_count >= max_retries:
                    logger.error("Max retries reached. Please check:")
                    logger.error("1. Is the GPS plugged in?")
                    logger.error("2. Correct port? Try: ls /dev/tty* | grep -E '(USB|ACM)'")
                    logger.error("3. Permissions? Try: sudo chmod 666 /dev/ttyUSB0")
                    retry_count = 0  # Reset for next attempt
                
                time.sleep(5)  # Wait before retry
                
            except Exception as e:
                logger.error(f"Unexpected error reading GPS: {e}")
                time.sleep(1)
        
        # Cleanup
        if self.serial and self.serial.is_open:
            self.serial.close()
            logger.info("Serial port closed")
    
    def ntp_response(self, data, client_addr):
        """Generate NTP response packet"""
        try:
            receive_timestamp = time.time()
            
            with self.gps_lock:
                if not self.gps_time:
                    logger.warning(f"No GPS time available for {client_addr}")
                    return None
                    
                # Check if GPS time is stale
                if self.last_gps_update and (time.time() - self.last_gps_update) > 10:
                    logger.warning(f"GPS time is stale ({time.time() - self.last_gps_update:.1f}s old)")
                    return None
                
                # Calculate current GPS time with offset
                time_since_update = time.time() - self.last_gps_update if self.last_gps_update else 0
                current_gps_time = self.gps_time + timedelta(seconds=time_since_update)
                
            if len(data) < 48:
                logger.warning(f"Invalid NTP packet size: {len(data)}")
                return None
                
            # Unpack client request
            unpacked = struct.unpack('!B B B b 11I', data[:48])
            client_transmit_int = unpacked[10]
            client_transmit_frac = unpacked[11]
            
            # NTP epoch starts at 1900-01-01
            ntp_epoch = datetime(1900, 1, 1, tzinfo=timezone.utc)
            unix_epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
            
            # Convert GPS time to NTP timestamp
            gps_ntp_timestamp = (current_gps_time - ntp_epoch).total_seconds()
            
            # Convert Unix timestamps to NTP
            ntp_unix_offset = (unix_epoch - ntp_epoch).total_seconds()
            receive_ntp_timestamp = receive_timestamp + ntp_unix_offset
            transmit_timestamp = time.time()
            transmit_ntp_timestamp = transmit_timestamp + ntp_unix_offset
            
            # Build response packet
            response = bytearray(48)
            
            # Header
            response[0] = 0x24  # LI=0, VN=4, Mode=4 (server)
            response[1] = 1     # Stratum 1 (GPS)
            response[2] = 6     # Poll interval
            response[3] = 0xEC  # Precision (~1 microsecond)
            
            # Root delay and dispersion (0 for stratum 1)
            struct.pack_into('!I', response, 4, 0)
            struct.pack_into('!I', response, 8, 0)
            
            # Reference ID: 'GPS ' for GPS time source
            response[12:16] = b'GPS '
            
            # Reference timestamp (last GPS update)
            struct.pack_into('!I', response, 16, int(gps_ntp_timestamp))
            struct.pack_into('!I', response, 20, int((gps_ntp_timestamp % 1) * 2**32))
            
            # Originate timestamp (copy from client)
            struct.pack_into('!I', response, 24, client_transmit_int)
            struct.pack_into('!I', response, 28, client_transmit_frac)
            
            # Receive timestamp
            struct.pack_into('!I', response, 32, int(receive_ntp_timestamp))
            struct.pack_into('!I', response, 36, int((receive_ntp_timestamp % 1) * 2**32))
            
            # Transmit timestamp
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
                    self.ntp_socket.settimeout(1.0)
                    self.ntp_socket.bind(('', self.ntp_port))
                    logger.info(f"✅ NTP server listening on UDP port {self.ntp_port}")
                
                try:
                    data, client_addr = self.ntp_socket.recvfrom(1024)
                    self.stats['ntp_requests'] += 1
                    logger.debug(f"NTP request from {client_addr}")
                    
                    response = self.ntp_response(data, client_addr)
                    if response:
                        self.ntp_socket.sendto(response, client_addr)
                        self.stats['ntp_responses'] += 1
                        logger.debug(f"Sent NTP response to {client_addr}")
                    else:
                        logger.debug(f"No response sent to {client_addr} (no valid GPS time)")
                        
                except socket.timeout:
                    continue
                    
            except OSError as e:
                if e.errno == 13:
                    logger.error(f"Permission denied on port {self.ntp_port}. Try port 1123 or run with sudo")
                    break
                elif e.errno == 98:
                    logger.error(f"Port {self.ntp_port} already in use")
                    break
                else:
                    logger.error(f"Socket error: {e}")
                    time.sleep(5)
                    
            except Exception as e:
                logger.error(f"NTP server error: {e}")
                time.sleep(1)
        
        if self.ntp_socket:
            self.ntp_socket.close()
            self.ntp_socket = None
            logger.info("NTP socket closed")
    
    def print_status(self):
        """Print current status"""
        with self.gps_lock:
            if self.gps_time:
                time_str = self.gps_time.isoformat()
                age = time.time() - self.last_gps_update if self.last_gps_update else 0
                time_status = f"{time_str} (age: {age:.1f}s)"
            else:
                time_status = "No GPS time yet"
        
        fix_types = {0: "No fix", 1: "GPS", 2: "DGPS", 3: "PPS", 4: "RTK", 5: "RTK float"}
        fix_status = fix_types.get(self.gps_fix_quality, "Unknown")
        
        logger.info(f"""
========================================
Adafruit Ultimate GPS Status:
  Firmware: {self.firmware_version}
  GPS Time: {time_status}
  Fix Type: {fix_status}
  Satellites: {self.satellites}
  
  NMEA Messages:
    Total: {self.stats['nmea_total']}
    RMC: {self.stats['rmc_count']} (valid: {self.stats['rmc_valid']})
    GGA: {self.stats['gga_count']} (valid: {self.stats['gga_valid']})
  
  NTP Server:
    Requests: {self.stats['ntp_requests']}
    Responses: {self.stats['ntp_responses']}
========================================
        """)
    
    def start(self):
        """Start GPS and NTP services"""
        self.running = True
        
        logger.info("Starting Adafruit Ultimate GPS NTP Server...")
        logger.info(f"  GPS Port: {self.serial_port} @ {self.baudrate} baud")
        logger.info(f"  NTP Port: {self.ntp_port}")
        
        # Start GPS reader thread
        gps_thread = threading.Thread(target=self.read_gps, daemon=True)
        gps_thread.start()
        
        # Give GPS a moment to initialize
        time.sleep(2)
        
        # Start NTP server thread
        ntp_thread = threading.Thread(target=self.ntp_server, daemon=True)
        ntp_thread.start()
        
        # Initialize NTP monitor if available
        if init_ntp_monitor:
            try:
                init_ntp_monitor([
                    {'address': 'localhost', 'port': self.ntp_port, 'name': 'Adafruit GPS NTP'}
                ])
                logger.info("NTP monitor initialized")
            except Exception as e:
                logger.error(f"Failed to initialize NTP monitor: {e}")
        
        logger.info("✅ Server started successfully")
    
    def stop(self):
        """Stop GPS and NTP services"""
        logger.info("Stopping server...")
        self.running = False
        
        time.sleep(2)
        
        if self.serial and self.serial.is_open:
            self.serial.close()
        if self.ntp_socket:
            self.ntp_socket.close()
            
        logger.info("Server stopped")
    
    def get_status(self):
        """Get current server status"""
        with self.gps_lock:
            return {
                'running': self.running,
                'gps_time': self.gps_time.isoformat() if self.gps_time else None,
                'gps_fix_quality': self.gps_fix_quality,
                'satellites': self.satellites,
                'firmware': self.firmware_version,
                'last_update': self.last_gps_update,
                'time_since_update': time.time() - self.last_gps_update if self.last_gps_update else None,
                'stats': self.stats
            }

@app.route('/')
def index():
    """Serve status page"""
    if 'server' in globals():
        status = server.get_status()
        return Response(
            f"Adafruit Ultimate GPS NTP Server\n"
            f"=====================================\n"
            f"Firmware: {status['firmware']}\n"
            f"Running: {status['running']}\n"
            f"GPS Time: {status['gps_time']}\n"
            f"Fix Quality: {status['gps_fix_quality']}\n"
            f"Satellites: {status['satellites']}\n"
            f"Time Since Update: {status['time_since_update']:.1f}s\n"
            f"\nStatistics:\n"
            f"  RMC Messages: {status['stats']['rmc_count']} (valid: {status['stats']['rmc_valid']})\n"
            f"  GGA Messages: {status['stats']['gga_count']} (valid: {status['stats']['gga_valid']})\n"
            f"  NTP Requests: {status['stats']['ntp_requests']}\n"
            f"  NTP Responses: {status['stats']['ntp_responses']}\n"
            f"\nAccess /stats for detailed statistics dashboard",
            mimetype='text/plain'
        )
    return Response("Adafruit GPS NTP Server\nAccess /stats for statistics", mimetype='text/plain')

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Adafruit Ultimate GPS NTP Server')
    parser.add_argument('--serial', default='/dev/ttyUSB0', 
                       help='GPS serial port (default: /dev/ttyUSB0)')
    parser.add_argument('--baudrate', type=int, default=9600,
                       help='GPS baud rate (default: 9600 for Adafruit)')
    parser.add_argument('--ntp-port', type=int, default=1123,
                       help='NTP server port (default: 1123)')
    parser.add_argument('--web-port', type=int, default=5000,
                       help='Web interface port (default: 5000)')
    
    args = parser.parse_args()
    
    # Create and start server
    server = AdafruitGPSNTP(
        serial_port=args.serial,
        baudrate=args.baudrate,
        ntp_port=args.ntp_port
    )
    
    try:
        server.start()
        logger.info(f"Web interface starting on port {args.web_port}")
        logger.info(f"View status at: http://localhost:{args.web_port}/")
        logger.info(f"Statistics at: http://localhost:{args.web_port}/stats/")
        app.run(host='0.0.0.0', port=args.web_port, debug=False)
    except KeyboardInterrupt:
        logger.info("\nShutting down...")
    except Exception as e:
        logger.error(f"Server error: {e}")
    finally:
        server.stop()
