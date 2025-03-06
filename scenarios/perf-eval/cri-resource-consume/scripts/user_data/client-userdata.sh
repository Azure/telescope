MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="==MYBOUNDARY=="

--==MYBOUNDARY==
Content-Type: text/x-shellscript; charset="us-ascii"

#!/bin/bash

# Enable containerd metrics
sudo tee -a /etc/containerd/config.toml <<EOF

[metrics]
address = "0.0.0.0:10257"
EOF

sudo tee -a /etc/eks/containerd/containerd-config.toml <<EOF

[metrics]
address = "0.0.0.0:10257"
EOF

# Restart containerd to apply changes
sudo systemctl restart containerd

cat /etc/eks/containerd/containerd-config.toml >> /var/log/user-data.log
cat /etc/containerd/config.toml >> /var/log/user-data.log
echo "Containerd metrics enabled on port 10257" >> /var/log/user-data.log

--==MYBOUNDARY==--
