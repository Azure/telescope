"""Entry point: python -m underlay_profiler --config /etc/profiler/config.yaml [--once]"""

import argparse
import logging
import signal
import threading

from .collector import Collector
from .config import load_config
from .discovery import Guard, K8sDiscovery, StaticDiscovery
from .fetch import Fetcher
from .metrics import Metrics, serve
from .sink import make_sink


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True)
    ap.add_argument("--once", action="store_true", help="run a single cycle and exit")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    cfg = load_config(args.config)
    metrics = Metrics()
    metrics.set("profiler_enabled", 1.0 if cfg.enabled else 0.0)
    serve(metrics, cfg.metrics_port)
    static_only = all(t.static_urls for t in cfg.targets)
    collector = Collector(cfg, StaticDiscovery() if static_only else K8sDiscovery(), Fetcher(),
                          Guard(cfg), make_sink(cfg.sink, metrics), metrics)

    if args.once:
        collector.run_cycle(0)
        return
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    collector.run_forever(args.config, stop)


if __name__ == "__main__":
    main()
