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
    NVIDIA_GPU_DEVICE_PLUGIN_YAML = "https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.17.3/nvidia-device-plugin.yml"
