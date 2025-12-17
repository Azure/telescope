#!/bin/bash
set -euo pipefail

# Script to setup ipvlan CNI configuration on an Azure VM node using IMDS
# This script is designed to run inside the node (not externally via az vm run-command)

# Default values
ADDRESS_VERSION="IPv4"
INTERFACE_NAME="eth0"
CNI_NAME="ipvlan-eth0"
API_VERSION="2025-04-07"

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

# Query Azure IMDS
query_imds() {
    local endpoint_path="$1"
    local url="http://169.254.169.254${endpoint_path}?api-version=${API_VERSION}&format=json"
    
    if ! curl -s -H "Metadata: true" "$url"; then
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

# Set default route and iptables command based on IP version
if [[ "$ADDRESS_VERSION" == "IPv6" ]]; then
    DEFAULT_ROUTE="::/0"
    IPTABLES_CMD="ip6tables"
else
    DEFAULT_ROUTE="0.0.0.0/0"
    IPTABLES_CMD="iptables"
fi

echo "Querying Azure IMDS for network interface information..."
IMDS_DATA=$(query_imds "/metadata/instance/network")
echo "Successfully retrieved IMDS data: $IMDS_DATA"

# Parse IMDS response and extract interface data
if [[ "$ADDRESS_VERSION" == "IPv6" ]]; then
    IP_VERSION_KEY="ipv6"
else
    IP_VERSION_KEY="ipv4"
fi

# Extract subnet and address blocks
SUBNET=$(echo "$IMDS_DATA" | jq -r ".interface[0].${IP_VERSION_KEY}.subnet[0] | .address + \"/\" + (.prefix | tostring)")
ADDRESS_BLOCKS=$(echo "$IMDS_DATA" | jq -c ".interface[0].${IP_VERSION_KEY}.ipAddressBlock[]")

if [[ -z "$SUBNET" || "$SUBNET" == "null/null" ]]; then
    echo "Error: Missing subnet information" >&2
    exit 1
fi

if [[ -z "$ADDRESS_BLOCKS" ]]; then
    echo "Error: Missing address blocks" >&2
    exit 1
fi

echo "Found subnet: $SUBNET"

# Build CNI configuration
CNI_RANGES="["

FIRST_BLOCK=true
while IFS= read -r block; do
    BLOCK_ADDR=$(echo "$block" | jq -r '.privateIpAddress')
    
    if [[ -z "$BLOCK_ADDR" || "$BLOCK_ADDR" == "null" ]]; then
        echo "Missing address in block, skipping"
        continue
    fi
    
    echo "Processing address block: $BLOCK_ADDR"
    
    # Derive range
    read -r START_IP END_IP <<< "$(derive_range "$BLOCK_ADDR" "$ADDRESS_VERSION")"
    
    # Add address to interface
    echo "Adding address block $BLOCK_ADDR to $INTERFACE_NAME"
    ip addr replace "$BLOCK_ADDR" dev "$INTERFACE_NAME"
    
    # Add iptables MASQUERADE rule
    echo "Adding iptables MASQUERADE rule for $BLOCK_ADDR"
    if ! $IPTABLES_CMD -t nat -C POSTROUTING -s "$BLOCK_ADDR" ! -d "$SUBNET" -j MASQUERADE 2>/dev/null; then
        echo "MASQUERADE rule not found, adding it"
        $IPTABLES_CMD -t nat -A POSTROUTING -s "$BLOCK_ADDR" ! -d "$SUBNET" -j MASQUERADE
    fi
    
    # Build subnet entry for CNI config
    if [[ "$FIRST_BLOCK" == true ]]; then
        FIRST_BLOCK=false
    else
        CNI_RANGES+=","
    fi
    
    CNI_RANGES+="{\"subnet\":\"$BLOCK_ADDR\",\"rangeStart\":\"$START_IP\",\"rangeEnd\":\"$END_IP\"}"
    
done <<< "$ADDRESS_BLOCKS"

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
