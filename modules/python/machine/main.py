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
import json
import os
import sys

from clients.aks_machine_client import AKSMachineClient
from machine.collect import collect_results
from machine.data_classes import MachineConfig
from machine.machine_manager import MachineManager
from utils.common import str2bool
from utils.logger_config import setup_logging, get_logger

logger = get_logger(__name__)


def _env_int_override(name: str, default: int) -> int:
    """Return ``int(os.environ[name])`` or ``default`` for empty/unresolved/invalid values."""
    value = os.environ.get(name, "").strip()
    if not value or value.startswith("$("):
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_bool_override(name: str, default: bool) -> bool:
    """Return ``str2bool(os.environ[name])`` or ``default`` for empty/unresolved/invalid values."""
    value = os.environ.get(name, "").strip()
    if not value or value.startswith("$("):
        return default
    try:
        return str2bool(value)
    except argparse.ArgumentTypeError:
        return default


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for the create / scale / collect subcommands."""
    parser = argparse.ArgumentParser(
        description="AKS Machine API CRUD perf test")
    sub = parser.add_subparsers(dest="command", required=True)

    def _common(subparser):
        subparser.add_argument("--cloud", choices=["azure"], required=True)
        subparser.add_argument("--run-id", required=True, dest="run_id")
        subparser.add_argument("--region", dest="region")
        subparser.add_argument("--resource-group", dest="resource_group")
        subparser.add_argument("--node-pool-name", dest="agentpool_name", required=True)
        subparser.add_argument("--vm-size", dest="vm_size", default="Standard_D2_v3")
        subparser.add_argument(
            "--scale-machine-count", dest="scale_machine_count", type=int, default=0)
        subparser.add_argument("--machine-workers", dest="machine_workers", type=int, default=1)
        subparser.add_argument(
            "--use-batch-api", dest="use_batch_api", type=str2bool, default=False)
        subparser.add_argument("--step-timeout", dest="step_timeout", type=int, default=600)
        subparser.add_argument(
            "--result-dir", dest="result_dir", default=os.environ.get("RESULT_DIR"))
        subparser.add_argument("--tags", dest="tags_json", default=None,
                               help="JSON object string forwarded to ARM machine resource tags.")

    for cmd in ("create", "scale"):
        subparser = sub.add_parser(cmd)
        _common(subparser)
    collect_sp = sub.add_parser("collect")
    collect_sp.add_argument("--cloud", choices=["azure"], required=True)
    collect_sp.add_argument("--run-id", required=True, dest="run_id")
    collect_sp.add_argument(
        "--run-url", dest="run_url", default=os.environ.get("RUN_URL", ""))
    collect_sp.add_argument("--region", dest="region")
    collect_sp.add_argument(
        "--result-dir", dest="result_dir", default=os.environ.get("RESULT_DIR"))
    return parser


def _build_machine_config(args) -> MachineConfig:
    """Translate parsed CLI args + env overrides into a MachineConfig dataclass."""
    if not args.result_dir:
        raise SystemExit("--result-dir or RESULT_DIR env must be set")
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
    """CLI entrypoint. Returns process exit code (0 success, 1 unexpected error)."""
    setup_logging()
    try:
        args = build_parser().parse_args(argv)
        if args.command == "collect":
            return collect_results(
                run_id=args.run_id, run_url=args.run_url,
                region=args.region, result_dir=args.result_dir)
        cfg = _build_machine_config(args)
        client = AKSMachineClient(
            resource_group=cfg.resource_group, cluster_name=None,
            result_dir=cfg.result_dir, operation_timeout_minutes=max(1, cfg.timeout // 60),
        )
        discovered = client.get_cluster_name()
        cfg2 = MachineConfig(**{**cfg.__dict__, "cluster_name": discovered})
        MachineManager(client, cfg2).perform_operation()
        return 0
    except Exception:  # pylint: disable=broad-except
        logger.critical("Unhandled error in machine.main", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
