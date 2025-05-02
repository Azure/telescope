# Overview

Telescope runs ADO pipelines with configured steps to benchmark kubernetes performance across:

- cloud providers: azure, gcp, aws
- managed kubernetes compoents: kubelet, api server, cni, etc

## Pipelines

The [pipelines](../pipelines/) orchestrate steps to run to conduct the benchmarking. The pipelines are to be run in Azure Devops (ADO) using ADO syntax.

## Scenarios

The [scenarios](../scenarios/) contains the scenarios for each test case, focusing on a particular setup. analogically each scenario is an e2e test case corresponding to `SCENARIO_NAME` used in the pipeline definition.

## Steps

The [steps](../steps/) folder contains reusable templates to be invoked from the pipeline. the steps are organized in a functional way, such as to setup/cleanup infrastructure, setup other resources / testing framework etc.

## Modules

The [modules](../modules/) contains the tailored code to be invoked from the steps. There are two main parts:

- python: python functions.
- terraform: cloud agnostic way to setup infrastructure

Python code is the entrypoint to other testing framework such as [clusterloader2](https://github.com/kubernetes/perf-tests/blob/master/clusterloader2/docs/GETTING_STARTED.md) and other handy tools such as [resource-consumer](https://github.com/kubernetes/kubernetes/blob/master/test/images/resource-consumer/README.md).

CL2 uses its own [template engine](https://github.com/kubernetes/perf-tests/blob/master/clusterloader2/README.md#object-template). For benchmarking purpose, the metrics is collected through prometheus and measurement defined by [PromQL](https://prometheus.io/docs/prometheus/latest/querying/operators/). There are CL2 [out of box measurements](https://github.com/kubernetes/perf-tests/blob/master/clusterloader2/README.md#Measurement) and customised [kubelet measurement](../modules/python/clusterloader2/cri/config/kubelet-measurement.yaml). The metrics to collect are [kubernetes metrics](https://kubernetes.io/docs/reference/instrumentation/metrics/) and the measurements are usually [SLOs](https://github.com/kubernetes/community/blob/master/sig-scalability/slos/slos.md) and other key performance [SLIs](https://kubernetes.io/docs/reference/instrumentation/slis/).

This is on top of other key system performance analysis and management, we can explore areas such as

- linux system performance analysis [golden signals](https://www.brendangregg.com/linuxperf.html)
- instrumentation / tooling (ebpf, system configuration, etc)
