#!/bin/bash
# filepath: /home/azureuser/aks/telescope/scenarios/perf-eval/lb-cross-plat-k6/scripts/user_data/client-userdata.sh

# Change SSH port for security purposes
sudo perl -pi -e 's/^#?Port 22$/Port 2222/' /etc/ssh/sshd_config
sudo service ssh restart

# Update and install dependencies
sudo apt-get update && sudo apt-get upgrade -y
sudo apt-get install -y ca-certificates curl gnupg lsb-release

# Install k6 for load testing
sudo gpg -k
sudo gpg --no-default-keyring --keyring /usr/share/keyrings/k6-archive-keyring.gpg --keyserver hkp://keyserver.ubuntu.com:80 --recv-keys C5AD17C747E3415A3642D57D77C6C491D6AC1D69
echo "deb [signed-by=/usr/share/keyrings/k6-archive-keyring.gpg] https://dl.k6.io/deb stable main" | sudo tee /etc/apt/sources.list.d/k6.list
sudo apt-get update
sudo apt-get install k6 -y

# Install monitoring tools
sudo apt-get install -y prometheus-node-exporter htop sysstat

# Install Azure CLI
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash

# Install kubectl for cluster interaction
sudo curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo chmod +x kubectl
sudo mv kubectl /usr/local/bin/

# Create directory for test scripts
mkdir -p /home/azureuser/loadtests

# Create a basic k6 script for HTTP testing
cat > /home/azureuser/loadtests/http-test.js << 'EOL'
import http from 'k6/http';
import { sleep } from 'k6';

export const options = {
  stages: [
    { duration: '1m', target: 1000 },  // Ramp up to 1000 RPS
    { duration: '3m', target: 5000 },  // Ramp up to 5000 RPS
    { duration: '5m', target: 5000 },  // Stay at 5000 RPS
    { duration: '1m', target: 0 },     // Ramp down to 0 RPS
  ],
};

export default function() {
  const TARGET_URL = __ENV.TARGET_URL || 'http://azure-lb-service'; // Can be overridden with environment variable
  const res = http.get(TARGET_URL);
  sleep(0.1);
}
EOL

# Set permissions
sudo chown -R azureuser:azureuser /home/azureuser/loadtests
chmod 755 /home/azureuser/loadtests/*.js

# Install OpenTelemetry Collector
curl -sSL https://github.com/open-telemetry/opentelemetry-collector-releases/releases/download/v0.83.0/otelcol_0.83.0_linux_amd64.tar.gz | sudo tar xzf - -C /usr/local/bin

# Create OpenTelemetry Collector config
sudo mkdir -p /etc/otelcol
cat > /etc/otelcol/config.yaml << 'EOL'
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  batch:
    send_batch_size: 10000
    timeout: 5s
  memory_limiter:
    check_interval: 1s
    limit_mib: 1000

exporters:
  azure_monitor:
    instrumentation_key: ${APPINSIGHTS_INSTRUMENTATIONKEY}
  logging:
    verbosity: detailed

service:
  pipelines:
    metrics:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [azure_monitor, logging]
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [azure_monitor, logging]
EOL

# Create systemd service for OpenTelemetry Collector
cat > /etc/systemd/system/otelcol.service << 'EOL'
[Unit]
Description=OpenTelemetry Collector
After=network.target

[Service]
ExecStart=/usr/local/bin/otelcol --config=/etc/otelcol/config.yaml
Restart=always
User=root
Group=root
Environment=APPINSIGHTS_INSTRUMENTATIONKEY=

[Install]
WantedBy=multi-user.target
EOL

sudo systemctl daemon-reload
sudo systemctl enable otelcol

echo "Client VM setup complete - ready for load testing"