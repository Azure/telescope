import sys
import re
import json

def parse_tcp_output(stdout):
  window_size_match = re.search(r'TCP window size: (?P<size>\d+\.?\d+) (?P<units>\S+)', stdout)
  window_size = float(window_size_match.group('size'))

  buffer_size_match = re.search(r'Write buffer size: (?P<buffer_size>\d+\.?\d+) \S+', stdout)
  buffer_size = float(buffer_size_match.group('buffer_size'))

  multi_thread = re.search(
    (
        r'\[SUM\]\s+\d+\.\d+-\d+\.\d+\s\w+\s+(?P<transfer>\d+)\s\w+\s+(?P<throughput>\d+)'
        r'\s\w+/\w+\s+(?P<write>\d+)/(?P<err>\d+)\s+(?P<retry>\d+)\s*'
    ),
    stdout,
  )

  if multi_thread:
    # Write, error, retry
    write = int(multi_thread.group('write'))
    err = int(multi_thread.group('err'))
    retry = int(multi_thread.group('retry'))
  else:
    # Write, error, retry
    match = re.search(
      r'\d+ Mbits/sec\s+(?P<write>\d+)/(?P<err>\d+)\s+(?P<retry>\d+)',
      stdout,
    )
    write = int(match.group('write'))
    err = int(match.group('err'))
    retry = int(match.group('retry'))

  r = re.compile(
      (
          r'\d+ Mbits\/sec\s+'
          r' \d+\/\d+\s+\d+\s+(?P<cwnd>-*\d+)(?P<cwnd_unit>\w+)\/(?P<rtt>\d+)'
          r'\s+(?P<rtt_unit>\w+)\s+(?P<netpwr>\d+\.\d+)'
      )
  )
  match = [m.groupdict() for m in r.finditer(stdout)]

  cwnd = sum(float(i['cwnd']) for i in match) / len(match)
  rtt = round(sum(float(i['rtt']) for i in match) / len(match), 2)
  netpwr = round(sum(float(i['netpwr']) for i in match) / len(match), 2)
  rtt_unit = match[0]['rtt_unit']

  thread_values = re.findall(r'\[SUM].*\s+(\d+\.?\d*).Mbits/sec', stdout)

  if not thread_values:
    thread_values = re.findall(
        r'\[.*\d+\].*\s+(\d+\.?\d*).Mbits/sec', stdout
    )

  total_throughput = sum(float(value) for value in thread_values)

  return {
    "total_throughput": total_throughput,
    "buffer_size": buffer_size,
    "tcp_window_size": window_size,
    "write_packet_count": write,
    "err_packet_count": err,
    "retry_packet_count": retry,
    "congestion_window": cwnd,
    "rtt": rtt,
    "rtt_unit": rtt_unit,
    "netpwr": netpwr,
  }


def parse_udp_output(stdout):
  match = re.search(r'UDP buffer size: (?P<buffer_size>\d+\.?\d+)\s+(?P<buffer_unit>\w+)', stdout)
  buffer_size = float(match.group('buffer_size'))
  datagram_size = int(re.findall(r'(?P<datagram_size>\d+)\sbyte\sdatagrams', stdout)[0])
  ipg_target = float(re.findall(r'IPG\starget:\s(\d+.?\d+)', stdout)[0])
  ipg_target_unit = str(re.findall(r'IPG\starget:\s\d+.?\d+\s(\S+)\s', stdout)[0])

  multi_thread = re.search(
      (
          r'\[SUM\]\s\d+\.?\d+-\d+\.?\d+\ssec\s+\d+\.?\d+\s+MBytes\s+\d+\.?\d+'
          r'\s+Mbits/sec\s+(?P<write>\d+)/(?P<err>\d+)\s+(?P<pps>\d+)\s+pps'
      ),
      stdout,
  )
  if multi_thread:
    # Write, Err, PPS
    write = int(multi_thread.group('write'))
    err = int(multi_thread.group('err'))
    pps = int(multi_thread.group('pps'))

  else:
    # Write, Err, PPS
    match = re.search(
        r'\d+\s+Mbits/sec\s+(?P<write>\d+)/(?P<err>\d+)\s+(?P<pps>\d+)\s+pps',
        stdout,
    )
    write = int(match.group('write'))
    err = int(match.group('err'))
    pps = int(match.group('pps'))

  # Jitter
  jitter_array = re.findall(r'Mbits/sec\s+(?P<jitter>\d+\.?\d+)\s+[a-zA-Z]+', stdout)
  jitter_avg = sum(float(x) for x in jitter_array) / len(jitter_array)

  jitter_unit = str(
      re.search(
          r'Mbits/sec\s+\d+\.?\d+\s+(?P<jitter_unit>[a-zA-Z]+)', stdout
      ).group('jitter_unit')
  )

  # Total and lost datagrams
  match = re.findall(
      r'(?P<lost_datagrams>\d+)/\s*(?P<total_datagrams>\d+)\s+\(', stdout
  )
  lost_datagrams_sum = sum(int(i[0]) for i in match)
  total_datagrams_sum = sum(int(i[1]) for i in match)

  # out of order datagrams
  out_of_order_array = re.findall(
      r'(\d+)\s+datagrams\sreceived\sout-of-order', stdout
  )
  out_of_order_sum = sum(int(x) for x in out_of_order_array)

  thread_values = re.findall(r'\[SUM].*\s+(\d+\.?\d*).Mbits/sec', stdout)
  if not thread_values:
    thread_values = re.findall(
        r'\[.*\d+\].*\s+(\d+\.?\d*).Mbits/sec\s+\d+/\d+', stdout
    )

  total_throughput = sum(float(value) for value in thread_values)

  return {
    "total_throughput": total_throughput,
    "buffer_size": buffer_size,
    "datagram_size_bytes": datagram_size,
    "write_packet_count": write,
    "err_packet_count": err,
    "pps": pps,
    "ipg_target": ipg_target,
    "ipg_target_unit": ipg_target_unit,
    "jitter": jitter_avg,
    "jitter_unit": jitter_unit,
    "lost_datagrams": lost_datagrams_sum,
    "total_datagrams": total_datagrams_sum,
    "out_of_order_datagrams": out_of_order_sum,
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