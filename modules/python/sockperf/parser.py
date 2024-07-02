import sys
import json
import re

def parse_sockperf_tcp_result(result_file, indent = None):
  try:
    file = open(result_file, 'r')
    result = file.read()
    file.close()
    
    if not result:
        print("No data to process!")
        sys.exit(1)
    
    parsed_result = {}
    parsed_result['raw'] = result

    # Parse SentMessages
    send_messages = re.search(r'SentMessages=(.+);', result)

    # Parse Rtt and std-dev Rtt
    rtt = re.search(r'> avg-rtt=(.+) ', result)
    rtt_std = re.search(r' \(std-dev=(.+)\)', result)
    if rtt:
        parsed_result['rtt'] = rtt.group(1)
    if rtt_std:
        parsed_result['rtt_std'] = rtt_std.group(1)

    # Parse percentiles
    #Total 203820 observations; each percentile contains 2038.20 observations
    percentiles_match = re.search(r' each percentile contains (.+) observations\n(.+?)<MIN>', result, re.DOTALL)
    if percentiles_match:
        percentiles_values = []
        # parsed_result["test123"] = percentiles_match.group(2)
        lines = percentiles_match.group(2).strip().split('\n')  # Skip the header line
        for line in lines:
            # <MAX> observation = 9229.894
            #max_match = re.search(r'MAX(.+)', line.strip())

            max_match = re.search(r' <MAX> observation = (.+)', line.strip())
            if max_match:
                percentiles_values.append({
                    "SamplingType": "MAX",
                    "Duration": float(max_match.group(1))
                })
            else:
                not_max_match = re.search(r'sockperf: ---> percentile (.+) =  (.+)', line.strip())
                if not_max_match:
                    percentiles_values.append({
                        "SamplingType": not_max_match.group(1),
                        "Duration": float(not_max_match.group(2))
                    })
        parsed_result['percentiles'] = percentiles_values

    # Convert to JSON
    parsed_json = json.dumps(parsed_result, indent=indent)

    return parsed_json
    
  except FileNotFoundError:
    print("File not found!")
    sys.exit(1)


def parse_sockperf_udp_result(result_file):
    print("Implement later")
    parsed_result = {}
    return parsed_result

def main():
  protocol = sys.argv[1]
  fileName = sys.argv[2]

  if protocol == 'tcp' or protocol == 'TCP':
    result = parse_sockperf_tcp_result(fileName)
  else:
    result = parse_sockperf_udp_result(fileName)
  print(result)

if __name__ == '__main__':
  main()
