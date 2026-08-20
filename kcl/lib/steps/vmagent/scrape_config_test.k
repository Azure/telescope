import .scrape_target as st
import .scrape_config as sc

test_single_target_renders_job = lambda {
    """A single ScrapeTarget should render one scrape_configs job with the
    right name, path, pod-label keep filter, and address construction."""
    targets = [st.ScrapeTarget {
        jobName = "workload-metrics"
        namespace = "benchmark-ns"
        podLabelSelector = {app = "my-benchmark-workload"}
        port = 9100
    }]
    out = sc.RenderScrapeConfig(targets, apiServer = "https://api:443", namespace = "benchmark-ns")
    assert "job_name: workload-metrics" in out
    assert "metrics_path: /metrics" in out
    assert "__meta_kubernetes_pod_label_app" in out
    assert "regex: my-benchmark-workload" in out
    assert "replacement: $1:9100" in out
    assert "metric_relabel_configs" not in out
}

test_container_filter_adds_relabel_rule = lambda {
    """containerName, when set, should add a container-name keep rule."""
    targets = [st.ScrapeTarget {
        jobName = "sidecar-metrics"
        namespace = "benchmark-ns"
        containerName = "sidecar"
        port = 9200
    }]
    out = sc.RenderScrapeConfig(targets, apiServer = "https://api:443")
    assert "__meta_kubernetes_pod_container_name" in out
    assert "regex: sidecar" in out
}

test_metric_name_keep_produces_metric_relabel_configs = lambda {
    """metricNameKeep, when set, should produce a metric_relabel_configs
    keep rule joining all entries with |."""
    targets = [st.ScrapeTarget {
        jobName = "filtered-metrics"
        namespace = "benchmark-ns"
        port = 9300
        metricNameKeep = ["requests_total", "errors_total"]
    }]
    out = sc.RenderScrapeConfig(targets, apiServer = "https://api:443")
    assert "metric_relabel_configs" in out
    assert "regex: requests_total|errors_total" in out
}

test_multiple_targets_render_multiple_jobs = lambda {
    """Each ScrapeTarget should produce its own independent scrape_configs entry."""
    targets = [
        st.ScrapeTarget {jobName = "job-a", namespace = "ns", port = 9100}
        st.ScrapeTarget {jobName = "job-b", namespace = "ns", port = 9200}
    ]
    out = sc.RenderScrapeConfig(targets, apiServer = "https://api:443")
    assert "job_name: job-a" in out
    assert "job_name: job-b" in out
}
