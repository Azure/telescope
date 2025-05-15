import json
from datetime import datetime, timezone
import numpy as np


def convert_timestamp(epoch):
    dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
    utc_str = dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    return utc_str


def parse_tcp_output(stdout):
    data = json.loads(stdout)
    start = data.get('start', {})
    timestamp = start.get('timestamp', {})
    intervals = data.get('intervals', {})
    stream_rtts = {}
    combined_rtts = []

    for interval in intervals:
        for stream_index, stream in enumerate(interval["streams"]):
            rtt = int(stream["rtt"])
            combined_rtts.append(rtt)

            if stream_index not in stream_rtts:
                stream_rtts[stream_index] = []
            stream_rtts[stream_index].append(rtt)

    combined_rtts_np = np.array(combined_rtts)
    p50 = float(np.percentile(combined_rtts_np, 50))

    p90_rtts = []
    p99_rtts = []
    max_rtts = []
    min_rtts = []
    mean_rtts = []
    for rtts in stream_rtts.values():
        rtts_np = np.array(rtts)
        p90_rtts.append(float(np.percentile(rtts_np, 90)))
        p99_rtts.append(float(np.percentile(rtts_np, 99)))
        max_rtts.append(int(np.max(rtts_np)))
        min_rtts.append(int(np.min(rtts_np)))
        mean_rtts.append(float(np.mean(rtts_np)))

    # Aggregate data from multiple streams in the 'end' section
    end = data.get('end', {})
    streams = end.get('streams', [])
    total_throughput = float(sum(stream.get('sender', {}).get(
        'bits_per_second', 0) for stream in streams) / 1000000)
    total_retransmits = int(sum(stream.get('sender', {}).get(
        'retransmits', 0) for stream in streams))

    cpu_utilization_percent = end.get('cpu_utilization_percent', {})

    return {
        'timestamp': convert_timestamp(timestamp.get('timesecs')),
        # Aggregated throughput
        'total_throughput': float(total_throughput),
        # Aggregated retransmits
        'retransmits': int(total_retransmits),
        # Overall p50 RTT across all streams
        'p50_rtt': float(p50),
        # Average of p90 per stream
        'p90_rtt': float(np.mean(p90_rtts)),
        # Average of p99 per stream
        'p99_rtt': float(np.mean(p99_rtts)),
        # Maximum of max RTT per stream
        'max_rtt': int(np.max(max_rtts)),
        # Minimum of min RTT per stream
        'min_rtt': int(np.min(min_rtts)),
        # Average mean RTT across streams
        'rtt': float(np.mean(mean_rtts)),
        'rtt_unit': 'us',
        'cpu_usage_client': cpu_utilization_percent.get('host_total'),
        'cpu_usage_server': cpu_utilization_percent.get('remote_total'),
    }


def parse_udp_output(stdout):
    data = json.loads(stdout)
    start = data.get('start', {})
    timestamp = start.get('timestamp', {})
    end = data.get('end', {})
    sum_value = end.get('sum', {})
    cpu_utilization_percent = end.get('cpu_utilization_percent', {})

    return {
        'timestamp': convert_timestamp(timestamp.get('timesecs')),
        'total_throughput': sum_value.get('bits_per_second') / 1000000,
        'jitter': sum_value.get('jitter_ms'),
        'jitter_unit': 'ms',
        'lost_datagrams': sum_value.get('lost_packets'),
        'total_datagrams': sum_value.get('packets'),
        'lost_percent': sum_value.get('lost_percent'),
        'cpu_usage_client': cpu_utilization_percent.get('host_total'),
        'cpu_usage_server': cpu_utilization_percent.get('remote_total'),
    }
