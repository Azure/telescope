#!/bin/bash

tag=$1
public_ip=${2:-''}
iteration=${3:-1000000}
limit=${4:-100}

cd client_build
echo "Running client"
./client $public_ip $iteration $limit &> logs.txt &
ps -ef | grep $side