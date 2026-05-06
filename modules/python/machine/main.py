"""CLI entrypoint for the Machine API perf test.

Differences from ado-telescope k8s/main.py:
- kebab-case flags (matches gh-telescope crud/main.py convention).
- Subcommands: create | scale | collect.  No 'delete' (NotImplementedError upstream).
- Drops dead flags: --node-count, --kubernetes-version, --cluster-name (auto-detected),
  --nodepool-type, --workload-test-setting, --feature-name, --batch-size, --machine-name.
- ENV-vs-CLI override factored into _env_int_override / _env_bool_override.
- Filters unresolved $(VAR) ADO substitutions automatically.
"""
import argparse
import os
import sys

from clients.aks_machine_client import AKSMachineClient
from machine.data_classes import MachineConfig
from machine.machine_manager import MachineManager
from machine.collect import collect_results
from utils.common import str2bool
from utils.logger_config import setup_logging, get_logger

logger = get_logger(__name__)


def _env_int_override(name: str, default: int) -> int:
    v = os.environ.get(name, "").strip()
    if not v or v.startswith("$(") or not v.lstrip("-").isdigit():
        return default
    return int(v)


def _env_bool_override(name: str, default: bool) -> bool:
    v = os.environ.get(name, "").strip()
    if not v or v.startswith("$("):
        return default
    try:
        return str2bool(v)
    except Exception:  # pylint: disable=broad-except
        return default


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="AKS Machine API CRUD perf test")
    sub = parser.add_subparsers(dest="command", required=True)

    def _common(p):
        p.add_argument("--cloud", choices=["azure"], required=True)
        p.add_argument("--run-id", required=True, dest="run_id")
        p.add_argument("--region", dest="region")
        p.add_argument("--resource-group", dest="resource_group")
        p.add_argument("--node-pool-name", dest="agentpool_name")
        p.add_argument("--vm-size", dest="vm_size", default="Standard_D2_v3")
        p.add_argument("--scale-machine-count", dest="scale_machine_count", type=int, default=0)
        p.add_argument("--machine-workers", dest="machine_workers", type=int, default=1)
        p.add_argument("--use-batch-api", dest="use_batch_api", type=str2bool, default=False)
        p.add_argument("--step-timeout", dest="step_timeout", type=int, default=600)
        p.add_argument("--result-dir", dest="result_dir", default=os.environ.get("RESULT_DIR"))
        p.add_argument("--tags", dest="tags_json", default=None,
                       help="JSON object string forwarded to ARM machine resource tags.")

    for cmd in ("create", "scale"):
        sp = sub.add_parser(cmd)
        _common(sp)
    sp = sub.add_parser("collect")
    sp.add_argument("--cloud", choices=["azure"], required=True)
    sp.add_argument("--run-id", required=True, dest="run_id")
    sp.add_argument("--run-url", dest="run_url", default=os.environ.get("RUN_URL", ""))
    sp.add_argument("--region", dest="region")
    sp.add_argument("--result-dir", dest="result_dir", default=os.environ.get("RESULT_DIR"))
    return parser


def _build_machine_config(args) -> MachineConfig:
    import json
    tags = json.loads(args.tags_json) if args.tags_json else None
    return MachineConfig(
        cloud=args.cloud,
        cluster_name="",  # discovered by AKSMachineClient.get_cluster_name
        resource_group=args.resource_group or os.environ.get("RUN_ID", ""),
        agentpool_name=args.agentpool_name,
        vm_size=args.vm_size,
        timeout=args.step_timeout,
        result_dir=args.result_dir,
        region=args.region,
        operation=args.command,
        tags=tags,
        scale_machine_count=_env_int_override("ENV_SCALE_MACHINE_COUNT",
                                              default=args.scale_machine_count),
        use_batch_api=_env_bool_override("ENV_USE_BATCH_API",
                                         default=args.use_batch_api),
        machine_workers=_env_int_override("ENV_MACHINE_WORKERS",
                                          default=args.machine_workers),
    )


def main(argv=None) -> int:
    setup_logging()
    args = build_parser().parse_args(argv)
    if args.command == "collect":
        return collect_results(
            cloud=args.cloud, run_id=args.run_id, run_url=args.run_url,
            region=args.region, result_dir=args.result_dir)
    cfg = _build_machine_config(args)
    cluster_name_seed = cfg.cluster_name or None
    client = AKSMachineClient(
        resource_group=cfg.resource_group, cluster_name=cluster_name_seed,
        result_dir=cfg.result_dir, operation_timeout_minutes=max(1, cfg.timeout // 60),
    )
    discovered = client.get_cluster_name()
    cfg2 = MachineConfig(**{**cfg.__dict__, "cluster_name": discovered})
    MachineManager(client, cfg2).perform_operation()
    return 0


if __name__ == "__main__":
    sys.exit(main())
