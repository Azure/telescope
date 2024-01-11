import sys
import json

def parse_tcp_output(stdout):
  data = json.loads(stdout)
  start = data.get('start', {})
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
    'throughput': sender.get('bits_per_second'),
    'retransmits': sender.get('retransmits'),
    'max_rtt': sender.get('max_rtt'),
    'min_rtt': sender.get('min_rtt'),
    'mean_rtt': sender.get('mean_rtt'),
    'cpu_usage_client': cpu_utilization_percent.get('host_total'),
    'cpu_usage_server': cpu_utilization_percent.get('remote_total'),
  }


def parse_udp_output(stdout):
  data = json.loads(stdout)
  end = data.get('end', {})
  sum = end.get('sum', {})
  cpu_utilization_percent = end.get('cpu_utilization_percent', {})

  return {
    'throughput': sum.get('bits_per_second'),
    'jitter_ms': sum.get('jitter_ms'),
    'lost_packets': sum.get('lost_packets'),
    'total_packets': sum.get('packets'),
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