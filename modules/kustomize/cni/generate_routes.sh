#!/bin/bash

# Script to generate 100,000 routes under 10.224.0.0/12 with /30 prefixes
# Each /30 subnet contains 4 IP addresses (2 usable)
# 10.224.0.0/12 covers 10.224.0.0 to 10.239.255.255

set -e

OUTPUT_FILE="add_routes.sh"
ROUTE_COUNT=100000

# Gateway pool - using common gateway IPs
GATEWAYS=(
    "10.224.0.1"
    "10.224.0.4" 
    "10.224.0.5"
    "10.224.0.6"
    "10.224.0.7"
    "10.224.0.8"
)

echo "Generating $ROUTE_COUNT routes..."
echo "Output file: $OUTPUT_FILE"

# Create output file with header
cat > "$OUTPUT_FILE" << 'EOF'
#!/bin/bash
# Generated routes for 10.224.0.0/12 network with /30 prefixes
# Total routes: 100000

set -e

echo "Adding 100,000 routes..."
start_time=$(date +%s)

EOF

# Function to convert IP to integer for calculations
ip_to_int() {
    local ip=$1
    local IFS='.'
    local -a octets=($ip)
    echo $(((octets[0] << 24) + (octets[1] << 16) + (octets[2] << 8) + octets[3]))
}

# Function to convert integer back to IP
int_to_ip() {
    local int=$1
    echo "$(((int >> 24) & 255)).$(((int >> 16) & 255)).$(((int >> 8) & 255)).$((int & 255))"
}

# Starting IP: 10.224.0.0
start_ip="10.224.0.0"
start_int=$(ip_to_int "$start_ip")

# Generate routes
echo "# Route generation started at $(date)" >> "$OUTPUT_FILE"

route_num=0
current_int=$start_int

while [ $route_num -lt $ROUTE_COUNT ]; do
    # Convert current integer back to IP
    current_ip=$(int_to_ip $current_int)
    
    # Extract octets for validation
    IFS='.' read -r o1 o2 o3 o4 <<< "$current_ip"
    
    # Ensure we stay within 10.224.0.0/12 (10.224.0.0 to 10.239.255.255)
    if [ $o1 -ne 10 ] || [ $o2 -lt 224 ] || [ $o2 -gt 239 ]; then
        echo "Error: IP $current_ip is outside 10.224.0.0/12 range"
        break
    fi
    
    # Ensure /30 alignment (last 2 bits of last octet should be 0)
    if [ $((o4 % 4)) -ne 0 ]; then
        # Round up to next /30 boundary
        current_int=$(((current_int + 3) & ~3))
        current_ip=$(int_to_ip $current_int)
    fi
    
    # Select gateway (rotate through available gateways)
    gateway_idx=$((route_num % ${#GATEWAYS[@]}))
    gateway="${GATEWAYS[$gateway_idx]}"
    
    # Add route command to output file
    echo "ip route add $current_ip/30 via $gateway dev eth0" >> "$OUTPUT_FILE"
    
    # Progress indicator
    if [ $((route_num % 10000)) -eq 0 ]; then
        echo "Generated $route_num routes..."
    fi
    
    # Move to next /30 subnet (add 4 to get next /30 block)
    current_int=$((current_int + 4))
    route_num=$((route_num + 1))
done

# Add footer to output file
cat >> "$OUTPUT_FILE" << 'EOF'

end_time=$(date +%s)
duration=$((end_time - start_time))
echo "Route addition completed in $duration seconds"

# Verify route count
route_count=$(ip route show | wc -l)
echo "Total routes in routing table: $route_count"

# Show some sample routes
echo "Sample routes added:"
ip route show | grep "10.224" | head -5
EOF

# Make the generated script executable
chmod +x "$OUTPUT_FILE"

echo "Route generation completed!"
echo "Generated $route_num routes in $OUTPUT_FILE"
echo ""
echo "To apply the routes, run: ./$OUTPUT_FILE"
echo ""
echo "WARNING: Adding 100,000 routes may:"
echo "- Take significant time (several minutes)"
echo "- Consume substantial memory"
echo "- Impact system performance"
echo "- Require sufficient privileges (run as root/sudo)"
echo ""
echo "To clean up routes later, you can use:"
echo "ip route show | grep '10.224' | while read route; do ip route del \$route 2>/dev/null || true; done"