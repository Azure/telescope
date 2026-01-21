#!/bin/bash
set -euo pipefail

# Script to setup ipvlan CNI configuration on an AWS EC2 instance using IMDS
# This script is designed to run inside the node

# Default values
ADDRESS_VERSION="IPv4"
INTERFACE_NAME="eth0"
CNI_NAME="ipvlan-eth0"
IMDS_TOKEN_TTL="300"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --address-version)
            ADDRESS_VERSION="$2"
            shift 2
            ;;
        --interface)
            INTERFACE_NAME="$2"
            shift 2
            ;;
        --cni-name)
            CNI_NAME="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [options]"
            echo "Options:"
            echo "  --address-version [IPv4|IPv6]  IP address version (default: IPv4)"
            echo "  --interface NAME               Network interface name (default: eth0)"
            echo "  --cni-name NAME                CNI configuration name (default: ipvlan-eth0)"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Get IMDSv2 token
get_imds_token() {
    curl -s -X PUT "http://169.254.169.254/latest/api/token" \
        -H "X-aws-ec2-metadata-token-ttl-seconds: ${IMDS_TOKEN_TTL}"
}

# Query AWS IMDS (IMDSv2)
query_imds() {
    local endpoint_path="$1"
    local token="$2"
    local url="http://169.254.169.254${endpoint_path}"
    
    if ! curl -s -H "X-aws-ec2-metadata-token: $token" "$url"; then
        echo "Error querying IMDS: $url" >&2
        exit 1
    fi
}

# Derive IP range from CIDR
derive_range() {
    local ip_addr="$1"
    local version="$2"
    
    if [[ "$version" == "IPv6" ]]; then
        # For IPv6, use ipcalc or manual calculation
        python3 -c "import ipaddress; net = ipaddress.IPv6Network('$ip_addr', strict=False); print(f'{net.network_address + 1} {net.broadcast_address - 1}')"
    else
        # For IPv4
        python3 -c "import ipaddress; net = ipaddress.IPv4Network('$ip_addr', strict=False); print(f'{net.network_address + 1} {net.broadcast_address - 1}')"
    fi
}

# Check for required CNI plugins
if ls /opt/cni/bin/ipvlan 1> /dev/null 2>&1; then
    echo "Found ipvlan CNI plugin."
else
    echo "Install all CNI plugins in /opt/cni/bin before running this script."
    # Detect architecture
    ARCH=$(uname -m)
    if [[ "$ARCH" == "aarch64" ]]; then
        CNI_ARCH="arm64"
    else
        CNI_ARCH="amd64"
    fi
    CNI_PLUGIN_URL="https://github.com/containernetworking/plugins/releases/download/v1.9.0/cni-plugins-linux-${CNI_ARCH}-v1.9.0.tgz"
    echo "Downloading CNI plugins from $CNI_PLUGIN_URL..."
    mkdir -p /opt/cni/bin
    curl -L "$CNI_PLUGIN_URL" | tar -xz -C /opt/cni/bin
    ls -la /opt/cni/bin
fi

# Set default route and iptables command based on IP version
if [[ "$ADDRESS_VERSION" == "IPv6" ]]; then
    DEFAULT_ROUTE="::/0"
    IPTABLES_CMD="ip6tables"
else
    DEFAULT_ROUTE="0.0.0.0/0"
    IPTABLES_CMD="iptables"
fi

echo "Getting IMDSv2 token..."
IMDS_TOKEN=$(get_imds_token)

if [[ -z "$IMDS_TOKEN" ]]; then
    echo "Error: Failed to get IMDS token" >&2
    exit 1
fi

echo "Querying AWS IMDS for network interface information..."

# Get the MAC address of the primary interface
MAC_ADDRESS=$(query_imds "/latest/meta-data/mac" "$IMDS_TOKEN")
echo "Found MAC address: $MAC_ADDRESS"

