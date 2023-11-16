#!/bin/bash

cd /home/adminuser
curl -L -s -o server.tar.gz https://github.com/anson627/cloud-lb-evaluator/releases/download/v1.0.4/server.tar.gz
tar -xzvf server.tar.gz
rm server.tar.gz