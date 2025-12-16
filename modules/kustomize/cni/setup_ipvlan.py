#!/usr/bin/env python3
"""
Script to setup ipvlan CNI configuration on an Azure VM node using IMDS.
This script is designed to run inside the node (not externally via az vm run-command).
"""

import argparse
import json
import subprocess
import sys
import ipaddress
import requests
from typing import List, Dict, Optional


def query_imds(endpoint_path: str, api_version: str = "2025-04-07") -> Dict:
    """
    Query Azure Instance Metadata Service (IMDS).

    Args:
        endpoint_path: The IMDS endpoint path (e.g., '/metadata/instance/network')
        api_version: The IMDS API version to use

    Returns:
        Dictionary containing the IMDS response
    """
    imds_url = f"http://169.254.169.254{endpoint_path}"
    headers = {"Metadata": "true"}
    params = {"api-version": api_version, "format": "json"}

    try:
        response = requests.get(imds_url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error querying IMDS: {e}", file=sys.stderr)
        sys.exit(1)


def get_network_interfaces() -> List[Dict]:
    """
    Retrieve network interface information from IMDS.

    Returns:
        List of network interface configurations
    """
    metadata = query_imds("/metadata/instance/network")
    interfaces = metadata.get("interface", [])

    if not interfaces:
        print("No network interfaces found in IMDS response", file=sys.stderr)
        sys.exit(1)

    return interfaces


def derive_range(ip_addr: str, address_version: str = "IPv4") -> str:
    """
    Derive usable IP range from a CIDR notation address.

    Args:
        ip_addr: IP address in CIDR notation
        address_version: IPv4 or IPv6

    Returns:
        String with start and end IP addresses separated by space
    """
    if address_version == "IPv6":
        network = ipaddress.IPv6Network(ip_addr, strict=False)
    else:
        network = ipaddress.IPv4Network(ip_addr, strict=False)

    if network.num_addresses <= 2:
        raise ValueError(f"Prefix too small for usable host range: {ip_addr}")

    start = network.network_address + 1
    end = network.broadcast_address - 1
    return f"{start} {end}"


def run_command(cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
    """
    Execute a shell command.

    Args:
        cmd: Command and arguments as a list
        check: Whether to raise exception on non-zero exit code

    Returns:
        CompletedProcess instance
    """
    print(f"Executing: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, check=check)
    if result.returncode != 0:
        print(f"Command failed with exit code {result.returncode}", file=sys.stderr)
        print(f"STDOUT: {result.stdout}", file=sys.stderr)
        print(f"STDERR: {result.stderr}", file=sys.stderr)
        if check:
            sys.exit(1)
    return result


def setup_ipvlan_config(
    ipvlan_configs: List[Dict],
    address_version: str = "IPv4",
    interface_name: str = "eth0",
    cni_name: str = "ipvlan-eth0",
) -> None:
    """
    Setup ipvlan CNI configuration, routes, and iptables rules.

    Args:
        ipvlan_configs: List of ipvlan IP configurations
        address_version: IPv4 or IPv6
        interface_name: Network interface name (default: eth0)
        cni_name: CNI configuration name
    """
    default_route = "::/0" if address_version == "IPv6" else "0.0.0.0/0"
    iptables_cmd = "ip6tables" if address_version == "IPv6" else "iptables"

    for ipvlan_cfg in ipvlan_configs:
        subnet = ipvlan_cfg.get("subnet")
        address_blocks = ipvlan_cfg.get("address_blocks", [])
        subnets = []
        for block in address_blocks:
            block_addr = block.get("privateIpAddress")
            if not block_addr:
                print(f"Missing address in address block: {block}; skipping.")
                continue

            start, end = derive_range(block_addr, address_version).split()
            subnet_map = {
                "subnet": block_addr,
                "rangeStart": start,
                "rangeEnd": end,
            }
            subnets.append(subnet_map)

            # Assign IP address to interface
            print(f"Adding address block {block_addr} to {interface_name}")
            run_command(["ip", "addr", "replace", block_addr, "dev", interface_name])
            # Add iptables MASQUERADE rule
            print(f"Adding iptables MASQUERADE rule for {block_addr}")
            try:
                run_command([iptables_cmd, "-t", "nat", "-C", "POSTROUTING", "-s", block_addr, "!", "-d", subnet, "-j", "MASQUERADE"])
            except SystemExit:
                print(f"MASQUERADE rule not found for {block_addr}, adding it.")
                run_command([iptables_cmd, "-t", "nat", "-A", "POSTROUTING", "-s", block_addr, "!", "-d", subnet, "-j", "MASQUERADE"])

        # Create CNI configuration
        config = {
            "cniVersion": "0.3.1",
            "name": cni_name,
            "type": "ipvlan",
            "master": interface_name,
            "linkInContainer": False,
            "mode": "l3s",
            "ipam": {
                "type": "host-local",
                "ranges": [subnets],
                "routes": [{"dst": default_route}],
            },
        }

        print(f"Generated ipvlan CNI config:\n{json.dumps(config, indent=2)}")

        # Write CNI configuration file
        cni_config_path = f"/etc/cni/net.d/01-{cni_name}.conf"
        try:
            with open(cni_config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
            print(f"Successfully wrote CNI config to {cni_config_path}")
        except IOError as e:
            print(f"Error writing CNI config to {cni_config_path}: {e}", file=sys.stderr)
            sys.exit(1)


def extract_ipvlan_configs(
    interfaces: List[Dict], address_version: str = "IPv4"
) -> List[Dict]:
    """
    Extract ipvlan IP configurations from IMDS network interface data.

    Args:
        interfaces: List of network interfaces from IMDS
        address_version: IPv4 or IPv6

    Returns:
        List of ipvlan IP configurations
    """
    ipvlan_configs = []

    for iface in interfaces:
        ipv4_configs = iface.get("ipv4", {}).get("ipAddress", [])
        ipv6_configs = iface.get("ipv6", {}).get("ipAddress", [])
        configs = ipv4_configs if address_version == "IPv4" else ipv6_configs

        subnet_info = configs.get("subnet", [])
        if not subnet_info:
            print(
                f"Missing subnet information for interface {iface.get('name', '')}"
            )
            sys.exit(1)

        subnet_address = subnet_info[0].get("address", "")
        subnet_prefix_length = subnet_info[0].get("prefix", "")
        subnet = f"{subnet_address}/{subnet_prefix_length}"

        address_blocks = configs.get("ipAddressBlock", [])
        if not address_blocks:
            print(
                f"Missing address blocks for interface {iface.get('name', '')}"
            )
            sys.exit(1)

        ipvlan_configs.append(
            {
                "subnet": subnet,
                "address_blocks": address_blocks,
            }
        )
    return ipvlan_configs


def main():
    parser = argparse.ArgumentParser(
        description="Setup ipvlan CNI configuration using Azure IMDS"
    )
    parser.add_argument(
        "--address-version",
        type=str,
        default="IPv4",
        choices=["IPv4", "IPv6"],
        help="IP address version (default: IPv4)",
    )
    parser.add_argument(
        "--interface",
        type=str,
        default="eth0",
        help="Network interface name (default: eth0)",
    )
    parser.add_argument(
        "--cni-name",
        type=str,
        default="ipvlan-eth0",
        help="CNI configuration name (default: ipvlan-eth0)",
    )

    args = parser.parse_args()

    print("Querying Azure IMDS for network interface information...")
    interfaces = get_network_interfaces()

    print(f"Found {len(interfaces)} network interface(s)")

    # Extract all IP configurations
    configs = extract_ipvlan_configs(interfaces, args.address_version)
    # Setup ipvlan configuration
    setup_ipvlan_config(
        configs,
        address_version=args.address_version,
        interface_name=args.interface,
        cni_name=args.cni_name,
    )

    print("\nSetup completed successfully!")


if __name__ == "__main__":
    main()
