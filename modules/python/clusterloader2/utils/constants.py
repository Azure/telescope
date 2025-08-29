POD_STARTUP_LATENCY_FILE_PREFIX_MEASUREMENT_MAP = {
    "PodStartupLatency_PodStartupLatency_"          : "PodStartupLatency_PodStartupLatency",
    "StatefulPodStartupLatency_PodStartupLatency_"  : "StatefulPodStartupLatency_PodStartupLatency",
    "StatelessPodStartupLatency_PodStartupLatency_" : "StatelessPodStartupLatency_PodStartupLatency",
}

NETWORK_METRIC_PREFIXES = ["APIResponsivenessPrometheus",
                           "InClusterNetworkLatency", 
                           "NetworkProgrammingLatency"]

PROM_QUERY_PREFIX = "GenericPrometheusQuery"

RESOURCE_USAGE_SUMMARY_PREFIX = "ResourceUsageSummary"

NETWORK_POLICY_SOAK_MEASUREMENT_PREFIX = "NetworkPolicySoakMeasurement"

JOB_LIFECYCLE_LATENCY_PREFIX = "JobLifecycleLatency"

SCHEDULING_THROUGHPUT_PROMETHEUS_PREFIX = "SchedulingThroughputPrometheus"

SCHEDULING_THROUGHPUT_PREFIX = "SchedulingThroughput"
