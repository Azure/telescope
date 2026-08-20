# Renders a vmagent scrape-config ConfigMap from a list of ScrapeTarget
# declarations -- mirrors aks-operator's per-team scrape_configs.k renderer
# (one declarative model -> generated YAML), generalized for any v2 benchmark.
# Prototype only: no ADX export, no pipeline wiring yet.

import yaml
import .scrape_target as st

_labelMetaName = lambda key: str -> str {
    "__meta_kubernetes_pod_label_${key}".replace("-", "_").replace(".", "_")
}

_relabelConfigsFor = lambda t: st.ScrapeTarget -> [any] {
    labelConfigs = [
        {
            source_labels = [_labelMetaName(k)]
            regex = v
            action = "keep"
        }
        for k, v in t.podLabelSelector
    ]
    containerConfig = [{
        source_labels = ["__meta_kubernetes_pod_container_name"]
        regex = t.containerName
        action = "keep"
    }] if t.containerName else []
    addressConfigs = [
        {
            source_labels = ["__meta_kubernetes_pod_ip"]
            target_label = "__address__"
            replacement = "$1:${t.port}"
        },
        {
            source_labels = ["__address__"]
            target_label = "instance"
        },
    ]
    labelConfigs + containerConfig + addressConfigs
}

_metricRelabelConfigsFor = lambda t: st.ScrapeTarget -> [any] {
    [{
        action = "keep"
        regex = "|".join(t.metricNameKeep)
        source_labels = ["__name__"]
    }] if t.metricNameKeep else []
}

_jobFor = lambda t: st.ScrapeTarget, apiServer: str -> any {
    job = {
        job_name = t.jobName
        metrics_path = t.metricsPath
        kubernetes_sd_configs = [{
            role = "pod"
            api_server = apiServer
            namespaces = {names = [t.namespace]}
        }]
        relabel_configs = _relabelConfigsFor(t)
    }
    metricRelabel = _metricRelabelConfigsFor(t)
    job | {metric_relabel_configs = metricRelabel} if metricRelabel else job
}

# RenderScrapeConfig builds a vmagent-compatible scrape-config ConfigMap YAML
# from a list of ScrapeTarget declarations.
RenderScrapeConfig = lambda targets: [st.ScrapeTarget], apiServer: str, configMapName: str = "vmagent-scrape-config", namespace: str = "default" -> str {
    promConfig = {
        global = {scrape_interval = "30s", scrape_timeout = "10s"}
        scrape_configs = [_jobFor(t, apiServer) for t in targets]
    }
    cm = {
        apiVersion = "v1"
        kind = "ConfigMap"
        metadata = {name = configMapName, namespace = namespace}
        data = {"prometheus.yml" = yaml.encode(promConfig)}
    }
    yaml.encode(cm)
}
