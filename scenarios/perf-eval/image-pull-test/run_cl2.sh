#!/bin/bash
#
# Run ClusterLoader2 image-pull test
#

set -e

if [ -z "$ROOT_DIR" ]; then
    echo "Error: ROOT_DIR is not set. Please run the setup cell first."
    exit 1
fi

# Install docker for root (required for sudo access to docker socket)
echo "Ensuring 'docker' library is installed for root..."
sudo python3 -m pip install docker >/dev/null 2>&1

export KUBECONFIG_PATH=${KUBECONFIG:-$HOME/.kube/config}
export PYTHONPATH="$ROOT_DIR/modules/python:$PYTHONPATH"

sudo -E PYTHONPATH="$PYTHONPATH" python3 -m clusterloader2.image_pull.run_test \
    --kubeconfig "$KUBECONFIG_PATH" \
    --root-dir "$ROOT_DIR" \
    --scenario "image-pull-test" \
    --cl2-image "ghcr.io/azure/clusterloader2:v20250311" \
    --prometheus-memory "2Gi" \
    --storage-provisioner "kubernetes.io/azure-disk" \
    --storage-volume-type "StandardSSD_LRS"

exit $?
