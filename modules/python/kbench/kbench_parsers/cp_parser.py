import re
import os
from os.path import join

KBENCH_LOGFILE = 'kbench.log'
KBENCH_CONFIG = 'config.json'

resources = [
    'pod',
    'deployment',
    'namespace',
    'service'
]

operations = [
    'create',
    'update',
    'list',
    'get',
    'delete'
]

MEAN_LABEL = 'mean'
MIN_LABEL = 'min'
MAX_LABEL = 'max'
P99_LABEL = 'p99'


def parse_test_results(results_dir, testname):
    res_stats = {}
    for root, _, files in os.walk(results_dir):
        if (root.endswith(testname) and len(files) > 0 and KBENCH_LOGFILE in files):
            logfile_path = join(root, KBENCH_LOGFILE)
            with open(logfile_path, 'r') as f:
                for line in f:
                    for res in resources:
                        for op in operations:
                            kpi = f'{op} {res} latency'
                            if kpi in line:
                                pattern = rf'(.*){kpi}:(\s+)(\d+.\d+)(\s+)(\d+.\d+)(\s+) (\d+.\d+)(\s+)(\d+.\d+)'
                                match = re.match(pattern, line)
                                if match:
                                    res_stats[f'{kpi} {MEAN_LABEL} (ms)'] = float(match.groups()[2])
                                    res_stats[f'{kpi} {MIN_LABEL} (ms)'] = float(match.groups()[4])
                                    res_stats[f'{kpi} {MAX_LABEL} (ms)'] = float(match.groups()[6])
                                    res_stats[f'{kpi} {P99_LABEL} (ms)'] = float(match.groups()[8])
            if KBENCH_CONFIG in files:
                config_path = join(root, KBENCH_CONFIG)
                with open(config_path, 'r') as f:
                    res_stats[f'{testname}_config_json'] = f.read()
            return res_stats
    return None
