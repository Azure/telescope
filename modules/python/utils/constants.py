from dataclasses import dataclass


@dataclass(frozen=True)
class UrlConstants:
    NVIDIA_GPU_DEVICE_PLUGIN_YAML = "https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.17.1/deployments/static/nvidia-device-plugin.yml"
    NVIDIA_HELM_REPO_URL = "https://helm.ngc.nvidia.com/nvidia"
    EKS_CHARTS_REPO_URL = "https://aws.github.io/eks-charts"
