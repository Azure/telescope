import sys
import json
import pandas as pd
import numpy as np

COLUMN_NAMES = ["timeStamp", "elapsed", "label", "responseCode", "responseMessage",
                "threadName", "dataType", "success", "failureMessage", "bytes",
                "sentBytes", "grpThreads", "allThreads", "URL", "Latency", "IdleTime", "Connect"]

def parse_jmeter_output(result_file):
  try:
    result = pd.read_csv(result_file)
    if len(result) == 0:
      return "No data to process!"

    for column in COLUMN_NAMES:
      if column not in result.columns:
        return f"Missing column: {column}"

    result['newLatency'] = result['elapsed'] - result['Connect']

    total_samples = result.shape[0]
    average = result['newLatency'].mean()
    median = result['newLatency'].median()
    percentile_90 = result['newLatency'].quantile(0.9)
    percentile_95 = result['newLatency'].quantile(0.95)
    percentile_99 = result['newLatency'].quantile(0.99)
    min = result['newLatency'].min()
    max = result['newLatency'].max()
    std = result['newLatency'].std()

    error_rate = sum(~result['success']) / total_samples * 100
    errors = result[~result['success']][['responseCode','responseMessage']].drop_duplicates().to_dict(orient='records')

    duration_in_seconds = (result['timeStamp'].max() - result['timeStamp'].min()) / 1000
    received_in_kb = sum(result['bytes']) / 1000
    received_kbs = received_in_kb / duration_in_seconds
    throughput = total_samples / duration_in_seconds

    data = {
      "# Samples": total_samples,
      "Average": average,
      "Median": median,
      "90% Line": percentile_90,
      "95% Line": percentile_95,
      "99% Line": percentile_99,
      "Min": min,
      "Max": max,
      "Std. Dev.": std,
      "Error %": error_rate,
      "Throughput": throughput,
      "Received KB/sec": received_kbs,
      "Errors": errors,
    }

    for key in data:
      if isinstance(data[key], np.int64):
        data[key] = int(data[key])
      elif isinstance(data[key], np.float64):
        data[key] = float(round(data[key], 2))
    
    json_result = json.dumps(data)
    return json_result
  except pd.errors.EmptyDataError as e:
    return "Empty file!"

def main():
  result_file = sys.argv[1]
  result = parse_jmeter_output(result_file)
  print(result)

if __name__ == '__main__':
  main()