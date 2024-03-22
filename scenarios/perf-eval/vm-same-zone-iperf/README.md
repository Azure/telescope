# Overview

This guide covers how to manually run vm same zone iperf test on Azure

## Prerequisite

* Install [Terraform](https://developer.hashicorp.com/terraform/tutorials/aws-get-started/install-cli)
* Install [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-linux?pivots=apt)

## Define Variables

Set environment variables for testing

```bash
RUN_ID=123456789 # Name of resource group created by Terraform
RESULT_DIR=/tmp/$RUN_ID
CLOUD=azure
REGION=eastus
SERVER_ROLE=server
CLIENT_ROLE=client
TEST_MODULES_DIR=modules/bash
SSH_KEY_PATH=$(pwd)/modules/terraform/$CLOUD/private_key.pem
WAIT_TIME=240
RUN_TIME=600
TCP_THREAD_MODE=multi
UDP_THREAD_MODE=single
```

## Validate Resources

Validate server VM is running and ready for iperf traffic

```bash
SERVER_VM_ID=$(az resource list --resource-type Microsoft.Compute/virtualMachines --location $REGION --query "[?(tags.run_id == '${RUN_ID}' && tags.role == '${SERVER_ROLE}')].id" --output tsv)
SERVER_PUBLIC_IP=$(az vm list-ip-addresses --ids $SERVER_VM_ID --query '[].virtualMachine.network.publicIpAddresses[0].ipAddress' -o tsv)
SERVER_PRIVATE_IP=$(az vm list-ip-addresses --ids $SERVER_VM_ID --query '[].virtualMachine.network.privateIpAddresses[0]' -o tsv)
```

Validate client VM is running and ready for iperf traffic

```bash
CLIENT_VM_ID=$(az resource list --resource-type Microsoft.Compute/virtualMachines --location $REGION --query "[?(tags.run_id == '${RUN_ID}' && tags.role == '${CLIENT_ROLE}')].id" --output tsv)
CLIENT_PUBLIC_IP=$(az vm list-ip-addresses --ids $CLIENT_VM_ID --query '[].virtualMachine.network.publicIpAddresses[0].ipAddress' -o tsv)
CLIENT_PRIVATE_IP=$(az vm list-ip-addresses --ids $CLIENT_VM_ID --query '[].virtualMachine.network.privateIpAddresses[0]' -o tsv)
```

## Execute Tests

Run iperf for both TCP and UDP test traffic with target bandwidth at 100Mbps, 1Gbps, 2Gbps, 4Gbps for 600 seconds

```bash
source ./${TEST_MODULES_DIR}/iperf.sh
run_iperf2 $SERVER_PRIVATE_IP $CLIENT_PUBLIC_IP $TCP_THREAD_MODE "tcp" $RUN_TIME $WAIT_TIME $SSH_KEY_PATH $SERVER_PUBLIC_IP $RESULT_DIR
run_iperf2 $SERVER_PRIVATE_IP $CLIENT_PUBLIC_IP $UDP_THREAD_MODE "udp" $RUN_TIME $WAIT_TIME $SSH_KEY_PATH $SERVER_PUBLIC_IP $RESULT_DIR
```

## Collect Results

Collect and parse iperf output and Linux counters, merge into a single result JSON file

```bash
collect_result_iperf2 $RESULT_DIR $CLIENT_PRIVATE_IP $SERVER_PRIVATE_IP $CLOUD $RUN_ID
```

Check the results

```bash
cat $RESULT_DIR/results.json | jq .
```

## Cleanup Results

Cleanup test results

```bash
rm -rf $RESULT_DIR
```
