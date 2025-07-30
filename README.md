[![Terraform Validation](https://github.com/Azure/telescope/actions/workflows/terraform-validation.yml/badge.svg)](https://github.com/Azure/telescope/actions/workflows/terraform-validation.yml) [![Python Validation](https://github.com/Azure/telescope/actions/workflows/python-validation.yml/badge.svg)](https://github.com/Azure/telescope/actions/workflows/python-validation.yml) [![YAML Validation](https://github.com/Azure/telescope/actions/workflows/yaml-validation.yml/badge.svg)](https://github.com/Azure/telescope/actions/workflows/yaml-validation.yml) [![Security Scan](https://github.com/Azure/telescope/actions/workflows/security-scan.yml/badge.svg)](https://github.com/Azure/telescope/actions/workflows/security-scan.yml)

# Telescope

Telescope is a cloud-native framework designed to benchmark and compare cloud products and services, with a focus on scalability and performance. It empowers users to make informed, data-driven decisions for multi-cloud strategies across Azure, AWS, and GCP.

The currently supported Kubernetes-based test scenarios are:
1. [API Server & ETCD Benchmark](pipelines/perf-eval/API%20Server%20Benchmark)
2. [Scheduler & Controller Benchmark](pipelines/perf-eval/Scheduler%20Benchmark)
3. [Autoscaler/Karpenter Benchmark](pipelines/perf-eval/Autoscale%20Benchmark)
4. [Container Network Benchmark](pipelines/perf-eval/CNI%20Benchmark)
5. [Container Storage Benchmark](pipelines/perf-eval/CSI%20Benchmark/)
6. [Container Runtime Benchmark](pipelines/perf-eval/CRI%20Benchmark/)
7. [GPU/HPC Benchmark](pipelines/perf-eval/GPU%20Benchmark)

The currently integrated open-source testing tools are:
1. [kperf](https://github.com/Azure/kperf/pkgs/container/kperf)
2. [kwok](https://github.com/kubernetes-sigs/kwok)
3. [clusterloader2](https://github.com/kubernetes/perf-tests/blob/master/clusterloader2/)
4. [resource-comsumer](https://github.com/kubernetes/kubernetes/blob/master/test/images/resource-consumer/README.md)
5. [iperf](https://github.com/esnet/iperf)
6. [fio](https://github.com/axboe/fio)

## Design

[Read more](docs/design.md)

## Contributing

[Read more](docs/contribute.md)
<!-- markdown-link-check-disable -->
This project welcomes contributions and suggestions.  Most contributions require you to agree to a
Contributor License Agreement (CLA) declaring that you have the right to, and actually do, grant us
the rights to use your contribution. For details, visit <https://cla.opensource.microsoft.com>.

When you submit a pull request, a CLA bot will automatically determine whether you need to provide
a CLA and decorate the PR appropriately (e.g., status check, comment). Simply follow the instructions
provided by the bot. You will only need to do this once across all repos using our CLA.

This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/).
For more information see the [Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/) or
contact [opencode@microsoft.com](mailto:opencode@microsoft.com) with any additional questions or comments.

## Trademarks

This project may contain trademarks or logos for projects, products, or services. Authorized use of Microsoft
trademarks or logos is subject to and must follow [Microsoft's Trademark & Brand Guidelines](https://www.microsoft.com/legal/intellectualproperty/trademarks/usage/general).
Use of Microsoft trademarks or logos in modified versions of this project must not cause confusion or imply Microsoft sponsorship.
Any use of third-party trademarks or logos are subject to those third-party's policies.

## License

See [LICENSE](LICENSE).

## Code of Conduct

This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/). For more information see the [Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/) or contact [opencode@microsoft.com](mailto:opencode@microsoft.com) with any additional questions or comments.