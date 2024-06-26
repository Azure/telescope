import sys
import json
import re

def parse_ncps_result(result_file, indent = None):
  try:
    file = open(result_file, 'r')
    result = file.read()
    file.close()
    
    if not result:
        print("No data to process!")
        sys.exit(1)
    
    parsed_result = {}

    # Parse CMDLINE and VERSION
    cmdline_match = re.search(r'=== CMDLINE: (.+)', result)
    version_match = re.search(r'=== VERSION (.+)', result)
    if cmdline_match:
        parsed_result['cmd'] = cmdline_match.group(1)
        thread_match = re.search(r'-r (\d+)', cmdline_match.group(1))
        if thread_match:
            parsed_result['thread_count'] = int(thread_match.group(1))
    if version_match:
        parsed_result['version'] = version_match.group(1)

    # Parse RXGBPS and TXGBPS
    rxgbps_match = re.search(r'###RXGBPS (.+)', result)
    if rxgbps_match:
        parsed_result['recevied'] = { "value": float(rxgbps_match.group(1)), "unit" : "Gbps" }
    txgbps_match = re.search(r'###TXGBPS (.+)', result)
    if txgbps_match:
        parsed_result['sent'] = { "value": float(txgbps_match.group(1)), "unit" : "Gbps" }

    # Parse connection establishment times
    connection_times_match = re.search(r'=== Time \(ms\) to Nth connection establishment for first \d+ connections:\n(.+?)\n\n', result, re.DOTALL)
    if connection_times_match:
        connection_times = []
        lines = connection_times_match.group(1).strip().split('\n')[1:]  # Skip the header line
        for line in lines:
            parts = re.split(r'\s+', line.strip())
            connection_times.append({
                'N': int(parts[1]),
                'T(ms)': int(parts[2]),
                'CPS': int(parts[3])
            })
        parsed_result['connection_times'] = connection_times

    # Parse end CPS
    end_cps_match = re.search(r'###ENDCPS (\d+)', result)
    if end_cps_match:
        parsed_result['cps'] = int(end_cps_match.group(1))

    # Parse SYN RTT statistics
    syn_rtt_match = re.search(r'=== SYN RTT \(us\) stats for first \d+ connections:\n(.+?)\n\n', result, re.DOTALL)
    if syn_rtt_match:
        syn_rtt_stats = {}
        lines = syn_rtt_match.group(1).strip().split('\n')
        headers = re.split(r'\s+', lines[0].strip())[1:]
        values = re.split(r'\s+', lines[1].strip())[1:]
        for header, value in zip(headers, values):
            syn_rtt_stats[header] = int(value)
        parsed_result['synrtt'] = syn_rtt_stats

    # Parse retransmit stats
    retransmit_match = re.search(r'^###REXMIT.*$', result, re.MULTILINE)
    if retransmit_match:
      values = retransmit_match.group(0).split(",")[1:]
      for value in values:
        key, val = value.split(":")
        parsed_result[key] = float(val)

    # Convert to JSON
    parsed_json = json.dumps(parsed_result, indent=indent)

    return parsed_json
    
  except FileNotFoundError:
    print("File not found!")
    sys.exit(1)

def main():
  result_file = sys.argv[1]
  result = parse_ncps_result(result_file)
  print(result)

if __name__ == '__main__':
  main()
