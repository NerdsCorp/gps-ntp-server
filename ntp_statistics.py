#!/usr/bin/env python3
"""
NTP Statistics and Comparison Module
Monitors and compares multiple NTP servers including GPS-based server
"""

import socket
import struct
import time
import threading
import json
import statistics
import logging
import sqlite3
import os
from datetime import datetime, timezone, timedelta
from collections import deque, defaultdict
import numpy as np
from flask import Blueprint, render_template_string, jsonify, request, redirect, url_for, Response

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class NTPDatabase:
    """SQLite database for NTP statistics with 1-week retention"""

    def __init__(self, db_path='ntp_stats.db'):
        """Initialize database and create schema"""
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self._init_schema()
        logger.info(f"NTP Database initialized at {db_path}")

    def _init_schema(self):
        """Create database schema"""
        with self.lock:
            cursor = self.conn.cursor()

            # Servers table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS servers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    address TEXT NOT NULL,
                    port INTEGER NOT NULL,
                    name TEXT,
                    enabled INTEGER DEFAULT 1,
                    UNIQUE(address, port)
                )
            ''')

            # History table for time-series data
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id INTEGER NOT NULL,
                    timestamp REAL NOT NULL,
                    reachable INTEGER NOT NULL,
                    stratum INTEGER,
                    rtt REAL,
                    offset REAL,
                    precision REAL,
                    reference_id TEXT,
                    data_json TEXT,
                    FOREIGN KEY (server_id) REFERENCES servers (id) ON DELETE CASCADE
                )
            ''')

            # Create index on timestamp for fast queries
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_history_timestamp
                ON history(timestamp)
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_history_server_timestamp
                ON history(server_id, timestamp)
            ''')

            # Metrics table for aggregated statistics
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS metrics (
                    server_id INTEGER PRIMARY KEY,
                    min_rtt REAL,
                    max_rtt REAL,
                    total_queries INTEGER DEFAULT 0,
                    successful_queries INTEGER DEFAULT 0,
                    failed_queries INTEGER DEFAULT 0,
                    total_offset REAL DEFAULT 0,
                    offset_squares REAL DEFAULT 0,
                    last_success TEXT,
                    last_failure TEXT,
                    availability REAL DEFAULT 100.0,
                    quality_score REAL DEFAULT 0,
                    FOREIGN KEY (server_id) REFERENCES servers (id) ON DELETE CASCADE
                )
            ''')

            self.conn.commit()

    def add_server(self, address, port=123, name=None):
        """Add or update a server"""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO servers (address, port, name)
                VALUES (?, ?, ?)
            ''', (address, port, name or address))

            if cursor.lastrowid == 0:
                # Server already exists, update name if provided
                cursor.execute('''
                    UPDATE servers SET name = ?
                    WHERE address = ? AND port = ?
                ''', (name or address, address, port))

            self.conn.commit()
            return self.get_server_id(address, port)

    def get_server_id(self, address, port=123):
        """Get server ID by address and port"""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT id FROM servers WHERE address = ? AND port = ?
            ''', (address, port))
            row = cursor.fetchone()
            return row[0] if row else None

    def get_all_servers(self):
        """Get all servers"""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM servers WHERE enabled = 1')
            return [dict(row) for row in cursor.fetchall()]

    def remove_server(self, address):
        """Remove a server (cascades to history and metrics)"""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute('DELETE FROM servers WHERE address = ?', (address,))
            self.conn.commit()

    def add_history(self, server_id, result):
        """Add a history record"""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO history
                (server_id, timestamp, reachable, stratum, rtt, offset, precision, reference_id, data_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                server_id,
                time.time(),
                1 if result.get('reachable') else 0,
                result.get('stratum'),
                result.get('rtt'),
                result.get('offset'),
                result.get('precision'),
                result.get('reference_id'),
                json.dumps(result)
            ))
            self.conn.commit()

    def get_history(self, server_id, limit=None, since=None):
        """Get history for a server"""
        with self.lock:
            cursor = self.conn.cursor()

            if since:
                query = '''
                    SELECT * FROM history
                    WHERE server_id = ? AND timestamp >= ?
                    ORDER BY timestamp DESC
                '''
                params = (server_id, since)
            else:
                query = '''
                    SELECT * FROM history
                    WHERE server_id = ?
                    ORDER BY timestamp DESC
                '''
                params = (server_id,)

            if limit:
                query += f' LIMIT {limit}'

            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def update_metrics(self, server_id, metrics):
        """Update or insert metrics for a server"""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO metrics
                (server_id, min_rtt, max_rtt, total_queries, successful_queries,
                 failed_queries, total_offset, offset_squares, last_success,
                 last_failure, availability, quality_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                server_id,
                metrics.get('min_rtt', float('inf')),
                metrics.get('max_rtt', 0),
                metrics.get('total_queries', 0),
                metrics.get('successful_queries', 0),
                metrics.get('failed_queries', 0),
                metrics.get('total_offset', 0),
                metrics.get('offset_squares', 0),
                metrics.get('last_success'),
                metrics.get('last_failure'),
                metrics.get('availability', 100.0),
                metrics.get('quality_score', 0)
            ))
            self.conn.commit()

    def get_metrics(self, server_id):
        """Get metrics for a server"""
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM metrics WHERE server_id = ?', (server_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def cleanup_old_data(self, days=7):
        """Remove data older than specified days"""
        cutoff = time.time() - (days * 86400)
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute('DELETE FROM history WHERE timestamp < ?', (cutoff,))
            deleted = cursor.rowcount
            self.conn.commit()
            if deleted > 0:
                logger.info(f"Cleaned up {deleted} old history records (older than {days} days)")

    def close(self):
        """Close database connection"""
        with self.lock:
            self.conn.close()

