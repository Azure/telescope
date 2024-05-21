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
            parsed_result['duration'] = test_params_match.group(1)
            parsed_result['url'] = test_params_match.group(2)
            parsed_result['threads'] = int(test_params_match.group(3))
            parsed_result['connections'] = int(test_params_match.group(4))

        # Extracting thread stats
        latency_stats_match = re.search(r'Latency\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)', result)
        if latency_stats_match:
            parsed_result['latency_stats'] = {
                'avg': latency_stats_match.group(1),
                'stdev': latency_stats_match.group(2),
                'max': latency_stats_match.group(3),
                'percent_within_stdev': latency_stats_match.group(4)
            }
        req_sec_stats_match = re.search(r'Req/Sec\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)', result)
        if req_sec_stats_match:
            parsed_result['req_sec_stats'] = {
                'avg': req_sec_stats_match.group(1),
                'stdev': req_sec_stats_match.group(2),
                'max': req_sec_stats_match.group(3),
                'percent_within_stdev': req_sec_stats_match.group(4)
            }

        # Extracting latency distribution
        latency_distribution_match = re.search(r'Latency Distribution\n\s+50%\s+(\S+)\n\s+75%\s+(\S+)\n\s+90%\s+(\S+)\n\s+99%\s+(\S+)', result)
        if latency_distribution_match:
            parsed_result['latency_distribution'] = {
                '50th_percentile': latency_distribution_match.group(1),
                '75th_percentile': latency_distribution_match.group(2),
                '90th_percentile': latency_distribution_match.group(3),
                '99th_percentile': latency_distribution_match.group(4)
            }

        # Extracting total requests
        total_requests_match = re.search(r'(\d+) requests in', result)
        if total_requests_match:
            parsed_result['total_requests'] = int(total_requests_match.group(1))
        
        # Extracting requests/sec
        requests_sec_match = re.search(r'Requests/sec:\s+(\S+)', result)
        if requests_sec_match:
            parsed_result['requests_per_sec'] = float(requests_sec_match.group(1))

        # Extracting transfer/sec
        transfer_match = re.search(r'Transfer/sec:\s+(\S+)', result)
        if transfer_match:
            parsed_result['transfer_per_sec'] = transfer_match.group(1)

        json_result = json.dumps(parsed_result)
        return json_result
    except FileNotFoundError:
        print("File not found!")
        sys.exit(1)

def main():
  result_file = sys.argv[1]
  result = parse_wrk_result(result_file)
  print(result)

if __name__ == '__main__':
  main()