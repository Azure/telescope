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
        vm = nic.get("virtualMachine") or {}
        vm_id = vm.get("id", "")
        vm_name = vm_id.split("/")[-1] if vm_id else ""
        ip_configs = []
        for cfg in nic.get("ipConfigurations") or []:
            cfg_name = cfg.get("name", "")
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


def boostrap_cni_config(
    node_rg, nic_name, vm_name, ipvlan_cfgs, address_version="IPv4"
):
    if not vm_name or vm_name == "null":
        print(f"NIC {nic_name} not attached to a VM; skipping CNI config.")
        return
    if not ipvlan_cfgs:
        print(f"NIC {nic_name} missing ipvlan metadata; skipping.")
        return

    default_route = "::/0" if address_version == "IPv6" else "0.0.0.0/0"
    iptables_cmd = "ip6tables" if address_version == "IPv6" else "iptables"
    cni_name = "ipvlan-eth0"
    interface_name = "eth0"

    subnets = []
    scripts = []
    for ipvlan_cfg in ipvlan_cfgs:
        ipvlan_cidr = ipvlan_cfg.get("ip")
        if not ipvlan_cidr:
            print(f"Unable to read ipvlan IP for NIC {nic_name}; skipping.")
            return
        subnet_prefix = ipvlan_cfg.get("subnet_prefix")
        if not subnet_prefix:
            print(f"Unable to read subnet prefix for NIC {subnet_prefix}; skipping.")
            return
        start, end = derive_range(ipvlan_cidr, address_version).split()
        subnet_map = {
            "subnet": ipvlan_cidr,
            "rangeStart": start,
            "rangeEnd": end,
        }
        subnets.append(subnet_map)
        scripts.append(f"ip addr replace {ipvlan_cidr} dev {interface_name}")
        scripts.append(
            f"{iptables_cmd} -t nat -A POSTROUTING -s {ipvlan_cidr} ! -d {subnet_prefix} -j MASQUERADE"
        )

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
    print(f"Generated ipvlan CNI config: {json.dumps(config, indent=2)}")
    ipvlan_payload = base64.b64encode(json.dumps(config, indent=2).encode()).decode()

    scripts.append(
        f"echo {ipvlan_payload} | base64 -d | tee /etc/cni/net.d/01-{cni_name}.conf"
    )

    print(scripts)
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


def ensure_ipvlan_ipconfig(node_rg, nic, address_version, config_count):
    nic_name = nic["name"]
    ipvlan_cfgs = [
        cfg for cfg in nic["ip_configs"] if cfg["name"].startswith("ipvlan")
    ]
    if ipvlan_cfgs and len(ipvlan_cfgs) == config_count:
        print(
            f"Found {len(ipvlan_cfgs)} ipvlan IP config(s) for NIC {nic_name} in {node_rg}..."
        )
        return ipvlan_cfgs
    primary_cfg = next((cfg for cfg in nic["ip_configs"] if cfg.get("primary")), None)
    if not primary_cfg:
        print(f"Unable to determine primary IP config for NIC {nic_name}; skipping.")
        return None
    subnet_id = primary_cfg.get("subnet_id")
    if not subnet_id:
        print(f"Unable to determine subnet for NIC {nic_name}; skipping.")
        return None
    print(
        f"Creating {config_count} ipvlan IP configs for NIC {nic_name} in {node_rg}..."
    )
    for i in range(config_count):
        config_name = f"ipvlan{i+1}"
        prefix_length = 28 if address_version == "IPv4" else 80
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
                config_name,
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
                    config_name,
                    "-o",
                    "json",
                ]
            )
        )
        subnet_id = (created_cfg.get("subnet") or {}).get("id", "")
        ipvlan_cfg = {
            "name": created_cfg.get("name", ""),
            "primary": bool(created_cfg.get("primary")),
            "ip": created_cfg.get("privateIPAddress", ""),
            "subnet_id": subnet_id,
            "subnet_prefix": subnet_prefix_for(subnet_id),
        }
        ipvlan_cfgs.append(ipvlan_cfg)
        print(f"Created ipvlan IP config on {nic_name}: {ipvlan_cfg}")
    return ipvlan_cfgs


def main():
    parser = argparse.ArgumentParser(description="Sync ipvlan configs for AKS nodes.")
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--cluster-name", required=True)
    parser.add_argument("--address-version", type=str, default="IPv4")
    parser.add_argument("--ipvlan-config-count", type=int, default=1)
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
        ipvlan_cfgs = ensure_ipvlan_ipconfig(
            node_rg, nic, args.address_version, args.ipvlan_config_count
        )
        if not ipvlan_cfgs:
            print(
                f"NIC {nic_name} does not yet have ipvlan IP config; skipping CNI config push."
            )
            continue
        if args.boostrap_cni_config:
            boostrap_cni_config(
                node_rg, nic_name, vm_name, ipvlan_cfgs, args.address_version
            )


if __name__ == "__main__":
    main()