# Create Flask blueprint
ntp_stats_bp = Blueprint('ntp_stats', __name__)

# Global NTP monitor instance
ntp_monitor = None
_monitor_lock = threading.Lock()

def init_ntp_monitor(servers=None):
    """Initialize the global NTP monitor"""
    global ntp_monitor
    if not ntp_monitor:
        ntp_monitor = NTPMonitor(servers=servers)
        ntp_monitor.start()
        logger.info(f"NTP Monitor initialized with {len(servers) if servers else 0} servers")
    return ntp_monitor

def get_ntp_monitor():
    """Get or lazily initialize the NTP monitor

    This function ensures the NTP monitor is initialized on first use,
    allowing the web server to start without blocking on NTP availability.
    Thread-safe lazy initialization.
    """
    global ntp_monitor
    if ntp_monitor is None:
        with _monitor_lock:
            # Double-check pattern to avoid race conditions
            if ntp_monitor is None:
                logger.info("Lazy initializing NTP monitor with empty server list")
                init_ntp_monitor([])  # Initialize with empty list
    return ntp_monitor

class NTPClient:
    """NTP Client for querying NTP servers"""
    
    def __init__(self, timeout=1.0):
        self.timeout = timeout
        
    def query_server(self, server, port=123):
        """Query an NTP server and return statistics"""
        try:
            # Create UDP socket with proper resource management
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.settimeout(self.timeout)

                # Create NTP request packet (48 bytes)
                packet = bytearray(48)
                packet[0] = 0x1B  # LI=0, VN=3, Mode=3 (client)

                # Record transmit time
                transmit_time = time.time()

                # Send request
                sock.sendto(packet, (server, port))

                # Receive response
                data, address = sock.recvfrom(1024)
                receive_time = time.time()

                # Calculate round-trip time
                rtt = (receive_time - transmit_time) * 1000  # Convert to ms

                # Check packet size
                if len(data) < 48:
                    raise ValueError(f"Invalid NTP response size: {len(data)}")

                # Unpack NTP response
                unpacked = struct.unpack('!B B B b 11I', data[:48])

                li_vn_mode = unpacked[0]
                stratum = unpacked[1]
                poll = unpacked[2]
                precision = unpacked[3]
                root_delay = unpacked[4] / 65536.0
                root_dispersion = unpacked[5] / 65536.0
                ref_id = unpacked[6]

                # Extract timestamps
                ref_timestamp_int = unpacked[7]
                ref_timestamp_frac = unpacked[8]
                ref_timestamp = ref_timestamp_int + (ref_timestamp_frac / 2**32)

                origin_timestamp_int = unpacked[9]
                origin_timestamp_frac = unpacked[10]

                recv_timestamp_int = unpacked[11]
                recv_timestamp_frac = unpacked[12]

                trans_timestamp_int = unpacked[13]
                trans_timestamp_frac = unpacked[14]

                # Convert to full timestamps
                origin_ntp = origin_timestamp_int + (origin_timestamp_frac / 2**32)
                recv_ntp = recv_timestamp_int + (recv_timestamp_frac / 2**32)
                trans_ntp = trans_timestamp_int + (trans_timestamp_frac / 2**32)

                # Calculate clock offset using NTP algorithm
                # T1 = origin (client transmit)
                # T2 = recv (server receive)
                # T3 = trans (server transmit)
                # T4 = receive_time (client receive)

                # Convert Unix timestamps to NTP for calculation
                ntp_epoch = datetime(1900, 1, 1, tzinfo=timezone.utc)
                unix_epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
                ntp_unix_offset = (unix_epoch - ntp_epoch).total_seconds()

                transmit_ntp = transmit_time + ntp_unix_offset
                receive_ntp = receive_time + ntp_unix_offset

                # Calculate offset: ((T2 - T1) + (T3 - T4)) / 2
                offset = ((recv_ntp - transmit_ntp) + (trans_ntp - receive_ntp)) / 2

                # Parse reference ID based on stratum
                if stratum == 0 or stratum == 1:
                    # Stratum 0/1: Reference ID is ASCII string
                    ref_id_str = struct.pack('!I', ref_id).decode('ascii', errors='ignore').strip('\x00')
                else:
                    # Stratum 2+: Reference ID is IP address
                    ref_id_str = socket.inet_ntoa(struct.pack('!I', ref_id))

                return {
                    'server': server,
                    'port': port,
                    'reachable': True,
                    'stratum': stratum,
                    'precision': 2 ** precision,
                    'root_delay': root_delay * 1000,  # Convert to ms
                    'root_dispersion': root_dispersion * 1000,  # Convert to ms
                    'reference_id': ref_id_str,
                    'reference_time': ref_timestamp,
                    'offset': offset * 1000,  # Convert to ms
                    'rtt': rtt,
                    'latency': rtt / 2,
                    'poll_interval': 2 ** poll,
                    'li': (li_vn_mode >> 6) & 0x3,
                    'version': (li_vn_mode >> 3) & 0x7,
                    'mode': li_vn_mode & 0x7,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }

        except socket.timeout:
            return {
                'server': server,
                'port': port,
                'reachable': False,
                'error': 'Timeout',
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
        except socket.gaierror as e:
            return {
                'server': server,
                'port': port,
                'reachable': False,
                'error': f'DNS resolution failed: {e}',
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
        except Exception as e:
            logger.error(f"Error querying {server}:{port}: {e}")
            return {
                'server': server,
                'port': port,
                'reachable': False,
                'error': str(e),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

class NTPMonitor:
    """Monitor multiple NTP servers and collect statistics"""

    def __init__(self, servers=None, history_size=3600, db_path='ntp_stats.db'):
        self.servers = servers or []
        self.history_size = history_size
        self.client = NTPClient()
        self.running = False
        self.thread = None
        self.current_stats = {}
        self.aggregated_stats = {}
        self.lock = threading.Lock()

        # Initialize database
        self.db = NTPDatabase(db_path)

        # Load servers from database if no servers provided
        if not self.servers:
            db_servers = self.db.get_all_servers()
            self.servers = [{
                'address': s['address'],
                'port': s['port'],
                'name': s['name'],
                'enabled': bool(s['enabled'])
            } for s in db_servers]
        else:
            # Add provided servers to database
            for server_config in self.servers:
                self.db.add_server(
                    server_config['address'],
                    server_config.get('port', 123),
                    server_config.get('name')
                )

        # In-memory cache for quick access (still needed for jitter/offset buffers)
        self.metrics = defaultdict(lambda: {
            'min_rtt': float('inf'),
            'max_rtt': 0,
            'total_queries': 0,
            'successful_queries': 0,
            'failed_queries': 0,
            'total_offset': 0,
            'offset_squares': 0,
            'last_success': None,
            'last_failure': None,
            'availability': 100.0,
            'jitter_buffer': deque(maxlen=10),
            'offset_buffer': deque(maxlen=60),
            'quality_score': 0
        })

        # Load metrics from database
        self._load_metrics_from_db()

        # Schedule cleanup thread
        self.cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)

    def _load_metrics_from_db(self):
        """Load metrics from database into memory"""
        for server_config in self.servers:
            server_id = self.db.get_server_id(server_config['address'], server_config.get('port', 123))
            if server_id:
                db_metrics = self.db.get_metrics(server_id)
                if db_metrics:
                    server = server_config['address']
                    self.metrics[server].update({
                        'min_rtt': db_metrics.get('min_rtt', float('inf')),
                        'max_rtt': db_metrics.get('max_rtt', 0),
                        'total_queries': db_metrics.get('total_queries', 0),
                        'successful_queries': db_metrics.get('successful_queries', 0),
                        'failed_queries': db_metrics.get('failed_queries', 0),
                        'total_offset': db_metrics.get('total_offset', 0),
                        'offset_squares': db_metrics.get('offset_squares', 0),
                        'last_success': db_metrics.get('last_success'),
                        'last_failure': db_metrics.get('last_failure'),
                        'availability': db_metrics.get('availability', 100.0),
                        'quality_score': db_metrics.get('quality_score', 0)
                    })

    def _cleanup_loop(self):
        """Periodic cleanup of old data"""
        while self.running:
            time.sleep(3600)  # Run every hour
            try:
                self.db.cleanup_old_data(days=7)
            except Exception as e:
                logger.error(f"Error during cleanup: {e}")

    def add_server(self, server, port=123, name=None):
        """Add an NTP server to monitor"""
        server_config = {
            'address': server,
            'port': port,
            'name': name or server,
            'enabled': True
        }
        with self.lock:
            # Check if server already exists
            for existing in self.servers:
                if existing['address'] == server and existing['port'] == port:
                    logger.info(f"Server {server}:{port} already exists")
                    return
            self.servers.append(server_config)
            # Add to database
            self.db.add_server(server, port, name)
            logger.info(f"Added NTP server: {server}:{port} ({name})")
    
    def remove_server(self, server):
        """Remove an NTP server from monitoring"""
        with self.lock:
            self.servers = [s for s in self.servers if s['address'] != server]
            # Remove from database (cascades to history and metrics)
            self.db.remove_server(server)
            # Also remove from in-memory metrics
            if server in self.metrics:
                del self.metrics[server]
    
    def query_all_servers(self):
        """Query all configured NTP servers"""
        results = {}

        with self.lock:
            servers = self.servers.copy()

        for server_config in servers:
            if not server_config.get('enabled', True):
                continue

            server = server_config['address']
            port = server_config.get('port', 123)
            name = server_config.get('name', server)

            result = self.client.query_server(server, port)
            result['name'] = name

            with self.lock:
                self.update_metrics(server, result)
                results[server] = result

                # Save to database
                server_id = self.db.get_server_id(server, port)
                if server_id:
                    self.db.add_history(server_id, result)
                    # Update metrics in database
                    self.db.update_metrics(server_id, self.metrics[server])

                self.current_stats = results

        # Calculate aggregated statistics
        with self.lock:
            self.calculate_aggregated_stats()

        return results
    
    def update_metrics(self, server, result):
        """Update performance metrics for a server"""
        metrics = self.metrics[server]
        
        metrics['total_queries'] += 1
        
        if result['reachable']:
            metrics['successful_queries'] += 1
            metrics['last_success'] = result['timestamp']
            
            # Update RTT statistics
            rtt = result['rtt']
            metrics['min_rtt'] = min(metrics['min_rtt'], rtt)
            metrics['max_rtt'] = max(metrics['max_rtt'], rtt)
            
            # Update offset statistics
            offset = result['offset']
            metrics['total_offset'] += offset
            metrics['offset_squares'] += offset ** 2
            metrics['offset_buffer'].append(offset)
            
            # Calculate jitter
            if len(metrics['jitter_buffer']) > 0:
                last_rtt = metrics['jitter_buffer'][-1]
                jitter = abs(rtt - last_rtt)
                result['jitter'] = jitter
            else:
                result['jitter'] = 0
            
            metrics['jitter_buffer'].append(rtt)
            
        else:
            metrics['failed_queries'] += 1
            metrics['last_failure'] = result['timestamp']
        
        # Calculate availability
        if metrics['total_queries'] > 0:
            metrics['availability'] = (metrics['successful_queries'] / metrics['total_queries']) * 100
        
        # Calculate quality score (0-100)
        self.calculate_quality_score(server)
    
    def calculate_quality_score(self, server):
        """Calculate quality score for a server"""
        metrics = self.metrics[server]
        
        if metrics['successful_queries'] == 0:
            metrics['quality_score'] = 0
            return
        
        score = 0
        
        # Availability (40 points)
        score += min(40, metrics['availability'] * 0.4)
        
        # Average RTT (30 points) - lower is better
        if metrics['min_rtt'] != float('inf') and len(metrics['jitter_buffer']) > 0:
            avg_rtt = sum(metrics['jitter_buffer']) / len(metrics['jitter_buffer'])
            if avg_rtt < 10:
                score += 30
            elif avg_rtt < 50:
                score += 30 - (avg_rtt - 10) * 0.5
            elif avg_rtt < 100:
                score += 10 - (avg_rtt - 50) * 0.1
        
        # Offset stability (30 points)
        if len(metrics['offset_buffer']) >= 2:
            offset_std = np.std(list(metrics['offset_buffer']))
            if offset_std < 1:
                score += 30
            elif offset_std < 5:
                score += 30 - (offset_std - 1) * 5
            elif offset_std < 10:
                score += 10 - (offset_std - 5) * 2
        
        metrics['quality_score'] = max(0, min(100, score))
    
    def calculate_aggregated_stats(self):
        """Calculate aggregated statistics across all servers"""
        reachable_servers = []
        all_offsets = []
        all_rtts = []
        
        for server, stats in self.current_stats.items():
            if stats.get('reachable'):
                reachable_servers.append(server)
                all_offsets.append(stats.get('offset', 0))
                all_rtts.append(stats.get('rtt', 0))
        
        if reachable_servers:
            self.aggregated_stats = {
                'servers_online': len(reachable_servers),
                'servers_total': len(self.servers),
                'avg_offset': statistics.mean(all_offsets),
                'offset_std': statistics.stdev(all_offsets) if len(all_offsets) > 1 else 0,
                'avg_rtt': statistics.mean(all_rtts),
                'min_rtt': min(all_rtts),
                'max_rtt': max(all_rtts),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
        else:
            self.aggregated_stats = {
                'servers_online': 0,
                'servers_total': len(self.servers),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
    
    def get_comparison_data(self):
        """Get comparison data for all servers"""
        comparison = []
        
        with self.lock:
            for server_config in self.servers:
                server = server_config['address']
                name = server_config['name']
                metrics = self.metrics[server]
                current = self.current_stats.get(server, {})
                
                # Calculate statistics
                if metrics['successful_queries'] > 0:
                    avg_rtt = sum(metrics['jitter_buffer']) / len(metrics['jitter_buffer']) if metrics['jitter_buffer'] else 0
                    avg_offset = metrics['total_offset'] / metrics['successful_queries']
                    
                    # Calculate offset standard deviation
                    if len(metrics['offset_buffer']) > 1:
                        offset_std = np.std(list(metrics['offset_buffer']))
                    else:
                        offset_std = 0
                else:
                    avg_rtt = 0
                    avg_offset = 0
                    offset_std = 0
                
                comparison.append({
                    'server': server,
                    'name': name,
                    'reachable': current.get('reachable', False),
                    'stratum': current.get('stratum', 0),
                    'reference_id': current.get('reference_id', ''),
                    'precision': current.get('precision', 0),
                    'current_offset': current.get('offset', 0),
                    'current_rtt': current.get('rtt', 0),
                    'avg_rtt': avg_rtt,
                    'min_rtt': metrics['min_rtt'] if metrics['min_rtt'] != float('inf') else 0,
                    'max_rtt': metrics['max_rtt'],
                    'avg_offset': avg_offset,
                    'offset_std': offset_std,
                    'availability': metrics['availability'],
                    'quality_score': metrics['quality_score'],
                    'total_queries': metrics['total_queries'],
                    'successful_queries': metrics['successful_queries']
                })
        
        # Sort by quality score
        comparison.sort(key=lambda x: x['quality_score'], reverse=True)
        return comparison
    
    def get_server_history(self, server, duration=3600):
        """Get historical data for a server from database"""
        server_id = self.db.get_server_id(server)
        if not server_id:
            return []

        cutoff = time.time() - duration
        history_records = self.db.get_history(server_id, since=cutoff)

        # Convert database records to the expected format
        return [{
            'timestamp': record['timestamp'],
            'data': json.loads(record['data_json']) if record['data_json'] else {}
        } for record in history_records]
    
    def monitor_loop(self):
        """Main monitoring loop"""
        while self.running:
            try:
                self.query_all_servers()
                logger.debug(f"Queried {len(self.servers)} servers")
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
            
            # Wait before next query
            time.sleep(30)  # Query every 30 seconds
    
    def start(self):
        """Start the monitoring thread"""
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self.monitor_loop, daemon=True)
            self.thread.start()
            self.cleanup_thread.start()
            logger.info("NTP Monitor started")
    
    def stop(self):
        """Stop the monitoring thread"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("NTP Monitor stopped")

# HTML template for the statistics page
STATS_HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NTP Statistics Monitor</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/dist/chartjs-plugin-zoom.min.js"></script>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            margin: 0;
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        .header {
            text-align: center;
            color: white;
            margin-bottom: 30px;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .stat-card {
            background: white;
            padding: 20px;
            border-radius: 10px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.1);
        }
        .add-server-card {
            background: white;
            padding: 20px;
            border-radius: 10px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.1);
            margin-bottom: 30px;
        }
        .add-server-form {
            display: grid;
            grid-template-columns: 2fr 1fr 2fr 1fr;
            gap: 10px;
            align-items: end;
        }
        .form-group {
            display: flex;
            flex-direction: column;
        }
        .form-group label {
            margin-bottom: 5px;
            font-weight: 500;
            color: #333;
            font-size: 14px;
        }
        .form-group input {
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 5px;
            font-size: 14px;
        }
        .btn {
            padding: 10px 20px;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-weight: 500;
            transition: all 0.3s;
        }
        .btn-primary {
            background: #667eea;
            color: white;
        }
        .btn-primary:hover {
            background: #5568d3;
        }
        .btn-danger {
            background: #dc3545;
            color: white;
            font-size: 12px;
            padding: 6px 12px;
        }
        .btn-danger:hover {
            background: #c82333;
        }
        .server-table {
            width: 100%;
            background: white;
            border-radius: 10px;
            overflow: hidden;
            box-shadow: 0 10px 30px rgba(0,0,0,0.1);
        }
        table {
            width: 100%;
            border-collapse: collapse;
        }
        th {
            background: #667eea;
            color: white;
            padding: 15px;
            text-align: left;
            font-weight: 500;
        }
        td {
            padding: 12px 15px;
            border-bottom: 1px solid #f0f0f0;
        }
        .status-badge {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 500;
        }
        .status-online {
            background: #d4edda;
            color: #155724;
        }
        .status-offline {
            background: #f8d7da;
            color: #721c24;
        }
        .chart-container {
            background: white;
            padding: 20px;
            border-radius: 10px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.1);
            margin-bottom: 20px;
            height: 300px;
            position: relative;
        }
        .time-precision {
            font-family: 'Courier New', monospace;
            font-size: 12px;
        }
        .time-ns {
            color: #666;
            font-size: 11px;
        }
        .alert {
            padding: 12px 20px;
            margin-bottom: 20px;
            border-radius: 5px;
            display: none;
        }
        .alert-success {
            background: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
        }
        .alert-error {
            background: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
        }
        @media (max-width: 768px) {
            .add-server-form {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🕐 NTP Statistics Monitor</h1>
            <p>Real-time monitoring of NTP servers with nanosecond precision</p>
        </div>

        <div id="alert-message" class="alert"></div>

        <div class="add-server-card">
            <h3 style="margin-top: 0;">Add NTP Server</h3>
            <div class="add-server-form">
                <div class="form-group">
                    <label for="server-address">Server Address</label>
                    <input type="text" id="server-address" placeholder="time.google.com" required>
                </div>
                <div class="form-group">
                    <label for="server-port">Port</label>
                    <input type="number" id="server-port" placeholder="123" value="123" min="1" max="65535">
                </div>
                <div class="form-group">
                    <label for="server-name">Display Name</label>
                    <input type="text" id="server-name" placeholder="Google NTP">
                </div>
                <div class="form-group">
                    <button class="btn btn-primary" onclick="addServer()">Add Server</button>
                </div>
            </div>
        </div>

        <div class="stats-grid">
            <div class="stat-card">
                <h3>Servers Online</h3>
                <p id="servers-online" style="font-size: 2em; margin: 10px 0; color: #667eea;">--</p>
            </div>
            <div class="stat-card">
                <h3>Best Latency</h3>
                <p id="best-latency" style="font-size: 2em; margin: 10px 0; color: #667eea;">--</p>
            </div>
            <div class="stat-card">
                <h3>Average Offset</h3>
                <p id="avg-offset" style="font-size: 2em; margin: 10px 0; color: #667eea;">--</p>
            </div>
            <div class="stat-card">
                <h3>Best Server</h3>
                <p id="best-server" style="font-size: 1.5em; margin: 10px 0; color: #667eea;">--</p>
            </div>
        </div>

        <div class="chart-container">
            <canvas id="rttChart"></canvas>
            <p style="text-align: center; color: #666; margin-top: 10px; font-size: 12px;">
                💡 Tip: Scroll to zoom, Ctrl+Drag to pan
            </p>
        </div>

        <div class="server-table">
            <table>
                <thead>
                    <tr>
                        <th>Server</th>
                        <th>Status</th>
                        <th>Stratum</th>
                        <th>RTT (µs / ns)</th>
                        <th>Offset (µs / ns)</th>
                        <th>Quality</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody id="server-list">
                </tbody>
            </table>
        </div>
    </div>
    
    <script>
        const ctx = document.getElementById('rttChart').getContext('2d');
        const rttChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: [],
                datasets: []
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    intersect: false,
                    mode: 'index'
                },
                scales: {
                    x: {
                        type: 'time',
                        time: {
                            displayFormats: {
                                minute: 'HH:mm',
                                hour: 'MMM d HH:mm'
                            }
                        },
                        title: {
                            display: true,
                            text: 'Time'
                        }
                    },
                    y: {
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: 'RTT (ms)'
                        }
                    }
                },
                plugins: {
                    zoom: {
                        pan: {
                            enabled: true,
                            mode: 'x',
                            modifierKey: 'ctrl'
                        },
                        zoom: {
                            wheel: {
                                enabled: true,
                                speed: 0.1
                            },
                            pinch: {
                                enabled: true
                            },
                            mode: 'x'
                        },
                        limits: {
                            x: {min: 'original', max: 'original'}
                        }
                    },
                    legend: {
                        display: true,
                        position: 'top'
                    },
                    tooltip: {
                        enabled: true
                    }
                }
            }
        });

        function formatTimePrecision(milliseconds) {
            if (!milliseconds) return '--';
            const microseconds = (milliseconds * 1000).toFixed(2);
            const nanoseconds = (milliseconds * 1000000).toFixed(0);
            return `<div class="time-precision">${microseconds} µs<br><span class="time-ns">${nanoseconds} ns</span></div>`;
        }

        function showAlert(message, type = 'success') {
            const alert = document.getElementById('alert-message');
            alert.textContent = message;
            alert.className = 'alert alert-' + type;
            alert.style.display = 'block';
            setTimeout(() => {
                alert.style.display = 'none';
            }, 5000);
        }

        function addServer() {
            const address = document.getElementById('server-address').value.trim();
            const port = parseInt(document.getElementById('server-port').value);
            const name = document.getElementById('server-name').value.trim() || address;

            if (!address) {
                showAlert('Please enter a server address', 'error');
                return;
            }

            fetch('/stats/api/ntp/add-server', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    server: address,
                    port: port,
                    name: name
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    showAlert(data.message || 'Server added successfully', 'success');
                    document.getElementById('server-address').value = '';
                    document.getElementById('server-port').value = '123';
                    document.getElementById('server-name').value = '';
                    updateStats();
                } else {
                    showAlert(data.error || 'Failed to add server', 'error');
                }
            })
            .catch(error => {
                showAlert('Error: ' + error.message, 'error');
            });
        }

        function removeServer(serverAddress, serverName) {
            if (!confirm(`Are you sure you want to remove ${serverName}?`)) {
                return;
            }

            fetch('/stats/api/ntp/remove-server', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    server: serverAddress
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    showAlert(data.message || 'Server removed successfully', 'success');
                    updateStats();
                } else {
                    showAlert(data.error || 'Failed to remove server', 'error');
                }
            })
            .catch(error => {
                showAlert('Error: ' + error.message, 'error');
            });
        }

        function updateStats() {
            fetch('/stats/api/ntp/stats')
                .then(response => response.json())
                .then(data => {
                    // Update summary stats
                    document.getElementById('servers-online').textContent = data.servers_online || 0;
                    document.getElementById('best-latency').innerHTML =
                        data.best_latency ? formatTimePrecision(data.best_latency) : '--';
                    document.getElementById('avg-offset').innerHTML =
                        data.avg_offset ? formatTimePrecision(Math.abs(data.avg_offset)) : '--';
                    document.getElementById('best-server').textContent = data.best_server_name || '--';

                    // Update server table
                    const tbody = document.getElementById('server-list');
                    tbody.innerHTML = '';

                    if (data.servers) {
                        data.servers.forEach(server => {
                            const row = tbody.insertRow();
                            row.innerHTML = `
                                <td><strong>${server.name}</strong><br><small style="color: #666;">${server.server}</small></td>
                                <td><span class="status-badge status-${server.reachable ? 'online' : 'offline'}">
                                    ${server.reachable ? 'Online' : 'Offline'}</span></td>
                                <td>${server.stratum || '--'}</td>
                                <td>${server.current_rtt ? formatTimePrecision(server.current_rtt) : '--'}</td>
                                <td>${server.current_offset ? formatTimePrecision(Math.abs(server.current_offset)) : '--'}</td>
                                <td>${server.quality_score ? server.quality_score.toFixed(1) + '%' : '--'}</td>
                                <td>
                                    <button class="btn btn-danger" onclick="removeServer('${server.server}', '${server.name}')">
                                        Remove
                                    </button>
                                </td>
                            `;
                        });
                    }

                    // Update chart
                    if (data.history) {
                        const datasets = [];
                        Object.keys(data.history).forEach((server, i) => {
                            const serverData = data.history[server];
                            datasets.push({
                                label: serverData.name,
                                data: serverData.points.map(p => ({
                                    x: new Date(p.timestamp),
                                    y: p.rtt
                                })),
                                borderColor: `hsl(${i * 60}, 70%, 50%)`,
                                fill: false
                            });
                        });
                        rttChart.data.datasets = datasets;
                        rttChart.update();
                    }
                });
        }

        // Allow Enter key to add server
        document.getElementById('server-address').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') addServer();
        });
        document.getElementById('server-name').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') addServer();
        });

        // Update stats every 5 seconds
        updateStats();
        setInterval(updateStats, 5000);
    </script>
</body>
</html>'''

@ntp_stats_bp.route('/')
def index():
    """Redirect to stats page"""
    return render_template_string(STATS_HTML_TEMPLATE)

@ntp_stats_bp.route('/api/ntp/stats')
def api_ntp_stats():
    """Return NTP statistics as JSON"""
    monitor = get_ntp_monitor()

    comparison = monitor.get_comparison_data()
    
    reachable_servers = [s for s in comparison if s['reachable']]
    
    summary = {
        'total_servers': len(comparison),
        'servers_online': len(reachable_servers),
        'best_latency': min([s['current_rtt'] for s in reachable_servers]) if reachable_servers else None,
        'avg_offset': statistics.mean([s['current_offset'] for s in reachable_servers]) if reachable_servers else None,
        'best_server_name': comparison[0]['name'] if comparison else None,
        'servers': comparison,
        'aggregated': monitor.aggregated_stats,
        'history': {}
    }

    # Add history for visualization
    for server_config in monitor.servers[:5]:  # Limit to 5 servers for performance
        server = server_config['address']
        history = monitor.get_server_history(server, 300)  # Last 5 minutes
        if history:
            summary['history'][server] = {
                'name': server_config['name'],
                'points': [
                    {
                        'timestamp': h['data']['timestamp'],
                        'rtt': h['data'].get('rtt', 0),
                        'offset': h['data'].get('offset', 0)
                    }
                    for h in history if h['data'].get('reachable', False)
                ]
            }
    
    return jsonify(summary)

@ntp_stats_bp.route('/api/ntp/add-server', methods=['POST'])
def api_add_server():
    """Add a new NTP server to monitor"""
    monitor = get_ntp_monitor()

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No JSON data provided'}), 400

    server = data.get('server')
    port = data.get('port', 123)
    name = data.get('name', server)

    if not server:
        return jsonify({'error': 'Server address required'}), 400

    if not (0 < port <= 65535):
        return jsonify({'error': 'Port must be between 1 and 65535'}), 400

    try:
        monitor.add_server(server, port, name)
        return jsonify({'success': True, 'message': f'Added server {name}'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@ntp_stats_bp.route('/api/ntp/remove-server', methods=['POST'])
def api_remove_server():
    """Remove an NTP server from monitoring"""
    monitor = get_ntp_monitor()

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No JSON data provided'}), 400

    server = data.get('server')

    if not server:
        return jsonify({'error': 'Server address required'}), 400

    try:
        monitor.remove_server(server)
        return jsonify({'success': True, 'message': f'Removed server {server}'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@ntp_stats_bp.route('/api/ntp/export')
def api_export_stats():
    """Export statistics as CSV"""
    monitor = get_ntp_monitor()

    comparison = monitor.get_comparison_data()
    
    csv_content = "Server,Name,Status,Stratum,Quality Score,Current RTT (ms),Avg RTT (ms),Min RTT (ms),Max RTT (ms),"
    csv_content += "Current Offset (ms),Avg Offset (ms),Offset StdDev (ms),Availability (%),Precision (ms),Reference ID\n"
    
    for server in comparison:
        csv_content += f"{server['server']},{server['name']},{('Online' if server['reachable'] else 'Offline')},"
        csv_content += f"{server['stratum']},{server['quality_score']:.1f},{server['current_rtt']:.2f},"
        csv_content += f"{server['avg_rtt']:.2f},{server['min_rtt']:.2f},{server['max_rtt']:.2f},"
        csv_content += f"{server['current_offset']:.2f},{server['avg_offset']:.2f},{server['offset_std']:.2f},"
        csv_content += f"{server['availability']:.1f},{server['precision']*1000:.3f},{server['reference_id']}\n"
    
    return Response(
        csv_content,
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=ntp_statistics.csv"}
    )

# Export functions and blueprint
__all__ = ['ntp_stats_bp', 'init_ntp_monitor', 'NTPMonitor', 'NTPClient']
