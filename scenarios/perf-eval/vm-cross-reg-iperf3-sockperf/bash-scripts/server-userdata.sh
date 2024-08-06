#!/bin/bash

sudo perl -pi -e 's/^#?Port 22$/Port 2222/' /etc/ssh/sshd_config
sudo service ssh restart

sudo apt-get update && sudo apt-get install iperf3 -y

# set up tcp listener
nohup iperf3 --server --port 20000 &> /dev/null &

for i in {3..4}
do
  nohup iperf3 --server --port "2000$i" &> /dev/null &
done

sudo apt-get update && sudo apt-get install sockperf net-tools -y

ip=$(ifconfig | grep -Eo 'inet (addr:)?([0-9]*\.){3}[0-9]*' | grep -Eo '([0-9]*\.){3}[0-9]*' | grep -v '127.0.0.1')
nohup sockperf server -i $ip --tcp -p 20005 &