# Get subnet CIDR
if [[ "$ADDRESS_VERSION" == "IPv6" ]]; then
    SUBNET=$(query_imds "/latest/meta-data/network/interfaces/macs/${MAC_ADDRESS}/subnet-ipv6-cidr-blocks" "$IMDS_TOKEN" | head -1)
else
    SUBNET=$(query_imds "/latest/meta-data/network/interfaces/macs/${MAC_ADDRESS}/subnet-ipv4-cidr-block" "$IMDS_TOKEN")
fi

if [[ -z "$SUBNET" ]]; then
    echo "Error: Missing subnet information" >&2
    exit 1
fi

echo "Found subnet: $SUBNET"

# Get IPv4/IPv6 prefixes (prefix delegation)
if [[ "$ADDRESS_VERSION" == "IPv6" ]]; then
    PREFIXES=$(query_imds "/latest/meta-data/network/interfaces/macs/${MAC_ADDRESS}/ipv6-prefix" "$IMDS_TOKEN")
else
    PREFIXES=$(query_imds "/latest/meta-data/network/interfaces/macs/${MAC_ADDRESS}/ipv4-prefix" "$IMDS_TOKEN")
fi

if [[ -z "$PREFIXES" ]]; then
    echo "Error: No IPv4/IPv6 prefixes found. Make sure prefix delegation is enabled on the ENI." >&2
    exit 1
fi

echo "Found prefixes:"
echo "$PREFIXES"

# Build CNI configuration
CNI_RANGES="["

FIRST_PREFIX=true
while IFS= read -r PREFIX; do
    if [[ -z "$PREFIX" ]]; then
        continue
    fi
    
    echo "Processing prefix: $PREFIX"
    
    # Derive range
    read -r START_IP END_IP <<< "$(derive_range "$PREFIX" "$ADDRESS_VERSION")"
    
    # Add address to interface
    echo "Adding prefix $PREFIX to $INTERFACE_NAME"
    ip addr replace "$PREFIX" dev "$INTERFACE_NAME" 2>/dev/null || true
    
    # Add iptables MASQUERADE rule
    echo "Adding iptables MASQUERADE rule for $PREFIX"
    if ! $IPTABLES_CMD -t nat -C POSTROUTING -s "$PREFIX" ! -d "$SUBNET" -j MASQUERADE 2>/dev/null; then
        echo "MASQUERADE rule not found, adding it"
        $IPTABLES_CMD -t nat -A POSTROUTING -s "$PREFIX" ! -d "$SUBNET" -j MASQUERADE
    fi
    
    # Build subnet entry for CNI config
    if [[ "$FIRST_PREFIX" == true ]]; then
        FIRST_PREFIX=false
    else
        CNI_RANGES+=","
    fi
    
    CNI_RANGES+="{\"subnet\":\"$PREFIX\",\"rangeStart\":\"$START_IP\",\"rangeEnd\":\"$END_IP\"}"
    
done <<< "$PREFIXES"

CNI_RANGES+="]"

# Create CNI configuration
CNI_CONFIG=$(cat <<EOF
{
  "cniVersion": "0.3.1",
  "name": "$CNI_NAME",
  "type": "ipvlan",
  "master": "$INTERFACE_NAME",
  "linkInContainer": false,
  "mode": "l3s",
  "ipam": {
    "type": "host-local",
    "ranges": [$CNI_RANGES],
    "routes": [{"dst": "$DEFAULT_ROUTE"}]
  }
}
EOF
)

echo "Generated ipvlan CNI config:"
echo "$CNI_CONFIG" | jq .

# Write CNI configuration file
mkdir -p /etc/cni/net.d
CNI_CONFIG_PATH="/etc/cni/net.d/01-${CNI_NAME}.conf"
echo "$CNI_CONFIG" | jq . > "$CNI_CONFIG_PATH"

if [[ $? -eq 0 ]]; then
    echo "Successfully wrote CNI config to $CNI_CONFIG_PATH"
else
    echo "Error writing CNI config to $CNI_CONFIG_PATH" >&2
    exit 1
fi

echo ""
echo "Setup completed successfully!"
