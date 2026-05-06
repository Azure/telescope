import json
import pathlib
import shutil

from machine.collect import collect_results

FIX = pathlib.Path(__file__).parent / "fixtures" / "machine_collect_golden"


def test_collect_matches_golden(tmp_path):
    # Copy fixture inputs to tmp result_dir
    for p in (FIX / "input").iterdir():
        shutil.copy(p, tmp_path / p.name)
    rc = collect_results(cloud="azure", run_id="RID", run_url="http://run/url",
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
