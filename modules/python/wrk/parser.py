import sys
import re
import json

def parse_wrk_result(result_file):
    
    try:
        file = open(result_file, 'r')
        result = file.read()
        file.close()
        
        if not result:
            print("No data to process!")
            sys.exit(1)
      
        parsed_result = {}

        # Extracting test parameters
        test_params_match = re.search(r'Running (\S+) test @ (\S+)\n\s+(\d+) threads and (\d+) connections', result)
        if test_params_match:
            duration, duration_unit = parse_unit(test_params_match.group(1))
            parsed_result['duration'] = { 'value': duration, 'unit': duration_unit}
            parsed_result['url'] = test_params_match.group(2)
            parsed_result['threads'] = int(test_params_match.group(3))
            parsed_result['connections'] = int(test_params_match.group(4))

        # Extracting thread stats
        latency_stats_match = re.search(r'Latency\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)', result)
        if latency_stats_match:
            avg, avg_unit = parse_unit(latency_stats_match.group(1))
            stdev, stdev_unit = parse_unit(latency_stats_match.group(2))
            maximum, max_unit = parse_unit(latency_stats_match.group(3))
            within_stdev, within_stdev_unit = parse_unit(latency_stats_match.group(4))
            parsed_result['latency_stats'] = {
                'avg': { 'value': avg, 'unit': avg_unit },
                'stdev': { 'value': stdev, 'unit': stdev_unit },
                'max': { 'value': maximum, 'unit': max_unit },
                'within_stdev': { 'value': within_stdev, 'unit': within_stdev_unit }
            }

        req_sec_stats_match = re.search(r'Req/Sec\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)', result)
        if req_sec_stats_match:
            avg, avg_unit = parse_unit(req_sec_stats_match.group(1))
            stdev, stdev_unit = parse_unit(req_sec_stats_match.group(2))
            maximum, max_unit = parse_unit(req_sec_stats_match.group(3))
            within_stdev, within_stdev_unit = parse_unit(req_sec_stats_match.group(4))
            parsed_result['req_sec_stats'] = {
                'avg': { 'value': avg, 'unit': avg_unit },
                'stdev': { 'value': stdev, 'unit': stdev_unit },
                'max': { 'value': maximum, 'unit': max_unit },
                'within_stdev': { 'value': within_stdev, 'unit': within_stdev_unit }
            }

        # Extracting latency distribution
        latency_distribution_match = re.search(r'Latency Distribution\n\s+50%\s+(\S+)\n\s+75%\s+(\S+)\n\s+90%\s+(\S+)\n\s+99%\s+(\S+)', result)
        if latency_distribution_match:
            per50, per50_unit = parse_unit(latency_distribution_match.group(1))
            per75, per75_unit = parse_unit(latency_distribution_match.group(2))
            per90, per90_unit = parse_unit(latency_distribution_match.group(3))
            per99, per99_unit = parse_unit(latency_distribution_match.group(4))
            parsed_result['latency_distribution'] = {
                '50th_percentile': { 'value': per50, 'unit': per50_unit },
                '75th_percentile': { 'value': per75, 'unit': per75_unit },
                '90th_percentile': { 'value': per90, 'unit': per90_unit },
                '99th_percentile': { 'value': per99, 'unit': per99_unit }
            }

        # Extracting total requests
        total_requests_match = re.search(r'(\d+) requests in', result)
        if total_requests_match:
            parsed_result['total_requests'] = int(total_requests_match.group(1))
        
        # Extracting total read
        total_read_match = re.search(r'(\S+) read', result)
        if total_read_match:
            value, unit = parse_unit(total_read_match.group(1))
            parsed_result['total_read'] = { 'value': value, 'unit': unit }
        
        # Extracing socket errors
        socket_errors_match = re.search(r'Socket errors: connect (\d+), read (\d+), write (\d+), timeout (\d+)', result)
        if socket_errors_match:
            parsed_result['socket_errors'] = {
                'connect': int(socket_errors_match.group(1)),
                'read': int(socket_errors_match.group(2)),
                'write': int(socket_errors_match.group(3)),
                'timeout': int(socket_errors_match.group(4))
            }

        # Extracting requests/sec
        requests_sec_match = re.search(r'Requests/sec:\s+(\S+)', result)
        if requests_sec_match:
            parsed_result['requests_per_sec'] = float(requests_sec_match.group(1))

        # Extracting transfer/sec
        transfer_match = re.search(r'Transfer/sec:\s+(\S+)', result)
        if transfer_match:
            value, unit = parse_unit(transfer_match.group(1))
            parsed_result['transfer_per_sec'] = { 'value': value, 'unit': unit }

        json_result = json.dumps(parsed_result)
        return json_result
    except FileNotFoundError:
        print("File not found!")
        sys.exit(1)

def parse_unit(value):
    # Regular expression to match the number and the unit
    pattern = r"([0-9]*\.?[0-9]+)([%a-zA-Z]+)"

    # Perform the matching
    match = re.match(pattern, value)

    if match:
        # Extract the number and unit
        number = float(match.group(1))
        unit = match.group(2)

        return number, unit
    else:
        print(f"No match found for value {value}!")
        sys.exit(1)

def main():
  result_file = sys.argv[1]
  result = parse_wrk_result(result_file)
  print(result)

if __name__ == '__main__':
  main()