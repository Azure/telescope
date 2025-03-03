# High Pod Startup Latency SLO Investigation

# Overview

- This SLO is measured using Kubernetes metric [kubelet_pod_start_sli_duration_seconds](https://kubernetes.io/docs/reference/instrumentation/metrics/), which measures the duration in seconds to start a pod, **excluding time to pull images and run init containers**, measured from pod creation timestamp to when all its containers are reported as started and observed via watch.
- To satisfy the SLO, the 99th percentile per cluster-day of this Pod Startup Latency must remain **<=5 seconds**. However, [Telescope data](https://kusto.azure.com/dashboards/5affe683-1995-4673-a299-237c2d4ac6ea?p-_startTime=2days&p-_endTime=now&p-_maxPods=v-110&p-_kubeletMetric=v-KubeletPodStartupSLIDuration&p-_loadType=v-memory#7674a8e0-2acb-4be2-bc7b-61dba1cf7a01) is showing this SLO hasn't been satisfied and AKS performance is 5x worse than EKS performance.

## Identified bottlenecks:

1. Default daemonsets' pod startup latency skews P99 latency
2. CNI performance issue: HostNetwork set to True is significantly better than HostNetwork set to False
3. Ephemeral disk is better than Managed disk
4. Parallel pull feature in k8s 1.31 version by default

# Detailed Investigation

## Test setup

- Test is run with 3 different **max-pods** settings of 30, 70, 110 pods per node:

| Cloud | Max Pods | Default Daemonset Pod Count | Workload Pod Count | Total Pod Count |
|-------|----------|-----------------------------|--------------------|-----------------|
| AKS   | 30       | 6                           | 24                 | 30              |
| AWS   | 30       | 2                           | 28                 | 30              |
| AKS   | 70       | 6                           | 64                 | 70              |
| AWS   | 70       | 2                           | 68                 | 70              |
| AKS   | 110      | 6                           | 104                | 110             |
| AWS   | 110      | 2                           | 108                | 110             |

- In our deployment, there is **NO** `initContainers` and `imagePullPolicy` is set to `IfNotPresent`.
- Comparision matrix:

| Cloud | K8s Version | VM Size           | Disk Type | VM OS       | Parallel pull enabled |
|-------|-------------|-------------------|-----------|-------------|-----------------------|
| AWS   | 1.31        | m5.4xlarge        | EBS       | AzureLinux2 | True                  |
| AKS   | 1.30        | Standard_D16_v3   | Managed   | Linux       | False                 |
| AKS   | 1.31        | Standard_D16_v3   | Managed   | Linux       | True                  |
| AKS   | 1.30        | Standard_D16ds_v4 | Ephemeral | Linux       | False                 |
| AKS   | 1.31        | Standard_D16ds_v4 | Ephemeral | Linux       | True                  |
| AKS   | 1.31        | Standard_D16ds_v4 | Ephemeral | Linux       | False                 |
- Our workload pool has a total of **10 nodes**, and there's a separate pool for system pods so results won't get influenced by system workloads.

## Bottleneck 1: Default daemonsets' pod startup latency skews P99 latency (Resolved)

- The metric **kubelet_pod_start_sli_duration_seconds** takes into account all pods in a node, including daemonsets, so there's currently not an easy way to look at pod startup latency of just workload pod only. 
- Oddly, on Azure, the pod startup latency of daemonset pods are outrageously high

```bash
root@aks-userpool0-40776863-vmss000001:/var/log# cat messages | grep pod_startup_latency_tracker
Feb 26 16:14:44 aks-userpool0-40776863-vmss000001 kubelet[3270]: I0226 16:14:44.120921    3270 pod_startup_latency_tracker.go:104] "Observed pod startup duration" pod="kube-system/csi-azuredisk-node-gkzz5" podStartSLOduration=46.120908806 podStartE2EDuration="46.120908806s" podCreationTimestamp="2025-02-26 16:13:58 +0000 UTC" firstStartedPulling="0001-01-01 00:00:00 +0000 UTC" lastFinishedPulling="0001-01-01 00:00:00 +0000 UTC" observedRunningTime="2025-02-26 16:14:44.120755608 +0000 UTC m=+80.216506551" watchObservedRunningTime="2025-02-26 16:14:44.120908806 +0000 UTC m=+80.216659949"
Feb 26 16:14:46 aks-userpool0-40776863-vmss000001 kubelet[3270]: I0226 16:14:46.112113    3270 pod_startup_latency_tracker.go:104] "Observed pod startup duration" pod="kube-system/kube-proxy-c9b74" podStartSLOduration=48.112095192 podStartE2EDuration="48.112095192s" podCreationTimestamp="2025-02-26 16:13:58 +0000 UTC" firstStartedPulling="0001-01-01 00:00:00 +0000 UTC" lastFinishedPulling="0001-01-01 00:00:00 +0000 UTC" observedRunningTime="2025-02-26 16:14:45.112131295 +0000 UTC m=+81.207882138" watchObservedRunningTime="2025-02-26 16:14:46.112095192 +0000 UTC m=+82.207846035"
Feb 26 16:14:48 aks-userpool0-40776863-vmss000001 kubelet[3270]: I0226 16:14:48.118048    3270 pod_startup_latency_tracker.go:104] "Observed pod startup duration" pod="kube-system/azure-cns-lrnkq" podStartSLOduration=50.118033733 podStartE2EDuration="50.118033733s" podCreationTimestamp="2025-02-26 16:13:58 +0000 UTC" firstStartedPulling="0001-01-01 00:00:00 +0000 UTC" lastFinishedPulling="0001-01-01 00:00:00 +0000 UTC" observedRunningTime="2025-02-26 16:14:48.117239941 +0000 UTC m=+84.212990884" watchObservedRunningTime="2025-02-26 16:14:48.118033733 +0000 UTC m=+84.213784676"
Feb 26 16:14:51 aks-userpool0-40776863-vmss000001 kubelet[3270]: I0226 16:14:51.124471    3270 pod_startup_latency_tracker.go:104] "Observed pod startup duration" pod="kube-system/csi-azurefile-node-r6t8m" podStartSLOduration=53.124460216 podStartE2EDuration="53.124460216s" podCreationTimestamp="2025-02-26 16:13:58 +0000 UTC" firstStartedPulling="0001-01-01 00:00:00 +0000 UTC" lastFinishedPulling="0001-01-01 00:00:00 +0000 UTC" observedRunningTime="2025-02-26 16:14:51.124318817 +0000 UTC m=+87.220069660" watchObservedRunningTime="2025-02-26 16:14:51.124460216 +0000 UTC m=+87.220211159"
Feb 26 16:14:53 aks-userpool0-40776863-vmss000001 kubelet[3270]: I0226 16:14:53.125659    3270 pod_startup_latency_tracker.go:104] "Observed pod startup duration" pod="kube-system/cloud-node-manager-2dq49" podStartSLOduration=55.125648638 podStartE2EDuration="55.125648638s" podCreationTimestamp="2025-02-26 16:13:58 +0000 UTC" firstStartedPulling="0001-01-01 00:00:00 +0000 UTC" lastFinishedPulling="0001-01-01 00:00:00 +0000 UTC" observedRunningTime="2025-02-26 16:14:53.125549939 +0000 UTC m=+89.221300882" watchObservedRunningTime="2025-02-26 16:14:53.125648638 +0000 UTC m=+89.221399581"
Feb 26 16:14:56 aks-userpool0-40776863-vmss000001 kubelet[3270]: I0226 16:14:56.130966    3270 pod_startup_latency_tracker.go:104] "Observed pod startup duration" pod="kube-system/azure-ip-masq-agent-nqw99" podStartSLOduration=58.130955645 podStartE2EDuration="58.130955645s" podCreationTimestamp="2025-02-26 16:13:58 +0000 UTC" firstStartedPulling="0001-01-01 00:00:00 +0000 UTC" lastFinishedPulling="0001-01-01 00:00:00 +0000 UTC" observedRunningTime="2025-02-26 16:14:56.130931345 +0000 UTC m=+92.226682188" watchObservedRunningTime="2025-02-26 16:14:56.130955645 +0000 UTC m=+92.226706488"
```
While on EKS, the pod startup latency of daemonsets are well within SLO

```bash
Feb 25 19:30:03 ip-10-0-189-158 kubelet: I0225 19:30:03.207570    4509 pod_startup_latency_tracker.go:104] "Observed pod startup duration" pod="kube-system/kube-proxy-vg4qp" podStartSLOduration=4.207509209 podStartE2EDuration="4.207509209s" podCreationTimestamp="2025-02-25 19:29:59 +0000 UTC" firstStartedPulling="0001-01-01 00:00:00 +0000 UTC" lastFinishedPulling="0001-01-01 00:00:00 +0000 UTC" observedRunningTime="2025-02-25 19:30:03.205667942 +0000 UTC m=+5.344912697" watchObservedRunningTime="2025-02-25 19:30:03.207509209 +0000 UTC m=+5.346753952"
Feb 25 19:30:12 ip-10-0-189-158 kubelet: I0225 19:30:12.230929    4509 pod_startup_latency_tracker.go:104] "Observed pod startup duration" pod="kube-system/aws-node-vw7c6" podStartSLOduration=2.471963941 podStartE2EDuration="13.230915126s" podCreationTimestamp="2025-02-25 19:29:59 +0000 UTC" firstStartedPulling="2025-02-25 19:30:00.84531012 +0000 UTC m=+2.984554843" lastFinishedPulling="2025-02-25 19:30:11.604261306 +0000 UTC m=+13.743506028" observedRunningTime="2025-02-25 19:30:12.230780261 +0000 UTC m=+14.370025005" watchObservedRunningTime="2025-02-25 19:30:12.230915126 +0000 UTC m=+14.370159852"
```

So, when looking into the P99 of test in which we deploy 110 pods per node, the P99 of 110 is 108 pods which will include daemonsets latency.

In a fresh node on Azure, daemonsets latency is already high

```
(env) alyssa@CPC-alyss-5IIXY:~/telescope$ kubectl get --raw /api/v1/nodes/aks-userpool0-40776863-vmss000001/proxy/metrics | grep kubelet_pod_start_sli
# HELP kubelet_pod_start_sli_duration_seconds [ALPHA] Duration in seconds to start a pod, excluding time to pull images and run init containers, measured from pod creation timestamp to when all its containers are reported as started and observed via watch
# TYPE kubelet_pod_start_sli_duration_seconds histogram
kubelet_pod_start_sli_duration_seconds_bucket{le="0.5"} 0
kubelet_pod_start_sli_duration_seconds_bucket{le="1"} 0
kubelet_pod_start_sli_duration_seconds_bucket{le="2"} 0
kubelet_pod_start_sli_duration_seconds_bucket{le="3"} 0
kubelet_pod_start_sli_duration_seconds_bucket{le="4"} 0
kubelet_pod_start_sli_duration_seconds_bucket{le="5"} 0
kubelet_pod_start_sli_duration_seconds_bucket{le="6"} 0
kubelet_pod_start_sli_duration_seconds_bucket{le="8"} 0
kubelet_pod_start_sli_duration_seconds_bucket{le="10"} 0
kubelet_pod_start_sli_duration_seconds_bucket{le="20"} 0
kubelet_pod_start_sli_duration_seconds_bucket{le="30"} 0
kubelet_pod_start_sli_duration_seconds_bucket{le="45"} 0
kubelet_pod_start_sli_duration_seconds_bucket{le="60"} 6
kubelet_pod_start_sli_duration_seconds_bucket{le="120"} 6
kubelet_pod_start_sli_duration_seconds_bucket{le="180"} 6
kubelet_pod_start_sli_duration_seconds_bucket{le="240"} 6
kubelet_pod_start_sli_duration_seconds_bucket{le="300"} 6
kubelet_pod_start_sli_duration_seconds_bucket{le="360"} 6
kubelet_pod_start_sli_duration_seconds_bucket{le="480"} 6
kubelet_pod_start_sli_duration_seconds_bucket{le="600"} 6
kubelet_pod_start_sli_duration_seconds_bucket{le="900"} 6
kubelet_pod_start_sli_duration_seconds_bucket{le="1200"} 6
kubelet_pod_start_sli_duration_seconds_bucket{le="1800"} 6
kubelet_pod_start_sli_duration_seconds_bucket{le="2700"} 6
kubelet_pod_start_sli_duration_seconds_bucket{le="3600"} 6
kubelet_pod_start_sli_duration_seconds_bucket{le="+Inf"} 6
kubelet_pod_start_sli_duration_seconds_sum 310.73210223
kubelet_pod_start_sli_duration_seconds_count 6
```

After running the test, the data looks like below
```
(env) alyssa@CPC-alyss-5IIXY:~/telescope$ kubectl get --raw /api/v1/nodes/aks-userpool0-40776863-vmss000001/proxy/metrics | grep kubelet_pod_start_sli
# HELP kubelet_pod_start_sli_duration_seconds [ALPHA] Duration in seconds to start a pod, excluding time to pull images and run init containers, measured from pod creation timestamp to when all its containers are reported as started and observed via watch
# TYPE kubelet_pod_start_sli_duration_seconds histogram
kubelet_pod_start_sli_duration_seconds_bucket{le="0.5"} 2
kubelet_pod_start_sli_duration_seconds_bucket{le="1"} 2
kubelet_pod_start_sli_duration_seconds_bucket{le="2"} 2
kubelet_pod_start_sli_duration_seconds_bucket{le="3"} 2
kubelet_pod_start_sli_duration_seconds_bucket{le="4"} 9
kubelet_pod_start_sli_duration_seconds_bucket{le="5"} 25
kubelet_pod_start_sli_duration_seconds_bucket{le="6"} 37
kubelet_pod_start_sli_duration_seconds_bucket{le="8"} 52
kubelet_pod_start_sli_duration_seconds_bucket{le="10"} 66
kubelet_pod_start_sli_duration_seconds_bucket{le="20"} 104
kubelet_pod_start_sli_duration_seconds_bucket{le="30"} 104
kubelet_pod_start_sli_duration_seconds_bucket{le="45"} 104
kubelet_pod_start_sli_duration_seconds_bucket{le="60"} 110
kubelet_pod_start_sli_duration_seconds_bucket{le="120"} 110
kubelet_pod_start_sli_duration_seconds_bucket{le="180"} 110
kubelet_pod_start_sli_duration_seconds_bucket{le="240"} 110
kubelet_pod_start_sli_duration_seconds_bucket{le="300"} 110
kubelet_pod_start_sli_duration_seconds_bucket{le="360"} 110
kubelet_pod_start_sli_duration_seconds_bucket{le="480"} 110
kubelet_pod_start_sli_duration_seconds_bucket{le="600"} 110
kubelet_pod_start_sli_duration_seconds_bucket{le="900"} 110
kubelet_pod_start_sli_duration_seconds_bucket{le="1200"} 110
kubelet_pod_start_sli_duration_seconds_bucket{le="1800"} 110
kubelet_pod_start_sli_duration_seconds_bucket{le="2700"} 110
kubelet_pod_start_sli_duration_seconds_bucket{le="3600"} 110
kubelet_pod_start_sli_duration_seconds_bucket{le="+Inf"} 110
kubelet_pod_start_sli_duration_seconds_sum -1.8446742887692856e+10
kubelet_pod_start_sli_duration_seconds_count 110
```

The actual P99 of just workload pods should be this range
```
kubelet_pod_start_sli_duration_seconds_bucket{le="10"} 66
kubelet_pod_start_sli_duration_seconds_bucket{le="20"} 104
```
But it ends up being this range
```
kubelet_pod_start_sli_duration_seconds_bucket{le="45"} 104
kubelet_pod_start_sli_duration_seconds_bucket{le="60"} 110
```

