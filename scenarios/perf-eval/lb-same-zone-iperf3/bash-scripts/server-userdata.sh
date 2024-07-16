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