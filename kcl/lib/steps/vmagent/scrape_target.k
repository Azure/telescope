# ScrapeTarget describes one vmagent scrape job for an arbitrary v2 benchmark's
# workload. Deliberately minimal (namespace + pod-label selector + port/path +
# optional metric-name allowlist) -- full scrape-config complexity (cadvisor-style
# label routing, konnectivity CONNECT proxying, per-tier regexes, etc.) stays
# specific to the vmagent-loadtest harness and is intentionally NOT reproduced
# here. See wiki/Telescope-V2-KCL-Vmagent-Observability-Design.md for the design.

schema ScrapeTarget:
    """One vmagent scrape job targeting pods in a benchmark's own namespace."""
    jobName: str
    namespace: str
    podLabelSelector: {str: str} = {}
    containerName: str = ""
    port: int
    metricsPath: str = "/metrics"
    metricNameKeep: [str] = []

    check:
        jobName != "", "ScrapeTarget.jobName must be set"
        namespace != "", "ScrapeTarget.namespace must be set"
        port > 0, "ScrapeTarget.port must be a positive port number"
