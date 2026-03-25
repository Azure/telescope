---
name: telescope-python-test
description: >
  Run Python tests for the telescope project under modules/python. Use this skill
  whenever the user asks to test Python, run Python tests, run pytest, test
  or validate Python changes in the telescope repo. Also triggers for "does the
  Python still work", "check the tests", or any request to verify the modules/python
  code is healthy.
---

# Telescope Python Test Runner

The Python module lives at `modules/python/` and uses a local virtualenv for isolation.
The package must be installed in editable mode before tests can be discovered, because
`pyproject.toml` restricts packages to an installed path.

## Steps

Run all four commands in sequence from the repo root or from within `modules/python/`.
The working directory for all commands is `modules/python/`.

```bash
cd modules/python

# 1. Create virtualenv (safe to re-run; skips if .venv already exists)
python3 -m venv .venv

# 2. Install dependencies
.venv/bin/pip install -q -r requirements.txt

# 3. Install the package itself in editable mode (required for imports)
.venv/bin/pip install -e .

# 4. Run tests
PYTHONPATH=. .venv/bin/python -m pytest tests -v
```

## Notes

- **Why `PYTHONPATH=.`?** Ensures sibling packages like `clients/` and `utils/` resolve
  correctly even for code that imports them directly (e.g. `from utils.constants import UrlConstants`).
- **Re-running:** If `.venv` already exists and deps haven't changed, you can skip steps 1–3
  and go straight to step 4.
- **Test location:** All tests live under `tests`.