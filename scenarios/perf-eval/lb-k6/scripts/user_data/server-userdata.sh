#!/bin/bash
# filepath: /home/azureuser/aks/telescope/scenarios/perf-eval/lb-cross-plat-k6/scripts/user_data/server-userdata.sh

# Change SSH port for security purposes
sudo perl -pi -e 's/^#?Port 22$/Port 2222/' /etc/ssh/sshd_config
sudo service ssh restart

# Update and install dependencies
sudo apt-get update && sudo apt-get upgrade -y
sudo apt-get install -y ca-certificates curl gnupg lsb-release nginx

# Install Azure CLI 
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash

# Create simple web server for load testing
cat > /var/www/html/index.html << 'EOL'
<!DOCTYPE html>
<html>
<head>
    <title>AKS Load Test Server</title>
</head>
<body>
    <h1>Hello World from Azure Load Balancer Test Server</h1>
    <p>Server ID: $(hostname)</p>
    <p>Timestamp: $(date)</p>
</body>
</html>
EOL

# Configure nginx to listen on port 80 with basic performance settings
cat > /etc/nginx/sites-available/default << 'EOL'
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    
    root /var/www/html;
    index index.html;
    
    server_name _;
    
    location / {
        try_files $uri $uri/ =404;
    }
    
    # Health check endpoint
    location /health {
        access_log off;
        return 200 'healthy\n';
    }
}
EOL

# Configure nginx for high performance
cat > /etc/nginx/nginx.conf << 'EOL'
user www-data;
worker_processes auto;
pid /run/nginx.pid;
include /etc/nginx/modules-enabled/*.conf;

events {
    worker_connections 10000;
    multi_accept on;
    use epoll;
}

http {
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    types_hash_max_size 2048;
    server_tokens off;
    
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    
    access_log /var/log/nginx/access.log;
    error_log /var/log/nginx/error.log;
    
    gzip on;
    
    include /etc/nginx/conf.d/*.conf;
    include /etc/nginx/sites-enabled/*;
}
EOL

# Update kernel parameters for better performance
cat > /etc/sysctl.d/99-network-tuning.conf << 'EOL'
net.core.somaxconn = 65536
net.ipv4.tcp_max_syn_backlog = 65536
net.core.netdev_max_backlog = 65536
net.ipv4.ip_local_port_range = 1024 65535
EOL
sudo sysctl -p /etc/sysctl.d/99-network-tuning.conf

# Restart nginx with new configuration
sudo systemctl enable nginx
sudo systemctl restart nginx

# Install monitoring tools
sudo apt-get install -y prometheus-node-exporter htop sysstat

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
  hostmetrics:
    collection_interval: 10s
    scrapers:
      cpu:
      load:
      memory:
      network:
      disk:
  filelog:
    include: [/var/log/nginx/access.log]
    
processors:
  batch:
    send_batch_size: 10000
    timeout: 5s
  resource:
    attributes:
      - key: service.name
        value: "aks-lb-server"
        action: upsert

exporters:
  azure_monitor:
    instrumentation_key: ${APPINSIGHTS_INSTRUMENTATIONKEY}
  logging:
    verbosity: detailed

service:
  pipelines:
    metrics:
      receivers: [otlp, hostmetrics]
      processors: [resource, batch]
      exporters: [azure_monitor, logging]
    traces:
      receivers: [otlp]
      processors: [resource, batch]
      exporters: [azure_monitor, logging]
    logs:
      receivers: [filelog]
      processors: [resource, batch]
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
sudo systemctl start otelcol

# Start HTTP server on port 20001 for compatibility with load balancer health checks
cat > /usr/local/bin/simple-http-server.py << 'EOL'
#!/usr/bin/env python3
from http.server import HTTPServer, BaseHTTPRequestHandler

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'OK\n')

httpd = HTTPServer(('0.0.0.0', 20001), SimpleHTTPRequestHandler)
httpd.serve_forever()
EOL

chmod +x /usr/local/bin/simple-http-server.py

# Create systemd service for simple HTTP server
cat > /etc/systemd/system/http-health.service << 'EOL'
[Unit]
Description=Simple HTTP Health Check Server
After=network.target

[Service]
ExecStart=/usr/local/bin/simple-http-server.py
Restart=always
User=root
Group=root

[Install]
WantedBy=multi-user.target
EOL

sudo systemctl daemon-reload
sudo systemctl enable http-health
sudo systemctl start http-health

echo "Server setup complete - ready for load balancer testing"