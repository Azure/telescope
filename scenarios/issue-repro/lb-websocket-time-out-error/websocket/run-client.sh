#!/bin/bash

tag=$1
public_ip=${2:-''}
port=${3:-443}
iteration=${4:-1000000}
limit=${5:-100}
timeout=${6:-10}

side="client"

cd /home/adminuser
curl -L -s -o ${side}.tar.gz https://github.com/anson627/cloud-lb-evaluator/releases/download/$tag/${side}.tar.gz
tar -xzvf ${side}.tar.gz 
rm ${side}.tar.gz

cd ${side}_build
echo "Running client"
./${side} $public_ip $port $iteration $limit $timeout &> logs.txt &
ps -ef | grep $side