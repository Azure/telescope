#!/bin/bash

tag=$1
timeout=${2:-32}
side="server"

cd /home/adminuser
curl -L -s -o ${side}.tar.gz https://github.com/anson627/cloud-lb-evaluator/releases/download/$tag/${side}.tar.gz
tar -xzvf ${side}.tar.gz 
rm ${side}.tar.gz

cd ${side}_build
echo "Running server"
./${side} $timeout &> logs.txt &
ps -ef | grep $side