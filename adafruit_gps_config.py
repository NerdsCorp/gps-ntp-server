#!/usr/bin/env python3
"""
Adafruit Ultimate GPS Configuration Tool
Configure and test the Adafruit Ultimate GPS module
"""

import serial
import time
import sys
import argparse

class AdafruitGPSConfig:
    """Configuration tool for Adafruit Ultimate GPS"""
    
    # PMTK command set for MTK3339 chipset (used in Adafruit Ultimate GPS)
    COMMANDS = {
        # Update rates
        'RATE_10HZ': b'$PMTK220,100*2F\r\n',      # 10 Hz (100ms)
        'RATE_5HZ': b'$PMTK220,200*2C\r\n',       # 5 Hz (200ms)
        'RATE_1HZ': b'$PMTK220,1000*1F\r\n',      # 1 Hz (1000ms)
        
        # Baud rates
        'BAUD_115200': b'$PMTK251,115200*1F\r\n',
        'BAUD_57600': b'$PMTK251,57600*2C\r\n',
        'BAUD_9600': b'$PMTK251,9600*17\r\n',
        
        # NMEA sentence output configuration
        # Format: GLL,RMC,VTG,GGA,GSA,GSV,0,0,0,0,0,0,0,0,0,0,0,0,0
        'OUTPUT_RMC_GGA': b'$PMTK314,0,1,0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0*28\r\n',  # RMC + GGA only
        'OUTPUT_ALL': b'$PMTK314,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0*28\r\n',      # All NMEA
        'OUTPUT_RMC_ONLY': b'$PMTK314,0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0*29\r\n', # RMC only
        
        # Fix interval
        'FIX_CTL_1S': b'$PMTK300,1000,0,0,0,0*1C\r\n',   # 1 second fix interval
        'FIX_CTL_5S': b'$PMTK300,5000,0,0,0,0*18\r\n',   # 5 second fix interval
        
        # Antenna status
        'ANTENNA_STATUS': b'$PGCMD,33,1*6C\r\n',          # Report antenna status
        'ANTENNA_OFF': b'$PGCMD,33,0*6D\r\n',             # Stop antenna status
        
        # System commands
        'TEST': b'$PMTK000*32\r\n',                       # Test command
        'VERSION': b'$PMTK605*31\r\n',                    # Get firmware version
        'HOT_START': b'$PMTK101*32\r\n',                  # Hot start (use backup data)
        'WARM_START': b'$PMTK102*31\r\n',                 # Warm start  
        'COLD_START': b'$PMTK103*30\r\n',                 # Cold start (clear all data)
        'FULL_COLD_START': b'$PMTK104*37\r\n',            # Full cold start (factory reset)
        
        # Enable SBAS (WAAS/EGNOS/MSAS)
        'SBAS_ENABLE': b'$PMTK313,1*2E\r\n',
        'SBAS_DISABLE': b'$PMTK313,0*2F\r\n',
        
        # Enable EASY (self-assisted GPS)
        'EASY_ENABLE': b'$PMTK869,1,1*35\r\n',
        'EASY_DISABLE': b'$PMTK869,1,0*34\r\n',
    }
    
    def __init__(self, port='/dev/ttyUSB0', baudrate=9600):
        self.port = port
        self.baudrate = baudrate
        self.serial = None
        
    def connect(self):
        """Connect to GPS module"""
        try:
            print(f"Connecting to {self.port} at {self.baudrate} baud...")
            self.serial = serial.Serial(self.port, self.baudrate, timeout=1)
            time.sleep(0.5)  # Give it time to initialize
            self.serial.reset_input_buffer()
            print("✅ Connected successfully")
            return True
        except Exception as e:
            print(f"❌ Failed to connect: {e}")
            return False
    
    def send_command(self, command, wait_response=True):
        """Send a command to the GPS"""
        if not self.serial:
            print("Not connected!")
            return False
            
        try:
            print(f"Sending: {command.decode('ascii').strip()}")
            self.serial.write(command)
            
            if wait_response:
                time.sleep(0.5)
                responses = []
                start_time = time.time()
                
                while time.time() - start_time < 2:
                    line = self.serial.readline().decode('ascii', errors='ignore').strip()
                    if line:
                        responses.append(line)
                        if line.startswith('$PMTK'):
                            print(f"  Response: {line}")
                
                return responses
            return True
            
        except Exception as e:
            print(f"❌ Error sending command: {e}")
            return False
    
    def configure_for_ntp(self):
        """Configure GPS optimally for NTP server use"""
        print("\n" + "="*60)
        print("Configuring Adafruit Ultimate GPS for NTP Server")
        print("="*60)
        
        if not self.connect():
            return False
        
        print("\n1. Testing connection...")
        self.send_command(self.COMMANDS['TEST'])
        
        print("\n2. Getting firmware version...")
        self.send_command(self.COMMANDS['VERSION'])
        
        print("\n3. Setting update rate to 1Hz (optimal for NTP)...")
        self.send_command(self.COMMANDS['RATE_1HZ'])
        
        print("\n4. Configuring NMEA output (RMC + GGA only)...")
        self.send_command(self.COMMANDS['OUTPUT_RMC_GGA'])
        
        print("\n5. Enabling SBAS for better accuracy...")
        self.send_command(self.COMMANDS['SBAS_ENABLE'])
        
        print("\n✅ Configuration complete!")
        print("\nYour GPS is now configured for NTP server use.")
        print("Settings:")
        print("  - Update rate: 1 Hz")
        print("  - NMEA output: RMC + GGA only")
        print("  - SBAS: Enabled")
        
        return True
    
    def monitor(self, duration=30):
        """Monitor GPS output"""
        print(f"\nMonitoring GPS output for {duration} seconds...")
        print("-"*60)
        
        if not self.serial:
            if not self.connect():
                return
        
        start_time = time.time()
        msg_count = {'RMC': 0, 'GGA': 0, 'GSV': 0, 'GSA': 0, 'OTHER': 0}
        has_fix = False
        satellites = 0
        
        while time.time() - start_time < duration:
            try:
                line = self.serial.readline().decode('ascii', errors='ignore').strip()
                if line:
                    # Count message types
                    if '$GPRMC' in line or '$GNRMC' in line:
                        msg_count['RMC'] += 1
                        if ',A,' in line:
                            has_fix = True
                    elif '$GPGGA' in line or '$GNGGA' in line:
                        msg_count['GGA'] += 1
                        parts = line.split(',')
                        if len(parts) > 7:
                            try:
                                sats = int(parts[7])
                                if sats > satellites:
                                    satellites = sats
                            except:
                                pass
                    elif '$GPGSV' in line or '$GNGSV' in line:
                        msg_count['GSV'] += 1
                    elif '$GPGSA' in line or '$GNGSA' in line:
                        msg_count['GSA'] += 1
                    else:
                        msg_count['OTHER'] += 1
                    
                    # Display sample messages
                    if msg_count['RMC'] == 1 and 'RMC' in line:
                        print(f"Sample RMC: {line[:80]}...")
                    elif msg_count['GGA'] == 1 and 'GGA' in line:
                        print(f"Sample GGA: {line[:80]}...")
                        
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"Error: {e}")
        
        print("-"*60)
        print("Summary:")
        print(f"  RMC messages: {msg_count['RMC']} (Required for date/time)")
        print(f"  GGA messages: {msg_count['GGA']} (Required for fix quality)")
        print(f"  GSV messages: {msg_count['GSV']} (Satellites in view)")
        print(f"  GSA messages: {msg_count['GSA']} (DOP values)")
        print(f"  Other: {msg_count['OTHER']}")
        print(f"\n  GPS Fix: {'✅ Yes' if has_fix else '❌ No'}")
        print(f"  Max Satellites: {satellites}")
        
        if msg_count['RMC'] == 0:
            print("\n⚠️  WARNING: No RMC messages! NTP server needs RMC for date.")
        if msg_count['GGA'] == 0:
            print("⚠️  WARNING: No GGA messages! NTP server needs GGA for quality.")
    
    def factory_reset(self):
        """Factory reset the GPS module"""
        print("\n⚠️  WARNING: This will factory reset the GPS module!")
        response = input("Are you sure? (yes/no): ")
        
        if response.lower() != 'yes':
            print("Cancelled")
            return
        
        if not self.serial:
            if not self.connect():
                return
        
        print("\nPerforming factory reset...")
        self.send_command(self.COMMANDS['FULL_COLD_START'])
        print("✅ Factory reset complete")
        print("Note: The GPS will take longer to get a fix after a cold start")
    
    def interactive_menu(self):
        """Interactive configuration menu"""
        if not self.connect():
            return
        
        while True:
            print("\n" + "="*60)
            print("Adafruit Ultimate GPS Configuration")
            print("="*60)
            print("1. Configure for NTP Server (recommended)")
            print("2. Monitor GPS output")
            print("3. Set update rate")
            print("4. Configure NMEA sentences")
            print("5. Get firmware version")
            print("6. Restart GPS (hot/warm/cold)")
            print("7. Factory reset")
            print("8. Exit")
            
            choice = input("\nSelect option (1-8): ")
            
            if choice == '1':
                self.configure_for_ntp()
            elif choice == '2':
                self.monitor()
            elif choice == '3':
                print("\nSelect update rate:")
                print("1. 1 Hz (recommended for NTP)")
                print("2. 5 Hz")
                print("3. 10 Hz")
                rate = input("Choice (1-3): ")
                if rate == '1':
                    self.send_command(self.COMMANDS['RATE_1HZ'])
                elif rate == '2':
                    self.send_command(self.COMMANDS['RATE_5HZ'])
                elif rate == '3':
                    self.send_command(self.COMMANDS['RATE_10HZ'])
            elif choice == '4':
                print("\nSelect NMEA output:")
                print("1. RMC + GGA only (recommended for NTP)")
                print("2. RMC only")
                print("3. All NMEA sentences")
                output = input("Choice (1-3): ")
                if output == '1':
                    self.send_command(self.COMMANDS['OUTPUT_RMC_GGA'])
                elif output == '2':
                    self.send_command(self.COMMANDS['OUTPUT_RMC_ONLY'])
                elif output == '3':
                    self.send_command(self.COMMANDS['OUTPUT_ALL'])
            elif choice == '5':
                self.send_command(self.COMMANDS['VERSION'])
            elif choice == '6':
                print("\nSelect restart type:")
                print("1. Hot start (use all backup data)")
                print("2. Warm start (use some backup)")
                print("3. Cold start (clear all data)")
                restart = input("Choice (1-3): ")
                if restart == '1':
                    self.send_command(self.COMMANDS['HOT_START'])
                elif restart == '2':
                    self.send_command(self.COMMANDS['WARM_START'])
                elif restart == '3':
                    self.send_command(self.COMMANDS['COLD_START'])
            elif choice == '7':
                self.factory_reset()
            elif choice == '8':
                break
            else:
                print("Invalid choice")
        
        if self.serial:
            self.serial.close()

def main():
    parser = argparse.ArgumentParser(description='Adafruit Ultimate GPS Configuration Tool')
    parser.add_argument('--port', default='/dev/ttyUSB0',
                       help='Serial port (default: /dev/ttyUSB0)')
    parser.add_argument('--baudrate', type=int, default=9600,
                       help='Baud rate (default: 9600)')
    parser.add_argument('--configure-ntp', action='store_true',
                       help='Configure GPS for NTP server use')
    parser.add_argument('--monitor', type=int, metavar='SECONDS',
                       help='Monitor GPS output for N seconds')
    parser.add_argument('--reset', action='store_true',
                       help='Factory reset GPS module')
    
    args = parser.parse_args()
    
    gps = AdafruitGPSConfig(args.port, args.baudrate)
    
    if args.configure_ntp:
        gps.configure_for_ntp()
    elif args.monitor:
        gps.monitor(args.monitor)
    elif args.reset:
        gps.factory_reset()
    else:
        gps.interactive_menu()

if __name__ == '__main__':
    main()
