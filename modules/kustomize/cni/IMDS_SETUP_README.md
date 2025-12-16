# Setup Node IMDS Script

This script configures ipvlan CNI on Azure VM nodes using the Azure Instance Metadata Service (IMDS).

## Overview

Unlike `setup.py` which runs externally and uses `az vm run-command`, this script is designed to run **inside the node** and queries IMDS directly to retrieve network interface configuration.

## Features

- Queries Azure IMDS for network interface metadata
- Extracts IP configurations from primary and secondary interfaces
- Generates ipvlan CNI configuration files
- Sets up IP addresses on network interfaces
- Configures iptables MASQUERADE rules for NAT
- Supports both IPv4 and IPv6

## Prerequisites

- Python 3.6+
- `requests` library: `pip install requests`
- Root/sudo privileges (for ip, iptables, and writing to `/etc/cni/net.d/`)
- Running on an Azure VM with IMDS access

## Installation

```bash
# Copy script to node
scp setup_ipvlan.py user@node:/tmp/

# SSH into the node
ssh user@node

# Install dependencies
pip install requests

# Make script executable
chmod +x /tmp/setup_ipvlan.py
```

## Usage

### Basic Usage (IPv4)

```bash
sudo python3 setup_ipvlan.py
```

### IPv6 Configuration

```bash
sudo python3 setup_ipvlan.py --address-version IPv6
```

### Skip Primary IP (Recommended)

If you want to configure only secondary IPs as ipvlan configs:

```bash
sudo python3 setup_ipvlan.py --skip-primary
```

### Custom Interface Name

```bash
sudo python3 setup_ipvlan.py --interface eth1 --cni-name ipvlan-eth1
```

### Dry Run

Test the configuration without making changes:

```bash
sudo python3 setup_ipvlan.py --dry-run
```

## Command-Line Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--address-version` | IP version (IPv4 or IPv6) | IPv4 |
| `--interface` | Network interface name | eth0 |
| `--cni-name` | CNI configuration name | ipvlan-eth0 |
| `--skip-primary` | Skip primary IP, use only secondary IPs | False |
| `--dry-run` | Print config without applying | False |

## What It Does

1. **Queries IMDS**: Retrieves network interface configuration from `http://169.254.169.254/metadata/instance/network`

2. **Extracts IP Configs**: Parses IPv4/IPv6 addresses, subnet information, and prefix lengths

3. **Derives IP Ranges**: Calculates usable IP ranges for IPAM (excluding network and broadcast addresses)

4. **Configures Network**:
   - Adds secondary IP addresses to the specified interface
   - Creates iptables MASQUERADE rules for outbound NAT

5. **Generates CNI Config**: Creates ipvlan CNI configuration file at `/etc/cni/net.d/01-ipvlan-eth0.conf`

## Example CNI Config Output

```json
{
  "cniVersion": "0.3.1",
  "name": "ipvlan-eth0",
  "type": "ipvlan",
  "master": "eth0",
  "linkInContainer": false,
  "mode": "l3s",
  "ipam": {
    "type": "host-local",
    "ranges": [
      [
        {
          "subnet": "10.224.0.16/28",
          "rangeStart": "10.224.0.17",
          "rangeEnd": "10.224.0.30"
        }
      ]
    ],
    "routes": [
      {
        "dst": "0.0.0.0/0"
      }
    ]
  }
}
```

## Comparison with setup.py

| Feature | setup.py | setup_ipvlan.py |
|---------|----------|-------------------|
| Runs from | External (workstation) | Inside node |
| Auth method | Azure CLI | IMDS |
| Execution | `az vm run-command` | Direct execution |
| Dependencies | Azure CLI, az login | requests library |
| Use case | Automation from outside | Bootstrap/init scripts |

## Troubleshooting

### IMDS Connection Error

```bash
# Test IMDS connectivity
curl -H "Metadata:true" "http://169.254.169.254/metadata/instance?api-version=2021-02-01"
```

### Permission Denied

Ensure you're running with sudo:
```bash
sudo python3 setup_ipvlan.py
```

### CNI Config Not Applied

Check CNI network directory exists:
```bash
sudo mkdir -p /etc/cni/net.d
```

### Verify Setup

```bash
# Check IP addresses
ip addr show eth0

# Check iptables rules
sudo iptables -t nat -L POSTROUTING -n -v

# Check CNI config
cat /etc/cni/net.d/01-ipvlan-eth0.conf
```

## Integration with Cloud-Init

You can use this script in cloud-init user data:

```yaml
#cloud-config
write_files:
  - path: /tmp/setup_ipvlan.py
    permissions: '0755'
    content: |
      #!/usr/bin/env python3
      # ... (script content) ...

runcmd:
  - pip3 install requests
  - python3 /tmp/setup_ipvlan.py --skip-primary
```

## License

Same as parent project.
