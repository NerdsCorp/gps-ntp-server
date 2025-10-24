#!/usr/bin/env python3
"""
Standalone NTP Server Testing and Comparison Tool
Test and compare multiple NTP servers without GPS requirements
"""

import argparse
import json
import sys
import time
from datetime import datetime
import statistics

# Import the NTP statistics module
from ntp_statistics import NTPClient, NTPMonitor

def print_header():
    """Print tool header"""
    print("=" * 70)
    print("NTP Server Testing and Comparison Tool")
    print("=" * 70)
    print()

def format_table(data, headers):
    """Format data as a table"""
    # Calculate column widths
    col_widths = []
    for i, header in enumerate(headers):
        width = len(header)
        for row in data:
            if i < len(row):
                width = max(width, len(str(row[i])))
        col_widths.append(width + 2)
    
    # Print header
    header_row = ""
    for i, header in enumerate(headers):
        header_row += str(header).ljust(col_widths[i])
    print(header_row)
    print("-" * sum(col_widths))
    
    # Print data
    for row in data:
        row_str = ""
        for i, cell in enumerate(row):
            if i < len(col_widths):
                row_str += str(cell).ljust(col_widths[i])
        print(row_str)

def test_single_server(server, port=123, count=5):
    """Test a single NTP server"""
    client = NTPClient(timeout=2.0)
    results = []
    
    print(f"Testing {server}:{port} ({count} queries)...")
    print()
    
    for i in range(count):
        result = client.query_server(server, port)
        results.append(result)
        
        if result['reachable']:
            print(f"  Query {i+1}: RTT={result['rtt']:.2f}ms, "
                  f"Offset={result['offset']:.2f}ms, "
                  f"Stratum={result['stratum']}")
        else:
            print(f"  Query {i+1}: Failed - {result.get('error', 'Unknown error')}")
        
        time.sleep(0.5)
    
    # Calculate statistics
    successful = [r for r in results if r['reachable']]
    
    if successful:
        rtts = [r['rtt'] for r in successful]
        offsets = [r['offset'] for r in successful]
        
        print()
        print("Statistics:")
        print(f"  Success Rate: {len(successful)}/{count} ({100*len(successful)/count:.1f}%)")
        print(f"  RTT - Min: {min(rtts):.2f}ms, Avg: {statistics.mean(rtts):.2f}ms, Max: {max(rtts):.2f}ms")
        if len(rtts) > 1:
            print(f"  RTT StdDev: {statistics.stdev(rtts):.2f}ms")
        print(f"  Offset - Min: {min(offsets):.2f}ms, Avg: {statistics.mean(offsets):.2f}ms, Max: {max(offsets):.2f}ms")
        if len(offsets) > 1:
            print(f"  Offset StdDev: {statistics.stdev(offsets):.2f}ms")
        
        # Get server details from last successful query
        last = successful[-1]
        print(f"  Stratum: {last['stratum']}")
        print(f"  Reference ID: {last['reference_id']}")
        print(f"  Precision: {last['precision']*1000:.3f}ms")
    else:
        print()
        print("All queries failed!")
    
    return results

def compare_servers(servers, count=5):
    """Compare multiple NTP servers"""
    all_results = {}
    
    print("Comparing NTP Servers")
    print("=" * 70)
    
    # Test each server
    for server_spec in servers:
        if ':' in server_spec:
            server, port = server_spec.rsplit(':', 1)
            port = int(port)
        else:
            server = server_spec
            port = 123
        
        results = test_single_server(server, port, count)
        all_results[server] = results
        print()
        print("-" * 70)
        print()
    
    # Generate comparison summary
    print("COMPARISON SUMMARY")
    print("=" * 70)
    
    comparison_data = []
    for server, results in all_results.items():
        successful = [r for r in results if r['reachable']]
        
        if successful:
            rtts = [r['rtt'] for r in successful]
            offsets = [r['offset'] for r in successful]
            
            comparison_data.append([
                server,
                f"{len(successful)}/{count}",
                f"{statistics.mean(rtts):.2f}",
                f"{min(rtts):.2f}",
                f"{max(rtts):.2f}",
                f"{statistics.stdev(rtts):.2f}" if len(rtts) > 1 else "N/A",
                f"{statistics.mean(offsets):.2f}",
                str(successful[0]['stratum'])
            ])
        else:
            comparison_data.append([
                server,
                "0/" + str(count),
                "N/A", "N/A", "N/A", "N/A", "N/A", "N/A"
            ])
    
    # Sort by average RTT
    comparison_data.sort(key=lambda x: float(x[2]) if x[2] != "N/A" else 999999)
    
    headers = ["Server", "Success", "Avg RTT", "Min RTT", "Max RTT", "StdDev", "Avg Offset", "Stratum"]
    format_table(comparison_data, headers)
    
    print()
    
    # Find best server
    if comparison_data and comparison_data[0][2] != "N/A":
        print(f"🏆 Best Server (lowest latency): {comparison_data[0][0]}")
        print(f"   Average RTT: {comparison_data[0][2]}ms")
    
    return all_results

