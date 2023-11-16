#!/bin/bash

tag=$1
timeout=${2:-32}

cd server_build
echo "Running server"
./server $timeout &> logs.txt &
ps -ef | grep $side