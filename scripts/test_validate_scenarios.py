#!/usr/bin/env python3
"""Tests for validate_scenarios.py (the thin /generate_yaml cross-scenario gate).

Run with: python3 scripts/test_validate_scenarios.py
"""

import os
import tempfile
import unittest

from validate_scenarios import (
    extract_path_refs,
    ref_owner,
    find_cycles,
    discover_scenarios,
    build_graph,
    find_scenario_reference_cycles,
    format_kcl_cycle_error,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _write(path: str, content: str = "") -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


class TestExtractPathRefs(unittest.TestCase):
    def test_plain_cl2_manifest_ref(self):
        text = 'cl2Manifest = "kcl/kata_benchmark/cl2.yaml"'
        self.assertEqual(extract_path_refs(text), ["kcl/kata_benchmark/cl2.yaml"])

    def test_pipeline_workspace_prefixed_ref_is_normalized(self):
        text = 'kwokNodeManifest = "$(Pipeline.Workspace)/s/kcl/kata_benchmark/kwok-node.yaml"'
        self.assertEqual(
            extract_path_refs(text), ["kcl/kata_benchmark/kwok-node.yaml"]
        )

    def test_multiple_refs_in_one_blob(self):
        text = (
            'cl2Manifest = "kcl/example_pipeline/cl2.yaml"\n'
            'kwokNodeManifest = "$(Pipeline.Workspace)/s/kcl/example_pipeline/kwok-node.yaml"\n'
        )
        self.assertEqual(
            extract_path_refs(text),
            [
                "kcl/example_pipeline/cl2.yaml",
                "kcl/example_pipeline/kwok-node.yaml",
            ],
        )

    def test_no_kcl_paths_returns_empty(self):
        text = 'name = "Kata Benchmark"\nLOCATION = "westus2"'
        self.assertEqual(extract_path_refs(text), [])

    def test_import_lines_are_not_path_refs(self):
        # Imports use dotted module syntax, not slash paths; must be ignored.
        text = "import lib.scenario\nimport lib.steps.azure"
        self.assertEqual(extract_path_refs(text), [])


class TestRefOwner(unittest.TestCase):
    def setUp(self):
        self.scenarios = {
            "example_pipeline",
            "kata_benchmark",
            "apiserver_benchmark/configmaps100",
        }

    def test_top_level_scenario_owner(self):
        self.assertEqual(
            ref_owner("kcl/kata_benchmark/cl2.yaml", self.scenarios),
            "kata_benchmark",
        )

    def test_nested_scenario_owner(self):
        self.assertEqual(
            ref_owner(
                "kcl/apiserver_benchmark/configmaps100/cl2.yaml", self.scenarios
            ),
            "apiserver_benchmark/configmaps100",
        )

    def test_lib_path_has_no_scenario_owner(self):
        self.assertIsNone(ref_owner("kcl/lib/scenario/foo.yaml", self.scenarios))

    def test_unknown_dir_has_no_owner(self):
        self.assertIsNone(ref_owner("kcl/nope/cl2.yaml", self.scenarios))

    def test_longest_prefix_wins(self):
        scenarios = {"apiserver_benchmark", "apiserver_benchmark/configmaps100"}
        self.assertEqual(
            ref_owner(
                "kcl/apiserver_benchmark/configmaps100/cl2.yaml", scenarios
            ),
            "apiserver_benchmark/configmaps100",
        )


class TestFindCycles(unittest.TestCase):
    def test_simple_two_node_cycle(self):
        graph = {"a": {"b"}, "b": {"a"}}
        cycles = find_cycles(graph)
        self.assertEqual(len(cycles), 1)
        self.assertEqual(set(cycles[0]), {"a", "b"})

    def test_acyclic_graph_has_no_cycles(self):
        graph = {"a": {"b"}, "b": {"c"}, "c": set()}
        self.assertEqual(find_cycles(graph), [])

    def test_three_node_cycle(self):
        graph = {"a": {"b"}, "b": {"c"}, "c": {"a"}}
        cycles = find_cycles(graph)
        self.assertEqual(len(cycles), 1)
        self.assertEqual(set(cycles[0]), {"a", "b", "c"})

    def test_disconnected_acyclic(self):
        graph = {"a": {"b"}, "b": set(), "c": {"d"}, "d": set()}
        self.assertEqual(find_cycles(graph), [])


class TestDiscoverScenarios(unittest.TestCase):
    def test_finds_pipeline_dirs_and_excludes_lib(self):
        with tempfile.TemporaryDirectory() as d:
            kcl = os.path.join(d, "kcl")
            _write(os.path.join(kcl, "example_pipeline", "pipeline.k"))
            _write(os.path.join(kcl, "nested", "deep", "pipeline.k"))
            _write(os.path.join(kcl, "lib", "scenario", "cl2_benchmark.k"))
            # Even a pipeline.k under lib/ must be excluded.
            _write(os.path.join(kcl, "lib", "weird", "pipeline.k"))
            self.assertEqual(
                discover_scenarios(kcl), {"example_pipeline", "nested/deep"}
            )


class TestBuildGraph(unittest.TestCase):
    def test_cross_scenario_edge_with_self_and_lib_excluded(self):
        with tempfile.TemporaryDirectory() as d:
            kcl = os.path.join(d, "kcl")
            _write(
                os.path.join(kcl, "a", "pipeline.k"),
                'cl2Manifest = "kcl/b/cl2.yaml"\n'
                'kwokNodeManifest = "$(Pipeline.Workspace)/s/kcl/a/own.yaml"\n',
            )
            _write(
                os.path.join(kcl, "b", "pipeline.k"),
                'cl2Manifest = "kcl/lib/scenario/x.yaml"\n',
            )
            _write(os.path.join(kcl, "lib", "scenario", "cl2_benchmark.k"))
            scenarios = discover_scenarios(kcl)
            graph = build_graph(kcl, scenarios)
            self.assertEqual(graph, {"a": {"b"}, "b": set()})


class TestFindScenarioReferenceCycles(unittest.TestCase):
    def test_detects_cross_scenario_cycle(self):
        with tempfile.TemporaryDirectory() as d:
            kcl = os.path.join(d, "kcl")
            _write(
                os.path.join(kcl, "a", "pipeline.k"),
                'cl2Manifest = "kcl/b/cl2.yaml"\n',
            )
            _write(
                os.path.join(kcl, "b", "pipeline.k"),
                'cl2Manifest = "kcl/a/cl2.yaml"\n',
            )
            cycles = find_scenario_reference_cycles(kcl)
            self.assertEqual(len(cycles), 1)
            self.assertEqual(set(cycles[0]), {"a", "b"})

    def test_real_repo_has_no_cross_scenario_cycles(self):
        kcl = os.path.join(REPO_ROOT, "kcl")
        self.assertEqual(find_scenario_reference_cycles(kcl), [])


class TestFormatKclCycleError(unittest.TestCase):
    KCL_CYCLE_STDERR = (
        "error[E1001]: RecursiveLoad\n"
        "Could not compiles due to cyclic import statements\n"
        "- /repo/kcl/aaa/main.k\n"
        "- /repo/kcl/bbb/main.k\n\n"
        "error[E2L23]: CompileError\n"
        " --> /repo/kcl/bbb/main.k:1:1\n"
        "There is a circular reference between modules bbb, aaa\n"
    )

    def test_detects_and_summarizes_cycle(self):
        msg = format_kcl_cycle_error(self.KCL_CYCLE_STDERR)
        self.assertIsNotNone(msg)
        self.assertIn("circular", msg.lower())
        # The friendly message should name the modules involved.
        self.assertIn("bbb", msg)
        self.assertIn("aaa", msg)

    def test_returns_none_for_unrelated_error(self):
        stderr = "error[E2L23]: CompileError\nundefined identifier 'foo'\n"
        self.assertIsNone(format_kcl_cycle_error(stderr))

    def test_returns_none_for_empty(self):
        self.assertIsNone(format_kcl_cycle_error(""))


if __name__ == "__main__":
    unittest.main()
