#!/bin/bash

tag=$1
public_ip=${2:-''}
iteration=${3:-1000000}
limit=${4:-100}
side="client"

cd /home/adminuser
curl -L -s -o ${side}.tar.gz https://github.com/anson627/cloud-lb-evaluator/releases/download/$tag/${side}.tar.gz
tar -xzvf ${side}.tar.gz 
rm ${side}.tar.gz

cd ${side}_build
echo "Running client"
./${side} $public_ip $iteration $limit &> logs.txt &
ps -ef | grep $side