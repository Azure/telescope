#!/usr/bin/env python3
"""Thin cross-scenario validation gate for Telescope v2 scenarios.

KCL's compiler already rejects circular *imports* (error E1001 RecursiveLoad),
so this gate deliberately does NOT re-check import cycles. It covers the blind
spot KCL cannot see: path-string references between scenarios (e.g. one
scenario's ``cl2Manifest`` / ``kwokNodeManifest`` pointing into another
scenario's directory). A cycle of such references is a hard failure.
"""

import os
import re

# Matches a kcl/<...> path fragment embedded in a .k source blob, anchored to a
# boundary so it ignores dotted import statements (which have no slashes).
_PATH_REF_RE = re.compile(r'(?:^|[\s"/])(kcl/[^\s"]*)')

# Matches KCL's "circular reference between modules X, Y" diagnostic.
_KCL_CYCLE_RE = re.compile(
    r"circular reference between modules ([^\n]+)", re.IGNORECASE
)


def extract_path_refs(text: str) -> list[str]:
    """Return all ``kcl/<...>`` path fragments embedded in a .k source blob.

    A leading ``$(Pipeline.Workspace)/s/`` is dropped automatically because the
    match starts at ``kcl/``.
    """
    return _PATH_REF_RE.findall(text)


def ref_owner(path_fragment: str, scenarios: set[str]) -> str | None:
    """Return the scenario directory that owns ``path_fragment``, or None.

    ``scenarios`` are directories relative to ``kcl/`` (e.g. ``kata_benchmark``
    or ``apiserver_benchmark/configmaps100``). The longest matching scenario
    prefix wins so nested scenarios resolve correctly.
    """
    if not path_fragment.startswith("kcl/"):
        return None
    rel = path_fragment[len("kcl/"):]
    best = None
    for s in scenarios:
        if rel == s or rel.startswith(s + "/"):
            if best is None or len(s) > len(best):
                best = s
    return best


def find_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    """Return cycles in a directed graph as lists of nodes (deduped by node set)."""
    cycles: list[list[str]] = []
    seen_sets: set[frozenset] = set()
    visited: set[str] = set()
    stack: list[str] = []
    onstack: set[str] = set()

    def dfs(u: str) -> None:
        visited.add(u)
        stack.append(u)
        onstack.add(u)
        for v in graph.get(u, ()):
            if v in onstack:
                cyc = stack[stack.index(v):]
                key = frozenset(cyc)
                if key not in seen_sets:
                    seen_sets.add(key)
                    cycles.append(list(cyc))
            elif v not in visited:
                dfs(v)
        stack.pop()
        onstack.discard(u)

    for n in graph:
        if n not in visited:
            dfs(n)
    return cycles


def discover_scenarios(kcl_root: str) -> set[str]:
    """Return scenario directories (relative to ``kcl_root``) that contain a
    ``pipeline.k``. Anything under ``lib/`` is excluded."""
    scenarios: set[str] = set()
    for dirpath, _dirnames, filenames in os.walk(kcl_root):
        if "pipeline.k" not in filenames:
            continue
        rel = os.path.relpath(dirpath, kcl_root)
        rel = rel.replace(os.sep, "/")
        if rel == "lib" or rel.startswith("lib/"):
            continue
        scenarios.add(rel)
    return scenarios


def build_graph(kcl_root: str, scenarios: set[str]) -> dict[str, set[str]]:
    """Build the scenario reference graph from path-string references found in
    each scenario's ``.k`` files. Self-references and references into ``lib/``
    are excluded."""
    graph: dict[str, set[str]] = {s: set() for s in scenarios}
    for scenario in scenarios:
        scenario_dir = os.path.join(kcl_root, *scenario.split("/"))
        for name in os.listdir(scenario_dir):
            if not name.endswith(".k"):
                continue
            with open(os.path.join(scenario_dir, name)) as f:
                text = f.read()
            for path_fragment in extract_path_refs(text):
                owner = ref_owner(path_fragment, scenarios)
                if owner is not None and owner != scenario:
                    graph[scenario].add(owner)
    return graph


def find_scenario_reference_cycles(kcl_root: str) -> list[list[str]]:
    """Return cross-scenario path-reference cycles under ``kcl_root``."""
    scenarios = discover_scenarios(kcl_root)
    return find_cycles(build_graph(kcl_root, scenarios))


def format_kcl_cycle_error(stderr: str) -> str | None:
    """If ``stderr`` from ``kcl run`` reports a circular import, return a
    friendly one-line summary; otherwise return None.

    KCL already detects scenario import cycles (error E1001 RecursiveLoad). This
    just reframes that diagnostic in scenario terms so authors get a clear
    pointer during ``/generate_yaml``.
    """
    if "RecursiveLoad" not in stderr:
        return None
    modules = ""
    m = _KCL_CYCLE_RE.search(stderr)
    if m:
        modules = m.group(1).strip()
    summary = "Circular import detected between scenario modules"
    if modules:
        summary += f": {modules}"
    summary += (
        ". Break the cycle so no scenario (transitively) imports itself."
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Cross-scenario validation gate: fails on path-string reference "
            "cycles between Telescope scenarios (a blind spot KCL's own import-"
            "cycle check cannot see)."
        )
    )
    default_kcl = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kcl"
    )
    parser.add_argument(
        "--kcl-root",
        default=default_kcl,
        help="Path to the kcl/ directory (default: <repo>/kcl).",
    )
    args = parser.parse_args(argv)

    cycles = find_scenario_reference_cycles(args.kcl_root)
    if not cycles:
        print("validate_scenarios: OK (no cross-scenario reference cycles)")
        return 0

    print("validate_scenarios: FAILED - cross-scenario reference cycle(s):")
    for cyc in cycles:
        print("  " + " -> ".join(cyc + [cyc[0]]))
    print(
        "\nA scenario's path-string references (cl2Manifest / kwokNodeManifest) "
        "must not form a loop into another scenario's directory."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

