#!/bin/bash
source ./modules/bash/utils.sh

azure_run_attach_detach_test() {
  local resource_group=$1
  local aks_name=$2
  local disk_number=$3
  local storage_class_name=$4
  local result_dir=$5

  mkdir -p $result_dir

  az aks get-credentials -n $aks_name -g $resource_group
  curl -skSL https://raw.githubusercontent.com/Azure/kubernetes-volume-drivers/master/test/attach_detach_test.sh | bash -s $disk_number $storage_class_name $result_dir/attachdetach-${disk_number}.txt --
}

aws_run_attach_detach_test() {
  local region=$1
  local eks_name=$2
  local disk_number=$3
  local storage_class_name=$4
  local result_dir=$5

  mkdir -p $result_dir

  aws eks --region $region update-kubeconfig --name $eks_name
  echo "region=$region, eks_name=$eks_name, disk_number=$disk_number, storage_class_name=$storage_class_name, result_dir=$result_dir"
  aws_create_deletion_due_time_tag_storageclass $storage_class_name
  curl -skSL https://raw.githubusercontent.com/Azure/kubernetes-volume-drivers/master/test/attach_detach_test.sh | bash -s $disk_number $storage_class_name $result_dir/attachdetach-${disk_number}.txt --
}

aws_create_deletion_due_time_tag_storageclass() {
  local storage_class_name=$1
  deletion_due_time=$(date -u -d "+3 hour" +'%Y-%m-%dT%H:%M:%SZ')
  cat <<EOF | kubectl apply -f -
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: $storage_class_name
parameters:
  tagSpecification_1: "deletion_due_time=${deletion_due_time}"
  fsType: ext4
  type: gp2
provisioner: ebs.csi.aws.com
reclaimPolicy: Delete
volumeBindingMode: WaitForFirstConsumer
EOF
  echo "created storage class $storage_class_name with deletion_due_time tag"
}

collect_result_attach_detach() {
  local result_dir=$1
  local run_link=$2
  local disk_number=$3

  echo "collecting attach detach test results from $result_dir/attachdetach-${disk_number}.txt into $result_dir/results.json"

  result="$result_dir/attachdetach-${disk_number}.txt"
  echo "========= collecting ${result} ==========="
  cat $result

  pv_creation_p50=$(cat $result | grep 'pv creation p50' | cut -c 18-)
  pv_creation_p90=$(cat $result | grep 'pv creation p90' | cut -c 18-)
  pv_creation_p99=$(cat $result | grep 'pv creation p99' | cut -c 18-)
  attach_p50=$(cat $result | grep 'attach p50' | cut -c 13-)
  attach_p90=$(cat $result | grep 'attach p90' | cut -c 13-)
  attach_p99=$(cat $result | grep 'attach p99' | cut -c 13-)
  detach_p50=$(cat $result | grep 'detach p50' | cut -c 13-)
  detach_p90=$(cat $result | grep 'detach p90' | cut -c 13-)
  detach_p99=$(cat $result | grep 'detach p99' | cut -c 13-)

  data=$(jq --null-input \
    --arg timestamp "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
    --arg disk_number "$disk_number" \
    --arg location "$REGION" \
    --arg vm_size "$MACHINE_TYPE" \
    --arg run_url "$run_link" \
    --arg cloud "$CLOUD" \
    --arg case_name "$CASE_NAME" \
    --arg pv_creation_p50 "$pv_creation_p50" \
    --arg pv_creation_p90 "$pv_creation_p90" \
    --arg pv_creation_p99 "$pv_creation_p99" \
    --arg attach_p50 "$attach_p50" \
    --arg attach_p90 "$attach_p90" \
    --arg attach_p99 "$attach_p99" \
    --arg detach_p50 "$detach_p50" \
    --arg detach_p90 "$detach_p90" \
    --arg detach_p99 "$detach_p99" \
    '{
      timestamp: $timestamp,
      disk_number: $disk_number,
      location: $location,
      vm_size: $vm_size,
      run_url: $run_url,
      cloud: $cloud,
      case_name: $case_name,
      pv_creation_p50: $pv_creation_p50,
      pv_creation_p90: $pv_creation_p90,
      pv_creation_p99: $pv_creation_p99,
      attach_p50: $attach_p50,
      attach_p90: $attach_p90,
      attach_p99: $attach_p99,
      detach_p50: $detach_p50,
      detach_p90: $detach_p90,
      detach_p99: $detach_p99
    }')

  echo $data >> $result_dir/results.json
}
