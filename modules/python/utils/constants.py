from dataclasses import dataclass


@dataclass(frozen=True)
class CommandConstants:
    NETSTAT_CMD = "netstat -s -u | jq -R -s 'split(\"\n\")'"
    LSCPU_CMD = "lscpu --json"
    LSPCI_CMD = "lspci && lsb_release -a"
    IPERF3_VERSION_CMD = "iperf3 --version"
    IP_LINK_CMD = "ip -j -s link show"
