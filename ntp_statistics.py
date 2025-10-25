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

# Create Flask blueprint
ntp_stats_bp = Blueprint('ntp_stats', __name__)

# Global NTP monitor instance
ntp_monitor = None

def init_ntp_monitor(servers=None):
    """Initialize the global NTP monitor"""
    global ntp_monitor
    if not ntp_monitor:
        ntp_monitor = NTPMonitor(servers=servers)
        ntp_monitor.start()
        logger.info(f"NTP Monitor initialized with {len(servers) if servers else 0} servers")
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
    
    def __init__(self, servers=None, history_size=3600):
        self.servers = servers or []
        self.history_size = history_size
        self.client = NTPClient()
        self.running = False
        self.thread = None
        self.current_stats = {}
        self.history = defaultdict(lambda: deque(maxlen=history_size))
        self.aggregated_stats = {}
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
        self.lock = threading.Lock()
        
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
            logger.info(f"Added NTP server: {server}:{port} ({name})")
    
    def remove_server(self, server):
        """Remove an NTP server from monitoring"""
        with self.lock:
            self.servers = [s for s in self.servers if s['address'] != server]
            # Also remove history and metrics
            if server in self.history:
                del self.history[server]
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
                self.history[server].append({
                    'timestamp': time.time(),
                    'data': result
                })
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
        """Get historical data for a server"""
        with self.lock:
            if server in self.history:
                history_list = list(self.history[server])
                cutoff = time.time() - duration
                return [h for h in history_list if h['timestamp'] >= cutoff]
        return []
    
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
            logger.info("NTP Monitor started")
    
    def stop(self):
        """Stop the monitoring thread"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("NTP Monitor stopped")

# HTML template for the statistics page (truncated for space)
STATS_HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NTP Statistics Monitor</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
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
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🕐 NTP Statistics Monitor</h1>
            <p>Real-time monitoring of NTP servers</p>
        </div>
        
        <div class="stats-grid">
            <div class="stat-card">
                <h3>Servers Online</h3>
                <p id="servers-online">--</p>
            </div>
            <div class="stat-card">
                <h3>Best Latency</h3>
                <p id="best-latency">--</p>
            </div>
            <div class="stat-card">
                <h3>Average Offset</h3>
                <p id="avg-offset">--</p>
            </div>
            <div class="stat-card">
                <h3>Best Server</h3>
                <p id="best-server">--</p>
            </div>
        </div>
        
        <div class="chart-container">
            <canvas id="rttChart"></canvas>
        </div>
        
        <div class="server-table">
            <table>
                <thead>
                    <tr>
                        <th>Server</th>
                        <th>Status</th>
                        <th>Stratum</th>
                        <th>RTT (ms)</th>
                        <th>Offset (ms)</th>
                        <th>Quality</th>
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
                scales: {
                    y: {
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: 'RTT (ms)'
                        }
                    }
                }
            }
        });
        
        function updateStats() {
            fetch('/stats/api/ntp/stats')
                .then(response => response.json())
                .then(data => {
                    // Update summary stats
                    document.getElementById('servers-online').textContent = data.servers_online || 0;
                    document.getElementById('best-latency').textContent = 
                        data.best_latency ? data.best_latency.toFixed(2) + ' ms' : '--';
                    document.getElementById('avg-offset').textContent = 
                        data.avg_offset ? data.avg_offset.toFixed(2) + ' ms' : '--';
                    document.getElementById('best-server').textContent = data.best_server_name || '--';
                    
                    // Update server table
                    const tbody = document.getElementById('server-list');
                    tbody.innerHTML = '';
                    
                    if (data.servers) {
                        data.servers.forEach(server => {
                            const row = tbody.insertRow();
                            row.innerHTML = `
                                <td>${server.name}</td>
                                <td><span class="status-badge status-${server.reachable ? 'online' : 'offline'}">
                                    ${server.reachable ? 'Online' : 'Offline'}</span></td>
                                <td>${server.stratum || '--'}</td>
                                <td>${server.current_rtt ? server.current_rtt.toFixed(2) : '--'}</td>
                                <td>${server.current_offset ? server.current_offset.toFixed(2) : '--'}</td>
                                <td>${server.quality_score ? server.quality_score.toFixed(1) + '%' : '--'}</td>
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
    if not ntp_monitor:
        return jsonify({'error': 'NTP monitor not initialized'}), 500
    
    comparison = ntp_monitor.get_comparison_data()
    
    reachable_servers = [s for s in comparison if s['reachable']]
    
    summary = {
        'total_servers': len(comparison),
        'servers_online': len(reachable_servers),
        'best_latency': min([s['current_rtt'] for s in reachable_servers]) if reachable_servers else None,
        'avg_offset': statistics.mean([s['current_offset'] for s in reachable_servers]) if reachable_servers else None,
        'best_server_name': comparison[0]['name'] if comparison else None,
        'servers': comparison,
        'aggregated': ntp_monitor.aggregated_stats,
        'history': {}
    }
    
    # Add history for visualization
    for server_config in ntp_monitor.servers[:5]:  # Limit to 5 servers for performance
        server = server_config['address']
        history = ntp_monitor.get_server_history(server, 300)  # Last 5 minutes
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
    if not ntp_monitor:
        return jsonify({'error': 'NTP monitor not initialized'}), 500
    
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
        ntp_monitor.add_server(server, port, name)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@ntp_stats_bp.route('/api/ntp/export')
def api_export_stats():
    """Export statistics as CSV"""
    if not ntp_monitor:
        return jsonify({'error': 'NTP monitor not initialized'}), 500
    
    comparison = ntp_monitor.get_comparison_data()
    
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
