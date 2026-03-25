from dataclasses import dataclass


@dataclass(frozen=True)
class CommandConstants:
    NETSTAT_CMD = "netstat -s -u | jq -R -s 'split(\"\n\")'"
    LSCPU_CMD = "lscpu --json"
    LSPCI_CMD = "lspci && lsb_release -a"
    IPERF3_VERSION_CMD = "iperf3 --version"
    IP_LINK_CMD = "ip -j -s link show"


@dataclass(frozen=True)
class UrlConstants:
    NVIDIA_GPU_DEVICE_PLUGIN_YAML = "https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.17.1/deployments/static/nvidia-device-plugin.yml"
    NVIDIA_HELM_REPO_URL = "https://helm.ngc.nvidia.com/nvidia"
    EKS_CHARTS_REPO_URL = "https://aws.github.io/eks-charts"

@dataclass(frozen=True)
class AzureSKUFamily:
    # VM Size to SKU Family mapping
    VM_SIZE_TO_SKU_FAMILY = {
        "Standard_ND96asr_v4": "ndv4"
    }
