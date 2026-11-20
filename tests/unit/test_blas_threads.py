"""One thread of BLAS in every run of the flow (RNF01; plan section 2, «el flujo los fija en pipeline.py y el compose en el entorno»; B3 of the independent evaluation, D47).

With more than one thread, OpenBLAS sums in another order and the refitted scores of a round change in their last bits: a rebuild (runbook R11) then gives ``offer_lists`` with other bytes, and
re-emitting a round that was issued raises ``ScoringError``. ``tests/conftest.py`` sets the variables for the suite; these tests run a process of their own **without** them, so they see what the
command line and the DAG get. The library reads the variable when it is loaded, so ``personaloffers.pipeline`` has to set it before its first import loads numpy, scipy or implicit."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
VARIABLES = ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")
PROBE = """
import json, os, sys
import personaloffers.pipeline
from threadpoolctl import threadpool_info
blas = [{"api": i["user_api"], "library": i["internal_api"], "threads": i["num_threads"]} for i in threadpool_info() if i["user_api"] == "blas"]
print(json.dumps({"env": {name: os.environ.get(name) for name in %r}, "blas": blas}))
""" % (VARIABLES,)


def _probe(**environment: str) -> dict:
    """What a fresh process sees after ``import personaloffers.pipeline``: the two variables and every BLAS library loaded, with its threads."""
    env = {k: v for k, v in os.environ.items() if k not in VARIABLES}
    env |= {"PYTHONPATH": str(PROJECT / "src"), **environment}
    done = subprocess.run([sys.executable, "-c", PROBE], cwd=PROJECT, env=env, capture_output=True, text=True, timeout=120, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_importing_the_pipeline_sets_one_thread_of_blas_before_numpy_loads_it():
    seen = _probe()
    assert seen["env"] == dict.fromkeys(VARIABLES, "1")
    assert seen["blas"] and {b["threads"] for b in seen["blas"]} == {1}, seen["blas"]


def test_a_value_from_outside_does_not_give_the_flow_more_threads():
    """The flow's lists must be the same bytes on any machine: a larger value set by the shell is replaced, not kept."""
    seen = _probe(OPENBLAS_NUM_THREADS="8", MKL_NUM_THREADS="8")
    assert seen["env"] == dict.fromkeys(VARIABLES, "1") and {b["threads"] for b in seen["blas"]} == {1}


def test_the_pipeline_sets_the_variables_before_its_first_import_of_the_package():
    """The order in the source: the assignments come before any ``import`` of ``personaloffers`` (which loads pandas and numpy)."""
    text = (PROJECT / "src" / "personaloffers" / "pipeline.py").read_text(encoding="utf-8")
    first_import = re.search(r"^from personaloffers|^import personaloffers", text, flags=re.MULTILINE).start()
    for name in VARIABLES:
        found = re.search(rf'^os\.environ\["{name}"\] = "1"', text, flags=re.MULTILINE)
        assert found is not None and found.start() < first_import, name


def test_the_compose_file_gives_every_airflow_service_one_thread_of_blas():
    """The DAG imports ``personaloffers.base`` (and with it numpy) before the pipeline, so inside Docker the variables come from the environment of every Airflow service."""
    compose = (PROJECT / "airflow" / "docker-compose.yaml").read_text(encoding="utf-8")
    common = re.search(r"^x-airflow-common:\n(.*?)^services:", compose, flags=re.MULTILINE | re.DOTALL).group(1)
    for name in VARIABLES:
        assert re.search(rf"^    {name}: '1'$", common, flags=re.MULTILINE), name
