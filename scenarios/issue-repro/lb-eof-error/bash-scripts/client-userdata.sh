#!/bin/bash

cd /home/adminuser
curl -L -s -o client.tar.gz https://github.com/anson627/cloud-lb-evaluator/releases/download/v1.0.4/client.tar.gz
tar -xzvf client.tar.gz
rm client.tar.gz