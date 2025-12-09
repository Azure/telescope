import argparse
import base64
import json
import subprocess
import ipaddress

subnet_cache = {}


def run_az(args, capture=True):
    cmd = ["az", *args]
    result = subprocess.run(cmd, capture_output=capture, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{result.stderr}")
    return result.stdout.strip() if capture else ""


def subnet_prefix_for(subnet_id):
    if not subnet_id:
        return ""
    if subnet_id in subnet_cache:
        return subnet_cache[subnet_id]
    subnet = json.loads(
        run_az(
            [
                "network",
                "vnet",
                "subnet",
                "show",
                "--ids",
                subnet_id,
                "-o",
                "json",
            ]
        )
    )
    prefix = subnet.get("addressPrefix")
    if not prefix:
        prefixes = subnet.get("addressPrefixes") or []
        print(f"Subnet {subnet_id} has prefixes: {prefixes}")
        prefix = prefixes[1] if prefixes else ""
    subnet_cache[subnet_id] = prefix
    return prefix


def scan_node_nics(node_rg):
    nic_records = json.loads(
        run_az(
            [
                "network",
                "nic",
                "list",
                "--resource-group",
                node_rg,
                "-o",
                "json",
            ]
        )
        or "[]"
    )
    results = []
    for nic in nic_records:
        nic_name = nic.get("name", "")
        if not nic_name.endswith("pod-nic"):
            print(f"Skipping non-pod NIC {nic_name}")
            continue
        vm = nic.get("virtualMachine") or {}
        vm_id = vm.get("id", "")
        vm_name = vm_id.split("/")[-1] if vm_id else ""
        ip_configs = []
        for cfg in nic.get("ipConfigurations") or []:
            cfg_name = cfg.get("name", "")
            if not (cfg.get("primary") or cfg_name in ("ipvlan", "ipv6config")):
                continue
            subnet_id = (cfg.get("subnet") or {}).get("id", "")
            ip_configs.append(
                {
                    "name": cfg_name,
                    "primary": bool(cfg.get("primary")),
                    "ip": cfg.get("privateIPAddress", ""),
                    "subnet_id": subnet_id,
                    "subnet_prefix": subnet_prefix_for(subnet_id) if subnet_id else "",
                }
            )
        results.append(
            {
                "name": nic.get("name"),
                "vm_name": vm_name,
                "ip_configs": ip_configs,
            }
        )
    return results


def boostrap_cni_config(node_rg, nic_name, vm_name, ipvlan_cfg, address_version="IPv4"):
    if not vm_name or vm_name == "null":
        print(f"NIC {nic_name} not attached to a VM; skipping CNI config.")
        return
    if not ipvlan_cfg:
        print(f"NIC {nic_name} missing ipvlan metadata; skipping.")
        return
    ipvlan_cidr = ipvlan_cfg.get("ip")
    if not ipvlan_cidr:
        print(f"Unable to read ipvlan IP for NIC {nic_name}; skipping.")
        return
    subnet_prefix = ipvlan_cfg.get("subnet_prefix")
    if not subnet_prefix:
        print(f"Unable to read subnet prefix for NIC {subnet_prefix}; skipping.")
        return
    start, end = derive_range(ipvlan_cidr, address_version).split()

    default_route = "::/0" if address_version == "IPv6" else "0.0.0.0/0"
    cni_name = "ipvlan-eth1"
    interface_name = "eth1"

    # CNI config uses dummy interface as master instead of eth0
    # This allows node-to-pod communication while keeping eth0 free
    config = {
        "cniVersion": "0.3.1",
        "name": cni_name,
        "type": "ipvlan",
        "master": interface_name,
        "linkInContainer": False,
        "mode": "l3s",
        "ipam": {
            "type": "host-local",
            "ranges": [
                [
                    {
                        "subnet": ipvlan_cidr,
                        "rangeStart": start,
                        "rangeEnd": end,
                    }
                ]
            ],
            "routes": [{"dst": default_route}],
        },
    }
    ipvlan_payload = base64.b64encode(json.dumps(config, indent=2).encode()).decode()
    print(
        f"Pushing ipvlan CNI config with subnet {ipvlan_cidr}, rangeStart {start}, rangeEnd {end} to VM {vm_name}..."
    )

    iptables_cmd = "ip6tables" if address_version == "IPv6" else "iptables"
    # network = ipaddress.ip_network(ipvlan_cidr, strict=False)
    # route_cmd = "ip -6 route" if address_version == "IPv6" else "ip route"

    scripts = [
        # Bring interface up
        f"ip addr replace {ipvlan_cidr} dev {interface_name}",
        f"ip link set {interface_name} up",
        f"ip route add {subnet_prefix} dev {interface_name} || true",
        # Write CNI config
        f"echo {ipvlan_payload} | base64 -d | tee /etc/cni/net.d/01-{cni_name}.conf",
        # Setup NAT for outbound traffic (pods to internet)
        f"{iptables_cmd} -t nat -A POSTROUTING -s {ipvlan_cidr} ! -d {subnet_prefix} -j MASQUERADE",
    ]

    print(scripts)

    # Add IPv6-specific configuration
    if address_version == "IPv6":
        scripts.extend(
            [
                # Enable IPv6 forwarding globally and on interfaces
                "sysctl -w net.ipv6.conf.all.forwarding=1",
                "sysctl -w net.ipv6.conf.default.forwarding=1",
                "sysctl -w net.ipv6.conf.eth0.forwarding=1",
                f"sysctl -w net.ipv6.conf.{interface_name}.forwarding=1",
                # Enable accepting local addresses (critical for L3S with local routes)
                "sysctl -w net.ipv6.conf.all.accept_local=1",
                f"sysctl -w net.ipv6.conf.{interface_name}.accept_local=1",
                # Disable RA (Router Advertisement) on dummy to prevent conflicts
                f"sysctl -w net.ipv6.conf.{interface_name}.accept_ra=0",
                # Enable NDP proxy for proper neighbor resolution
                f"sysctl -w net.ipv6.conf.{interface_name}.proxy_ndp=1",
            ]
        )
    run_az(
        [
            "vm",
            "run-command",
            "invoke",
            "--resource-group",
            node_rg,
            "--name",
            vm_name,
            "--command-id",
            "RunShellScript",
            "--scripts",
            " & ".join(scripts),
        ]
    )


def derive_range(ip_addr, address_version="IPv4"):
    if address_version == "IPv6":
        network = ipaddress.IPv6Network(ip_addr, strict=False)
    else:
        network = ipaddress.IPv4Network(ip_addr, strict=False)

    if network.num_addresses <= 2:
        raise ValueError("Prefix too small for usable host range")
    start = network.network_address + 1
    end = network.broadcast_address - 1
    return f"{start} {end}"


def ensure_ipvlan_ipconfig(node_rg, nic, address_version, prefix_length):
    nic_name = nic["name"]
    ipvlan_cfg = next(
        (cfg for cfg in nic["ip_configs"] if cfg["name"] == "ipvlan"), None
    )
    if ipvlan_cfg:
        print(f"Found ipvlan IP config for NIC {nic_name} in {node_rg}...")
        return ipvlan_cfg
    primary_cfg = next((cfg for cfg in nic["ip_configs"] if cfg.get("primary")), None)
    if not primary_cfg:
        print(f"Unable to determine primary IP config for NIC {nic_name}; skipping.")
        return None
    subnet_id = primary_cfg.get("subnet_id")
    if not subnet_id:
        print(f"Unable to determine subnet for NIC {nic_name}; skipping.")
        return None
    ipv6_cfg = next(
        (cfg for cfg in nic["ip_configs"] if cfg["name"] == "ipv6config"), None
    )
    print(address_version, ipv6_cfg)
    if address_version == "IPv6" and ipv6_cfg:
        run_az(
            [
                "network",
                "nic",
                "ip-config",
                "delete",
                "--resource-group",
                node_rg,
                "--nic-name",
                nic_name,
                "--name",
                "ipv6config",
            ]
        )
    print(f"Creating ipvlan IP config for NIC {nic_name} in {node_rg}...")
    run_az(
        [
            "network",
            "nic",
            "ip-config",
            "create",
            "--resource-group",
            node_rg,
            "--nic-name",
            nic_name,
            "--name",
            "ipvlan",
            "--subnet",
            subnet_id,
            "--private-ip-address-version",
            address_version,
            "--private-ip-address-prefix-length",
            str(prefix_length),
        ]
    )
    created_cfg = json.loads(
        run_az(
            [
                "network",
                "nic",
                "ip-config",
                "show",
                "--resource-group",
                node_rg,
                "--nic-name",
                nic_name,
                "--name",
                "ipvlan",
                "-o",
                "json",
            ]
        )
    )
    subnet_id = (created_cfg.get("subnet") or {}).get("id", "")
    ipvlan_cfg = {
        "name": created_cfg.get("name", "ipvlan"),
        "primary": bool(created_cfg.get("primary")),
        "ip": created_cfg.get("privateIPAddress", ""),
        "subnet_id": subnet_id,
        "subnet_prefix": subnet_prefix_for(subnet_id),
    }
    nic["ip_configs"].append(ipvlan_cfg)
    print(f"Created ipvlan IP config on {nic_name}.")
    return ipvlan_cfg


def main():
    parser = argparse.ArgumentParser(description="Sync ipvlan configs for AKS nodes.")
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--cluster-name", required=True)
    parser.add_argument("--address-version", type=str, default="IPv4")
    parser.add_argument("--ipvlan-prefix-length", type=int, default=28)
    parser.add_argument("--boostrap-cni-config", type=bool, default=False)
    args = parser.parse_args()

    node_rg = run_az(
        [
            "aks",
            "show",
            "-g",
            args.resource_group,
            "-n",
            args.cluster_name,
            "--query",
            "nodeResourceGroup",
            "-o",
            "tsv",
        ]
    )
    if not node_rg:
        raise RuntimeError(
            f"Unable to determine node resource group for {args.cluster_name}"
        )

    print(f"Scanning NICs for node resource group {node_rg}.")
    nic_views = scan_node_nics(node_rg)
    for nic in nic_views:
        nic_name = nic["name"]
        vm_name = nic["vm_name"]
        if not vm_name:
            print(f"NIC {nic_name} is detached; skipping CNI config push.")
            continue
        ipvlan_cfg = ensure_ipvlan_ipconfig(
            node_rg, nic, args.address_version, args.ipvlan_prefix_length
        )
        if not ipvlan_cfg:
            print(
                f"NIC {nic_name} does not yet have an ipvlan IP config; skipping CNI config push."
            )
            continue
        if args.boostrap_cni_config:
            boostrap_cni_config(
                node_rg, nic_name, vm_name, ipvlan_cfg, args.address_version
            )


if __name__ == "__main__":
    main()