def monitor_servers(servers, duration=60, interval=10):
    """Monitor servers over time"""
    monitor = NTPMonitor()
    
    # Add servers
    for server_spec in servers:
        if ':' in server_spec:
            server, port = server_spec.rsplit(':', 1)
            port = int(port)
        else:
            server = server_spec
            port = 123
        
        monitor.add_server(server, port, server)
    
    print(f"Monitoring {len(servers)} servers for {duration} seconds")
    print(f"Query interval: {interval} seconds")
    print("=" * 70)
    
    start_time = time.time()
    query_count = 0
    
    try:
        while time.time() - start_time < duration:
            query_count += 1
            print(f"\nQuery #{query_count} at {datetime.now().strftime('%H:%M:%S')}")
            print("-" * 40)
            
            # Query all servers
            results = monitor.query_all_servers()
            
            # Display current results
            for server, result in results.items():
                if result['reachable']:
                    print(f"  {result['name']:20} RTT: {result['rtt']:6.2f}ms  "
                          f"Offset: {result['offset']:+7.2f}ms  "
                          f"Stratum: {result['stratum']}")
                else:
                    print(f"  {result['name']:20} UNREACHABLE")
            
            # Show aggregated stats
            if monitor.aggregated_stats:
                stats = monitor.aggregated_stats
                print()
                print(f"  Average RTT: {stats['avg_rtt']:.2f}ms")
                print(f"  Best server: {stats['best_server']}")
            
            time.sleep(interval)
            
    except KeyboardInterrupt:
        print("\n\nMonitoring stopped by user")
    
    # Final summary
    print("\n" + "=" * 70)
    print("MONITORING SUMMARY")
    print("=" * 70)
    
    comparison = monitor.get_comparison_data()
    
    if comparison:
        headers = ["Server", "Availability", "Avg RTT", "Min RTT", "Max RTT", "Quality"]
        data = []
        
        for server in comparison:
            data.append([
                server['name'][:30],
                f"{server['availability']:.1f}%",
                f"{server['avg_rtt']:.2f}ms",
                f"{server['min_rtt']:.2f}ms",
                f"{server['max_rtt']:.2f}ms",
                f"{server['quality_score']:.0f}/100"
            ])
        
        format_table(data, headers)
    
    return monitor

def export_results(results, filename):
    """Export results to JSON file"""
    with open(filename, 'w') as f:
        # Convert results to serializable format
        export_data = {
            'timestamp': datetime.now().isoformat(),
            'servers': {}
        }
        
        for server, server_results in results.items():
            export_data['servers'][server] = []
            for result in server_results:
                # Remove non-serializable items
                clean_result = {k: v for k, v in result.items() 
                              if not callable(v)}
                export_data['servers'][server].append(clean_result)
        
        json.dump(export_data, f, indent=2)
    
    print(f"Results exported to {filename}")

def main():
    parser = argparse.ArgumentParser(
        description='NTP Server Testing and Comparison Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test a single server
  %(prog)s --server time.google.com
  
  # Test multiple servers
  %(prog)s --server time.google.com time.cloudflare.com pool.ntp.org
  
  # Test with custom port
  %(prog)s --server myserver.com:8123
  
  # Compare servers with 10 queries each
  %(prog)s --compare --count 10 --server time.google.com time.nist.gov
  
  # Monitor servers for 5 minutes
  %(prog)s --monitor --duration 300 --server time.google.com time.cloudflare.com
  
  # Export results to JSON
  %(prog)s --server time.google.com --export results.json
        """
    )
    
    parser.add_argument('--server', '-s', nargs='+', required=True,
                       help='NTP server(s) to test (can specify port as server:port)')
    parser.add_argument('--count', '-c', type=int, default=5,
                       help='Number of queries per server (default: 5)')
    parser.add_argument('--compare', action='store_true',
                       help='Compare multiple servers')
    parser.add_argument('--monitor', '-m', action='store_true',
                       help='Monitor servers over time')
    parser.add_argument('--duration', '-d', type=int, default=60,
                       help='Monitoring duration in seconds (default: 60)')
    parser.add_argument('--interval', '-i', type=int, default=10,
                       help='Query interval for monitoring (default: 10)')
    parser.add_argument('--export', '-e', metavar='FILE',
                       help='Export results to JSON file')
    parser.add_argument('--quiet', '-q', action='store_true',
                       help='Minimal output')
    
    args = parser.parse_args()
    
    if not args.quiet:
        print_header()
    
    results = None
    
    try:
        if args.monitor:
            # Monitor mode
            monitor = monitor_servers(args.server, args.duration, args.interval)
            # Convert monitor data to results format for export
            if args.export:
                results = {}
                for server_config in monitor.servers:
                    server = server_config['address']
                    history = monitor.get_server_history(server)
                    results[server] = [h['data'] for h in history]
        elif args.compare or len(args.server) > 1:
            # Comparison mode
            results = compare_servers(args.server, args.count)
        else:
            # Single server test
            server_spec = args.server[0]
            if ':' in server_spec:
                server, port = server_spec.rsplit(':', 1)
                port = int(port)
            else:
                server = server_spec
                port = 123
            
            server_results = test_single_server(server, port, args.count)
            results = {server: server_results}
        
        # Export if requested
        if args.export and results:
            export_results(results, args.export)
        
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
