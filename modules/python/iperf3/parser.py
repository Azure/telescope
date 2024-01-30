import sys
import json
from datetime import datetime

def convert_timestamp(epoch):
  dt = datetime.utcfromtimestamp(epoch)
  utc_str = dt.strftime('%Y-%m-%dT%H:%M:%SZ')
  return utc_str

def parse_tcp_output(stdout):
  data = json.loads(stdout)
  start = data.get('start', {})
  timestamp = start.get('timestamp', {})
  test_start = start.get('test_start', {})
  num_streams = test_start.get('num_streams')
  # TODO: handle multiple streams
  assert num_streams == 1
  end = data.get('end', {})
  streams = end.get('streams', {})
  stream = streams[0]
  sender = stream.get('sender', {})
  cpu_utilization_percent = end.get('cpu_utilization_percent', {})

  return {
    'timestamp': convert_timestamp(timestamp.get('timesecs')),
    'total_throughput': sender.get('bits_per_second') / 1000000,
    'retransmits': sender.get('retransmits'),
    'max_rtt': sender.get('max_rtt'),
    'min_rtt': sender.get('min_rtt'),
    'rtt': sender.get('mean_rtt'),
    'rtt_unit': 'us',
    'cpu_usage_client': cpu_utilization_percent.get('host_total'),
    'cpu_usage_server': cpu_utilization_percent.get('remote_total'),
  }


def parse_udp_output(stdout):
  data = json.loads(stdout)
  start = data.get('start', {})
  timestamp = start.get('timestamp', {})
  end = data.get('end', {})
  sum = end.get('sum', {})
  cpu_utilization_percent = end.get('cpu_utilization_percent', {})

  return {
    'timestamp': convert_timestamp(timestamp.get('timesecs')),
    'total_throughput': sum.get('bits_per_second') / 1000000,
    'jitter': sum.get('jitter_ms'),
    'jitter_unit': 'ms',
    'lost_datagrams': sum.get('lost_packets'),
    'total_datagrams': sum.get('packets'),
    'lost_percent': sum.get('lost_percent'),
    'cpu_usage_client': cpu_utilization_percent.get('host_total'),
    'cpu_usage_server': cpu_utilization_percent.get('remote_total'),
  }

def main():
  protocol = sys.argv[1]
  fileName = sys.argv[2]
  file = open(fileName, 'r')
  stdout = file.read()
  file.close()

  if protocol == 'tcp':
    metadata = parse_tcp_output(stdout)
  else:
    metadata = parse_udp_output(stdout)
  result = json.dumps(metadata)
  print(result)

if __name__ == '__main__':
  main()
