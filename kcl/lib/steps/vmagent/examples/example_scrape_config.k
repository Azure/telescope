# Prototype: exercise the vmagent ScrapeTarget schema + renderer against a
# couple of example targets (mirrors what a real benchmark's pipeline.k would
# declare). Run with:
#   kcl run kcl/lib/steps/vmagent/examples/example_scrape_config.k

import lib.steps.vmagent.scrape_target as st
import lib.steps.vmagent.scrape_config as sc

_targets = [
    st.ScrapeTarget {
        jobName = "workload-metrics"
        namespace = "benchmark-ns"
        podLabelSelector = {app = "my-benchmark-workload"}
        port = 9100
    }
    st.ScrapeTarget {
        jobName = "sidecar-metrics"
        namespace = "benchmark-ns"
        podLabelSelector = {app = "my-benchmark-workload"}
        containerName = "sidecar"
        port = 9200
        metricsPath = "/custom-metrics"
        metricNameKeep = ["request_duration_seconds_.*", "requests_total"]
    }
]

output = sc.RenderScrapeConfig(
    _targets,
    apiServer = "https://example-dp-api-server:443",
    configMapName = "example-scrape-config",
    namespace = "benchmark-ns",
)
