[![Terraform Validation](https://github.com/Azure/telescope/actions/workflows/terraform-validation.yml/badge.svg)](https://github.com/Azure/telescope/actions/workflows/terraform-validation.yml) [![Python Validation](https://github.com/Azure/telescope/actions/workflows/python-validation.yml/badge.svg)](https://github.com/Azure/telescope/actions/workflows/python-validation.yml) [![YAML Validation](https://github.com/Azure/telescope/actions/workflows/yaml-validation.yml/badge.svg)](https://github.com/Azure/telescope/actions/workflows/yaml-validation.yml) [![Security Scan](https://github.com/Azure/telescope/actions/workflows/security-scan.yml/badge.svg)](https://github.com/Azure/telescope/actions/workflows/security-scan.yml)

# Telescope

Telescope is a framework built to test and compare cloud products and services, focusing on evaluating scalability and performance. It enables users to make informed, data-driven decisions for their multi-cloud strategies. Currently, Telescope supports Azure and AWS, with plans to include GCP in the near future.

The currently available test scenarios are:
1. Kubernetes API server benchmark using [kperf](https://github.com/Azure/kperf/pkgs/container/kperf)
2. Kubernetes Autoscaling benchmark using [clusterloader2](https://github.com/kubernetes/perf-tests/blob/master/clusterloader2/)

with more coming soon.

## Design
![design](./docs/imgs/design.png)
As the achitecture diagram above shows, Telescope streamlines the evaluation process through five key steps:

1. Provision Resources
2. Validate Resources
3. Execute Tests
4. Cleanup Resources
5. Publish Results

Telescope offers three primary reusable components:

1. **Terraform modules** to manage test resource setup and provide reproducibility.
2. **Python modules** for seamless integration with testing and measurement tools.
3. **Azure services** including Pipeline, Blob Storage, Event Hub, and Data Explorer for continuous monitoring.

## Quick Start
1. Setup test framework by running commands as follows:
```bash
az login
aws configure

export AZDO_PERSONAL_ACCESS_TOKEN=<Azure DevOps Personal Access Token>
export AZDO_ORG_SERVICE_URL=https://dev.azure.com/<Azure DevOps Org Name>
export AZDO_GITHUB_SERVICE_CONNECTION_PAT=<GitHub Personal Access Token>
export TF_VAR_resource_group_name=<Resource Group Name>
export TF_VAR_storage_account_name=<Storage Account Name>
export TF_VAR_kusto_cluster_name=<Kusto Cluster Name>

cd modules/terraform/setup
make all
```

2. Run pipeline or wait for scheduled run on Azure DevOps
![pipeline](./docs/imgs/pipeline.jpeg)

3. Import [dashboard](./dashboards/example.json) and check test results on Azure Data Explorer
![results](./docs/imgs/results.jpeg)

## Contributing

[Read more](docs/contributing/readme.md)
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