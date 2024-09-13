#!/bin/bash
set -e

aws eks --region us-east-2 update-kubeconfig --name "${EKS_CLUSTER_NAME}"
# Install Karpenter
helm upgrade --install karpenter oci://public.ecr.aws/karpenter/karpenter \
  --version "1.0.1" \
  --namespace "kube-system" \
  --set "settings.clusterName=${EKS_CLUSTER_NAME}" \
  --set controller.resources.requests.cpu=1 \
  --set controller.resources.requests.memory=1Gi \
  --set controller.resources.limits.cpu=1 \
  --set controller.resources.limits.memory=1Gi \
  --set replicas=1 \
  --wait