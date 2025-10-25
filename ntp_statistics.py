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
from flask import Blueprint, render_template_string, jsonify, request

# Configure logging
logger = logging.getLogger(__name__)

# Create Flask blueprint
ntp_stats_bp = Blueprint('ntp_stats', __name__)

class NTPClient:
    """NTP Client for querying NTP servers"""
    
    def __init__(self, timeout=1.0):
        self.timeout = timeout
        
    def query_server(self, server, port=123):
        """Query an NTP server and return statistics"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(self.timeout)
            packet = bytearray(48)
            packet[0] = 0x1B  # LI=0, VN=3, Mode=3 (client)
            transmit_time = time.time()
            sock.sendto(packet, (server, port))
            data, address = sock.recvfrom(1024)
            receive_time = time.time()
            rtt = (receive_time - transmit_time) * 1000  # Convert to ms
            
            unpacked = struct.unpack('!B B B b 11I', data[:48])
            li_vn_mode = unpacked[0]
            stratum = unpacked[1]
            poll = unpacked[2]
            precision = unpacked[3]
            root_delay = unpacked[4] / 65536.0
            root_dispersion = unpacked[5] / 65536.0
            ref_id = unpacked[6]
            ref_timestamp_int = unpacked[7]
            ref_timestamp_frac = unpacked[8]
            ref_timestamp = ref_timestamp_int + (ref_timestamp_frac / 2**32)
            origin_timestamp_int = unpacked[9]
            origin_timestamp_frac = unpacked[10]
            recv_timestamp_int = unpacked[11]
            recv_timestamp_frac = unpacked[12]
            recv_timestamp = recv_timestamp_int + (recv_timestamp_frac / 2**32)
            trans_timestamp_int = unpacked[13]
            trans_timestamp_frac = unloaded[14]
            trans_timestamp = trans_timestamp_int + (trans_timestamp_frac / 2**32)
            
            # Fixed: Corrected NTP offset calculation with proper parenthesis
            NTP_EPOCH = datetime(1900, 1, 1, tzinfo=timezone.utc)
            offset = ((recv_timestamp - (origin_timestamp_int + (origin_timestamp_frac / 2**32))) +
                      (trans_timestamp - (receive_time + (datetime(1970, 1, 1, tzinfo=timezone.utc) - NTP_EPOCH).total_seconds()))) / 2
            
            if stratum == 0 or stratum == 1:
                ref_id_str = struct.pack('!I', ref_id).decode('ascii', errors='ignore').strip('\x00')
            else:
                ref_id_str = socket.inet_ntoa(struct.pack('!I', ref_id))
            
            sock.close()
            
            return {
                'server': server,
                'port': port,
                'reachable': True,
                'stratum': stratum,
                'precision': 2 ** precision,
                'root_delay': root_delay * 1000,
                'root_dispersion': root_dispersion * 1000,
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
        except Exception as e:
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
            if server_config not in self.servers:
                self.servers.append(server_config)
                logger.info(f"Added NTP server: {server}:{port} ({name})")
    
    def remove_server(self, server):
        """Remove an NTP server from monitoring"""
        with self.lock:
            self.servers = [s for s in self.servers if s['address'] != server]
    
    def query_all_servers(self):
        """Query all configured NTP servers"""
        results = {}
        
        with self.lock:
            servers = self.servers.copy()
        
        for server_config in servers:
            if not server_config['enabled']:
                continue
                
            server = server_config['address']
            port = server_config['port']
            name = server_config['name']
            
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
                self.calculate_aggregated_stats()
        
        return results
    
    def update_metrics(self, server, result):
        """Update performance metrics for a server"""
        metrics = self.metrics[server]
        
        metrics['total_queries'] += 1
        
        if result['reachable']:
            metrics['successful_queries'] += 1
            metrics['last_success'] = result['timestamp']
            rtt = result['rtt']
            metrics['min_rtt'] = min(metrics['min_rtt'], rtt)
            metrics['max_rtt'] = max(metrics['max_rtt'], rtt)
            offset = result['offset']
            metrics['total_offset'] += offset
            metrics['offset_squares'] += offset ** 2
            metrics['offset_buffer'].append(offset)
            
            if len(metrics['jitter_buffer']) > 0:
                last_rtt = metrics['jitter_buffer'][-1]
                jitter = abs(rtt - last_rtt)
                result['jitter'] = jitter
            metrics['jitter_buffer'].append(rtt)
            
        else:
            metrics['failed_queries'] += 1
            metrics['last_failure'] = result['timestamp']
        
        if metrics['total_queries'] > 0:
            metrics['availability'] = (metrics['successful_queries'] / metrics['total_queries']) * 100
        
        self.calculate_quality_score(server, metrics)
    
    def calculate_quality_score(self, server, metrics):
        """Calculate a quality score for an NTP server (0-100)"""
        score = 100.0
        availability_penalty = (100 - metrics['availability']) * 0.4
        score -= availability_penalty
        
        if metrics['min_rtt'] != float('inf'):
            avg_rtt = sum(metrics['jitter_buffer']) / len(metrics['jitter_buffer']) if metrics['jitter_buffer'] else 0
            if avg_rtt > 100:
                latency_penalty = min(20, (avg_rtt - 100) / 10)
                score -= latency_penalty
        
        if len(metrics['jitter_buffer']) > 1:
            jitter_values = [abs(metrics['jitter_buffer'][i] - metrics['jitter_buffer'][i-1]) for i in range(1, len(metrics['jitter_buffer']))]
            avg_jitter = sum(jitter_values) / len(jitter_values)
            if avg_jitter > 10:
                jitter_penalty = min(20, avg_jitter / 2)
                score -= jitter_penalty
        
        if len(metrics['offset_buffer']) > 1:
            try:
                offset_std = statistics.stdev(metrics['offset_buffer'])
                if offset_std > 50:
                    offset_penalty = min(20, offset_std / 5)
                    score -= offset_penalty
            except statistics.StatisticsError:
                pass
        
        metrics['quality_score'] = max(0, score)
        return metrics['quality_score']
    
    def calculate_aggregated_stats(self):
        """Calculate aggregated statistics across all servers"""
        with self.lock:
            if not self.current_stats:
                self.aggregated_stats = {}
                return
            
            reachable_servers = [s for s in self.current_stats.values() if s['reachable']]
            
            if reachable_servers:
                try:
                    self.aggregated_stats = {
                        'total_servers': len(self.servers),
                        'reachable_servers': len(reachable_servers),
                        'avg_rtt': statistics.mean([s['rtt'] for s in reachable_servers]),
                        'min_rtt': min([s['rtt'] for s in reachable_servers]),
                        'max_rtt': max([s['rtt'] for s in reachable_servers]),
                        'avg_offset': statistics.mean([s['offset'] for s in reachable_servers]),
                        'avg_stratum': statistics.mean([s['stratum'] for s in reachable_servers]),
                        'best_server': min(reachable_servers, key=lambda x: x['rtt'])['server'],
                        'worst_server': max(reachable_servers, key=lambda x: x['rtt'])['server'],
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    }
                    offsets = [s['offset'] for s in reachable_servers]
                    if len(offsets) > 1:
                        self.aggregated_stats['offset_std'] = statistics.stdev(offsets)
                        self.aggregated_stats['offset_spread'] = max(offsets) - min(offsets)
                except statistics.StatisticsError:
                    self.aggregated_stats = {}
            else:
                self.aggregated_stats = {}
    
    def get_server_history(self, server, duration=3600):
        """Get historical data for a server"""
        with self.lock:
            if server not in self.history:
                return []
            cutoff_time = time.time() - duration
            return [h for h in self.history[server] if h['timestamp'] > cutoff_time]
    
    def get_comparison_data(self):
        """Get formatted comparison data for all servers"""
        comparison = []
        
        with self.lock:
            for server_config in self.servers:
                server = server_config['address']
                metrics = self.metrics[server]
                current = self.current_stats.get(server, {})
                
                avg_rtt = sum(metrics['jitter_buffer']) / len(metrics['jitter_buffer']) if metrics['jitter_buffer'] else 0
                avg_offset = metrics['total_offset'] / metrics['successful_queries'] if metrics['successful_queries'] > 0 else 0
                
                if metrics['successful_queries'] > 1:
                    variance = (metrics['offset_squares'] / metrics['successful_queries']) - (avg_offset ** 2)
                    offset_std = variance ** 0.5 if variance > 0 else 0
                else:
                    offset_std = 0
                
                comparison.append({
                    'server': server,
                    'name': server_config['name'],
                    'port': server_config['port'],
                    'reachable': current.get('reachable', False),
                    'stratum': current.get('stratum', '-'),
                    'current_rtt': current.get('rtt', 0),
                    'current_offset': current.get('offset', 0),
                    'avg_rtt': avg_rtt,
                    'min_rtt': metrics['min_rtt'] if metrics['min_rtt'] != float('inf') else 0,
                    'max_rtt': metrics['max_rtt'],
                    'avg_offset': avg_offset,
                    'offset_std': offset_std,
                    'availability': metrics['availability'],
                    'quality_score': metrics['quality_score'],
                    'total_queries': metrics['total_queries'],
                    'successful_queries': metrics['successful_queries'],
                    'reference_id': current.get('reference_id', '-'),
                    'precision': current.get('precision', 0),
                    'last_success': metrics['last_success'],
                    'last_failure': metrics['last_failure']
                })
        
        comparison.sort(key=lambda x: x['quality_score'], reverse=True)
        return comparison
    
    def run_monitor(self, interval=10):
        """Run monitoring loop"""
        self.running = True
        while self.running:
            try:
                self.query_all_servers()
                logger.debug(f"Queried {len(self.servers)} NTP servers")
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
            
            time.sleep(interval)
    
    def start(self, interval=10):
        """Start monitoring in background thread"""
        with self.lock:
            if self.thread and self.thread.is_alive():
                logger.warning("Monitor already running")
                return
            self.thread = threading.Thread(target=self.run_monitor, args=(interval,), daemon=True)
            self.thread.start()
            logger.info(f"Started NTP monitoring with {len(self.servers)} servers")
    
    def stop(self):
        """Stop monitoring"""
        with self.lock:
            self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("Stopped NTP monitoring")

# Global NTP monitor instance
ntp_monitor = None

def init_ntp_monitor(servers=None):
    """Initialize the NTP monitor with default servers"""
    global ntp_monitor
    
    default_servers = [
        {'address': 'time.nist.gov', 'port': 123, 'name': 'NIST (US Gov)'},
        {'address': 'time.google.com', 'port': 123, 'name': 'Google'},
        {'address': 'time.cloudflare.com', 'port': 123, 'name': 'Cloudflare'},
        {'address': 'time.windows.com', 'port': 123, 'name': 'Microsoft'},
        {'address': 'time.apple.com', 'port': 123, 'name': 'Apple'},
        {'address': 'pool.ntp.org', 'port': 123, 'name': 'NTP Pool'},
        {'address': 'time.facebook.com', 'port': 123, 'name': 'Facebook'},
        {'address': 'time.aws.com', 'port': 123, 'name': 'AWS'},
    ]
    
    ntp_monitor = NTPMonitor()
    
    for server in default_servers:
        ntp_monitor.add_server(server['address'], server['port'], server['name'])
    
    if servers:
        for server in servers:
            ntp_monitor.add_server(server['address'], server.get('port', 123), server.get('name'))
    
    ntp_monitor.start(interval=30)
    
    return ntp_monitor

# Flask routes for statistics page
STATS_HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>NTP Server Statistics & Comparison</title>
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
            max-width: 1600px;
            margin: 0 auto;
        }
        h1 {
            color: white;
            text-align: center;
            margin-bottom: 30px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }
        .summary-cards {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 30px;
        }
        .summary-card {
            background: white;
            border-radius: 8px;
            padding: 15px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            text-align: center;
        }
        .summary-card h3 {
            color: #666;
            font-size: 14px;
            margin-bottom: 10px;
            font-weight: 500;
        }
        .summary-value {
            font-size: 28px;
            font-weight: bold;
            color: #333;
        }
        .summary-unit {
            color: #999;
            font-size: 14px;
            margin-left: 4px;
        }
        .comparison-table {
            background: white;
            border-radius: 10px;
            padding: 20px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            margin-bottom: 30px;
            overflow-x: auto;
        }
        .comparison-table h2 {
            color: #333;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 2px solid #667eea;
        }
        table {
            width: 100%;
            border-collapse: collapse;
        }
        th {
            background: #f8f9fa;
            padding: 12px;
            text-align: left;
            font-weight: 600;
            color: #666;
            border-bottom: 2px solid #dee2e6;
            position: sticky;
            top: 0;
            z-index: 10;
        }
        td {
            padding: 10px 12px;
            border-bottom: 1px solid #eee;
        }
        tr:hover {
            background: #f8f9fa;
        }
        .server-name {
            font-weight: 600;
            color: #333;
        }
        .status-badge {
            display: inline-block;
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: 600;
        }
        .status-online {
            background: #d4edda;
            color: #155724;
        }
        .status-offline {
            background: #f8d7da;
            color: #721c24;
        }
        .quality-bar {
            width: 100px;
            height: 20px;
            background: #e9ecef;
            border-radius: 10px;
            overflow: hidden;
            position: relative;
        }
        .quality-fill {
            height: 100%;
            transition: width 0.3s ease;
        }
        .quality-excellent { background: linear-gradient(90deg, #28a745, #20c997); }
        .quality-good { background: linear-gradient(90deg, #ffc107, #fd7e14); }
        .quality-fair { background: linear-gradient(90deg, #fd7e14, #dc3545); }
        .quality-poor { background: #dc3545; }
        .quality-text {
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            text-align: center;
            line-height: 20px;
            font-size: 11px;
            font-weight: bold;
            color: white;
            text-shadow: 1px 1px 1px rgba(0,0,0,0.3);
        }
        .metric-good { color: #28a745; }
        .metric-warning { color: #ffc107; }
        .metric-bad { color: #dc3545; }
        .charts-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(500px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .chart-container {
            background: white;
            border-radius: 10px;
            padding: 20px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
        }
        .chart-container h3 {
            color: #333;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 1px solid #dee2e6;
        }
        #latencyChart, #offsetChart, #jitterChart, #availabilityChart {
            height: 300px;
        }
        .controls {
            background: white;
            border-radius: 10px;
            padding: 15px;
            margin-bottom: 20px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .controls button {
            background: #667eea;
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 5px;
            margin-right: 10px;
            cursor: pointer;
            font-weight: 600;
        }
        .controls button:hover {
            background: #5a67d8;
        }
        .controls input {
            padding: 8px;
            border: 1px solid #dee2e6;
            border-radius: 5px;
            margin-right: 10px;
        }
        .best-server {
            background: #d4edda;
        }
        .local-server {
            background: #cfe2ff;
        }
        .tooltip {
            position: relative;
            display: inline-block;
        }
        .tooltip .tooltiptext {
            visibility: hidden;
            width: 200px;
            background-color: #555;
            color: #fff;
            text-align: center;
            padding: 8px;
            border-radius: 6px;
            position: absolute;
            z-index: 1;
            bottom: 125%;
            left: 50%;
            margin-left: -100px;
            opacity: 0;
            transition: opacity 0.3s;
            font-size: 12px;
        }
        .tooltip:hover .tooltiptext {
            visibility: visible;
            opacity: 1;
        }
        .legend {
            display: flex;
            justify-content: center;
            gap: 20px;
            margin: 10px 0;
            flex-wrap: wrap;
        }
        .legend-item {
            display: flex;
            align-items: center;
            gap: 5px;
            font-size: 12px;
        }
        .legend-color {
            width: 20px;
            height: 10px;
            border-radius: 2px;
        }
        .stats-footer {
            text-align: center;
            color: white;
            margin-top: 20px;
            font-size: 14px;
        }
    </style>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body>
    <div class="container">
        <h1>📊 NTP Server Statistics & Comparison</h1>
        
        <div class="controls">
            <button onclick="refreshStats()">🔄 Refresh</button>
            <button onclick="addServer()">➕ Add Server</button>
            <button onclick="exportData()">📥 Export CSV</button>
            <input type="text" id="newServer" placeholder="NTP server address">
            <input type="number" id="newPort" placeholder="Port" value="123" style="width: 80px;">
            <span style="margin-left: 20px; color: #666;">Auto-refresh: <span id="countdown">30</span>s</span>
        </div>
        
        <div class="summary-cards">
            <div class="summary-card">
                <h3>Servers Monitored</h3>
                <div class="summary-value" id="total-servers">-</div>
            </div>
            <div class="summary-card">
                <h3>Servers Online</h3>
                <div class="summary-value" id="servers-online">-</div>
            </div>
            <div class="summary-card">
                <h3>Best Latency</h3>
                <div class="summary-value"><span id="best-latency">-</span><span class="summary-unit">ms</span></div>
            </div>
            <div class="summary-card">
                <h3>Average Offset</h3>
                <div class="summary-value"><span id="avg-offset">-</span><span class="summary-unit">ms</span></div>
            </div>
            <div class="summary-card">
                <h3>GPS Server Status</h3>
                <div class="summary-value" id="gps-status">-</div>
            </div>
            <div class="summary-card">
                <h3>Best Server</h3>
                <div class="summary-value" id="best-server" style="font-size: 14px;">-</div>
            </div>
        </div>
        
        <div class="comparison-table">
            <h2>🔍 Server Comparison</h2>
            <table id="comparison-table">
                <thead>
                    <tr>
                        <th>Server</th>
                        <th>Status</th>
                        <th>Stratum</th>
                        <th>Quality</th>
                        <th>Current RTT</th>
                        <th>Avg RTT</th>
                        <th>Min/Max RTT</th>
                        <th>Current Offset</th>
                        <th>Avg Offset</th>
                        <th>Std Dev</th>
                        <th>Availability</th>
                        <th>Precision</th>
                        <th>Reference</th>
                    </tr>
                </thead>
                <tbody id="comparison-tbody">
                    <tr>
                        <td colspan="13" style="text-align: center; color: #999;">Loading...</td>
                    </tr>
                </tbody>
            </table>
        </div>
        
        <div class="charts-grid">
            <div class="chart-container">
                <h3>📈 Latency Comparison (RTT)</h3>
                <canvas id="latencyChart"></canvas>
            </div>
            <div class="chart-container">
                <h3>⏱️ Offset from System Time</h3>
                <canvas id="offsetChart"></canvas>
            </div>
            <div class="chart-container">
                <h3>📊 Jitter (Latency Variation)</h3>
                <canvas id="jitterChart"></canvas>
            </div>
            <div class="chart-container">
                <h3>✅ Availability (%)</h3>
                <canvas id="availabilityChart"></canvas>
            </div>
        </div>
        
        <div class="chart-container">
            <h3>📉 Historical Performance (Last Hour)</h3>
            <canvas id="historicalChart"></canvas>
            <div class="legend" id="historicalLegend"></div>
        </div>
        
        <div class="stats-footer">
            Last updated: <span id="last-update">-</span> | 
            Query interval: 30 seconds | 
            Monitoring since: <span id="monitor-start">-</span>
        </div>
    </div>
    
    <script>
        let charts = {};
        let refreshTimer = 30;
        let monitorStartTime = new Date();
        
        function initCharts() {
            charts.latency = new Chart(document.getElementById('latencyChart'), {
                type: 'bar',
                data: {
                    labels: [],
                    datasets: [{
                        label: 'Current RTT (ms)',
                        data: [],
                        backgroundColor: 'rgba(102, 126, 234, 0.8)',
                        borderColor: 'rgba(102, 126, 234, 1)',
                        borderWidth: 1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: {
                            beginAtZero: true,
                            title: {
                                display: true,
                                text: 'Round Trip Time (ms)'
                            }
                        }
                    }
                }
            });
            
            charts.offset = new Chart(document.getElementById('offsetChart'), {
                type: 'bar',
                data: {
                    labels: [],
                    datasets: [{
                        label: 'Time Offset (ms)',
                        data: [],
                        backgroundColor: [],
                        borderColor: [],
                        borderWidth: 1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: {
                            title: {
                                display: true,
                                text: 'Offset (ms)'
                            }
                        }
                    }
                }
            });
            
            charts.jitter = new Chart(document.getElementById('jitterChart'), {
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
                                text: 'Jitter (ms)'
                            }
                        }
                    }
                }
            });
            
            charts.availability = new Chart(document.getElementById('availabilityChart'), {
                type: 'doughnut',
                data: {
                    labels: [],
                    datasets: [{
                        data: [],
                        backgroundColor: [],
                        borderWidth: 0
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            position: 'right'
                        }
                    }
                }
            });
            
            charts.historical = new Chart(document.getElementById('historicalChart'), {
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
                        },
                        x: {
                            type: 'time',
                            time: {
                                unit: 'minute',
                                displayFormats: {
                                    minute: 'HH:mm'
                                }
                            },
                            title: {
                                display: true,
                                text: 'Time'
                            }
                        }
                    },
                    plugins: {
                        legend: {
                            display: false
                        }
                    }
                }
            });
        }
        
        function formatNumber(num, decimals = 2) {
            if (num === null || num === undefined || isNaN(num)) return '-';
            return num.toFixed(decimals);
        }
        
        function getQualityColor(score) {
            if (score >= 90) return 'quality-excellent';
            if (score >= 70) return 'quality-good';
            if (score >= 50) return 'quality-fair';
            return 'quality-poor';
        }
        
        function getMetricColor(value, thresholds) {
            if (value <= thresholds.good) return 'metric-good';
            if (value <= thresholds.warning) return 'metric-warning';
            return 'metric-bad';
        }
        
        function updateStats() {
            fetch('/api/ntp/stats')
                .then(response => {
                    if (!response.ok) throw new Error('Failed to fetch NTP stats');
                    return response.json();
                })
                .then(data => {
                    document.getElementById('total-servers').textContent = data.total_servers || 0;
                    document.getElementById('servers-online').textContent = data.servers_online || 0;
                    document.getElementById('best-latency').textContent = formatNumber(data.best_latency);
                    document.getElementById('avg-offset').textContent = formatNumber(data.avg_offset);
                    document.getElementById('best-server').textContent = data.best_server_name || '-';
                    
                    const gpsServer = data.servers.find(s => s.name.includes('GPS'));
                    if (gpsServer) {
                        document.getElementById('gps-status').textContent = gpsServer.reachable ? 'Online' : 'Offline';
                        document.getElementById('gps-status').className = gpsServer.reachable ? 'metric-good' : 'metric-bad';
                    }
                    
                    updateComparisonTable(data.servers);
                    updateCharts(data);
                    
                    document.getElementById('last-update').textContent = new Date().toLocaleTimeString();
                    document.getElementById('monitor-start').textContent = monitorStartTime.toLocaleTimeString();
                })
                .catch(error => {
                    console.error('Error fetching stats:', error);
                    document.getElementById('comparison-tbody').innerHTML = 
                        '<tr><td colspan="13" style="text-align: center; color: #999;">Error fetching data</td></tr>';
                });
        }
        
        function updateComparisonTable(servers) {
            const tbody = document.getElementById('comparison-tbody');
            
            if (!servers || servers.length === 0) {
                tbody.innerHTML = '<tr><td colspan="13" style="text-align: center; color: #999;">No data available</td></tr>';
                return;
            }
            
            servers.sort((a, b) => b.quality_score - a.quality_score);
            
            tbody.innerHTML = servers.map(server => {
                const isGPS = server.name.includes('GPS');
                const isBest = server.quality_score === Math.max(...servers.map(s => s.quality_score));
                const rowClass = isGPS ? 'local-server' : (isBest ? 'best-server' : '');
                
                return `
                    <tr class="${rowClass}">
                        <td class="server-name">
                            ${server.name}
                            ${isGPS ? '🛰️' : ''}
                            ${isBest && !isGPS ? '👑' : ''}
                        </td>
                        <td>
                            <span class="status-badge ${server.reachable ? 'status-online' : 'status-offline'}">
                                ${server.reachable ? 'Online' : 'Offline'}
                            </span>
                        </td>
                        <td>${server.stratum || '-'}</td>
                        <td>
                            <div class="quality-bar tooltip">
                                <div class="quality-fill ${getQualityColor(server.quality_score)}" 
                                     style="width: ${server.quality_score}%"></div>
                                <div class="quality-text">${formatNumber(server.quality_score, 0)}%</div>
                                <span class="tooltiptext">
                                    Quality factors: Availability, Latency, Jitter, Offset stability
                                </span>
                            </div>
                        </td>
                        <td class="${getMetricColor(server.current_rtt, {good: 50, warning: 100})}">
                            ${formatNumber(server.current_rtt)} ms
                        </td>
                        <td>${formatNumber(server.avg_rtt)} ms</td>
                        <td>${formatNumber(server.min_rtt)}/${formatNumber(server.max_rtt)} ms</td>
                        <td class="${getMetricColor(Math.abs(server.current_offset), {good: 10, warning: 50})}">
                            ${server.current_offset > 0 ? '+' : ''}${formatNumber(server.current_offset)} ms
                        </td>
                        <td>${formatNumber(server.avg_offset)} ms</td>
                        <td>${formatNumber(server.offset_std)} ms</td>
                        <td class="${getMetricColor(100 - server.availability, {good: 1, warning: 5})}">
                            ${formatNumber(server.availability, 1)}%
                        </td>
                        <td>${formatNumber(server.precision * 1000)} ms</td>
                        <td>${server.reference_id || '-'}</td>
                    </tr>
                `;
            }).join('');
        }
        
        function updateCharts(data) {
            if (!data.servers) return;
            
            const servers = data.servers.filter(s => s.reachable);
            
            charts.latency.data.labels = servers.map(s => s.name);
            charts.latency.data.datasets[0].data = servers.map(s => s.current_rtt);
            charts.latency.update();
            
            charts.offset.data.labels = servers.map(s => s.name);
            charts.offset.data.datasets[0].data = servers.map(s => s.current_offset);
            charts.offset.data.datasets[0].backgroundColor = servers.map(s => {
                const absOffset = Math.abs(s.current_offset);
                if (absOffset < 10) return 'rgba(40, 167, 69, 0.8)';
                if (absOffset < 50) return 'rgba(255, 193, 7, 0.8)';
                return 'rgba(220, 53, 69, 0.8)';
            });
            charts.offset.data.datasets[0].borderColor = servers.map(s => {
                const absOffset = Math.abs(s.current_offset);
                if (absOffset < 10) return 'rgba(40, 167, 69, 1)';
                if (absOffset < 50) return 'rgba(255, 193, 7, 1)';
                return 'rgba(220, 53, 69, 1)';
            });
            charts.offset.update();
            
            charts.availability.data.labels = data.servers.map(s => s.name);
            charts.availability.data.datasets[0].data = data.servers.map(s => s.availability);
            charts.availability.data.datasets[0].backgroundColor = data.servers.map(s => {
                if (s.availability >= 99) return '#28a745';
                if (s.availability >= 95) return '#ffc107';
                return '#dc3545';
            });
            charts.availability.update();
            
            if (data.history) {
                updateHistoricalChart(data.history);
            }
        }
        
        function updateHistoricalChart(history) {
            const colors = [
                '#667eea', '#28a745', '#ffc107', '#dc3545', '#17a2b8',
                '#6610f2', '#e83e8c', '#fd7e14', '#20c997', '#6c757d'
            ];
            
            const datasets = [];
            const legendHtml = [];
            let colorIndex = 0;
            
            const now = new Date();
            const oneHourAgo = new Date(now.getTime() - 60 * 60 * 1000);
            const labels = [];
            for (let i = 0; i <= 60; i += 5) {
                const time = new Date(oneHourAgo.getTime() + i * 60 * 1000);
                labels.push(time);
            }
            
            for (const [server, data] of Object.entries(history)) {
                const color = colors[colorIndex % colors.length];
                datasets.push({
                    label: data.name,
                    data: data.points.map(p => ({x: new Date(p.timestamp), y: p.rtt})),
                    borderColor: color,
                    backgroundColor: color + '20',
                    borderWidth: 2,
                    fill: false,
                    tension: 0.1,
                    pointRadius: 0
                });
                
                legendHtml.push(`
                    <div class="legend-item">
                        <div class="legend-color" style="background: ${color}"></div>
                        <span>${data.name}</span>
                    </div>
                `);
                
                colorIndex++;
            }
            
            charts.historical.data.labels = labels;
            charts.historical.data.datasets = datasets;
            charts.historical.update();
            
            document.getElementById('historicalLegend').innerHTML = legendHtml.join('');
        }
        
        function refreshStats() {
            updateStats();
            refreshTimer = 30;
        }
        
        function addServer() {
            const server = document.getElementById('newServer').value;
            const port = document.getElementById('newPort').value || 123;
            
            if (!server) {
                alert('Please enter a server address');
                return;
            }
            
            fetch('/api/ntp/add-server', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({server: server, port: parseInt(port)})
            })
            .then(response => {
                if (!response.ok) throw new Error('Failed to add server');
                return response.json();
            })
            .then(data => {
                if (data.success) {
                    document.getElementById('newServer').value = '';
                    refreshStats();
                } else {
                    alert('Failed to add server: ' + (data.error || 'Unknown error'));
                }
            })
            .catch(error => alert('Error adding server: ' + error));
        }
        
        function exportData() {
            fetch('/api/ntp/export')
                .then(response => {
                    if (!response.ok) throw new Error('Failed to export data');
                    return response.blob();
                })
                .then(blob => {
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = 'ntp_stats_' + new Date().toISOString().split('T')[0] + '.csv';
                    document.body.appendChild(a);
                    a.click();
                    a.remove();
                    window.URL.revokeObjectURL(url);
                })
                .catch(error => alert('Error exporting data: ' + error));
        }
        
        function updateCountdown() {
            document.getElementById('countdown').textContent = refreshTimer;
            refreshTimer--;
            
            if (refreshTimer < 0) {
                refreshStats();
            }
        }
        
        initCharts();
        updateStats();
        
        setInterval(updateCountdown, 1000);
        
        document.getElementById('newServer').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') addServer();
        });
    </script>
</body>
</html>
'''

@ntp_stats_bp.route('/stats')
def stats_page():
    """Serve NTP statistics page"""
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
    
    for server_config in ntp_monitor.servers[:5]:
        server = server_config['address']
        history = ntp_monitor.get_server_history(server, 3600)
        if history:
            step = max(1, len(history) // 20)
            sampled = history[::step]
            summary['history'][server] = {
                'name': server_config['name'],
                'points': [
                    {
                        'timestamp': h['data']['timestamp'],
                        'rtt': h['data'].get('rtt', 0),
                        'offset': h['data'].get('offset', 0)
                    }
                    for h in sampled if h['data'].get('reachable', False)
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
    
    from flask import Response
    return Response(
        csv_content,
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=ntp_statistics.csv"}
    )

# Export functions and blueprint
__all__ = ['ntp_stats_bp', 'init_ntp_monitor', 'NTPMonitor', 'NTPClient']
