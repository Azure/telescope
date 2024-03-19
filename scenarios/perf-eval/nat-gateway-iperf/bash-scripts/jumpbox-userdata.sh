#!/bin/bash

sudo perl -pi -e 's/^#?Port 22$/Port 2222/' /etc/ssh/sshd_config
sudo service ssh restart
