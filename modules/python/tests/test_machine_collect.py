import json
import pathlib
import shutil

from machine.collect import collect_results

FIX = pathlib.Path(__file__).parent / "fixtures" / "machine_collect_golden"


def test_collect_matches_golden(tmp_path):
    # Copy fixture inputs to tmp result_dir
    for p in (FIX / "input").iterdir():
        shutil.copy(p, tmp_path / p.name)
    rc = collect_results(run_id="RID", run_url="http://run/url",
                         region="eastus", result_dir=str(tmp_path))
    assert rc == 0
    actual = (tmp_path / "results.json").read_text().splitlines()
    expected = (FIX / "expected_results.json").read_text().splitlines()
    assert len(actual) == len(expected)
    for a, e in zip(actual, expected):
        a_obj, e_obj = json.loads(a), json.loads(e)
        # Drop volatile timestamp before comparing top-level shape
        a_obj.pop("timestamp")
        e_obj.pop("timestamp")
        # Stringified columns: parse before comparing
        for k in ("aks_data", "operation_info", "cloud_info"):
            a_obj[k] = json.loads(a_obj[k])
            e_obj[k] = json.loads(e_obj[k])
        assert a_obj == e_obj


def test_collect_empty_dir_returns_zero(tmp_path):
    rc = collect_results(run_id="RID", run_url="http://run/url",
                         region="eastus", result_dir=str(tmp_path))
    assert rc == 0
    assert not (tmp_path / "results.json").exists()


def test_collect_excludes_existing_results_json(tmp_path):
    for p in (FIX / "input").iterdir():
        shutil.copy(p, tmp_path / p.name)
    # Drop a stale results.json that should NOT be re-ingested
    (tmp_path / "results.json").write_text('{"stale": "should not appear"}\n')
    rc = collect_results(run_id="RID", run_url="http://run/url",
                         region="eastus", result_dir=str(tmp_path))
    assert rc == 0
    lines = (tmp_path / "results.json").read_text().splitlines()
    assert len(lines) == 2  # exactly the 2 input files, not 3
    for line in lines:
        assert "stale" not in line


def test_collect_skips_malformed_payload(tmp_path):
    # Copy one valid input
    valid = FIX / "input" / "create_machine-azure-cl-ap-1714899900.json"
    shutil.copy(valid, tmp_path / valid.name)
    # Add a malformed file (missing "config" key)
    (tmp_path / "scale_machine-azure-cl-bad-1714900100.json").write_text(
        '{"response": {"operation_name": "scale_machine"}}'
    )
    rc = collect_results(run_id="RID", run_url="http://run/url",
                         region="eastus", result_dir=str(tmp_path))
    assert rc == 0
    lines = (tmp_path / "results.json").read_text().splitlines()
    assert len(lines) == 1  # only the valid one
