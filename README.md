# Telescope

Telescope is a performance evaluation framework designed for testing and comparing cloud products. The framework allows users to make data-driven decisions on their multi-cloud strategy and currently supports Azure and AWS, with GCP support coming soon.

## Achitecture
![arch](https://github.com/Azure/telescope/blob/main/docs/imgs/arch.png)
As the achitecture diagram above shows, Telescope streamlines the performance evaluation process in 5 steps:
1. Provision Resources
2. Validate Resources
3. Execute Tests
4. Cleanup Resources
5. Publish Results

and provides 3 major re-usable components:

* Terraform modules to manage target cloud resources
* Azure Pipeline to ochestrate and automate test runs
* Azure Blob Storage, Event Hub and Data Explorer for reporting

## Quick Start

## Usage

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