"""Planner fact p04: the dry run of the close's A/A and its calibration on the real archive, before the test window (plan section 14: the time of the close is not discovered in the real run).

The plan's test window starts on 2011-08-01. This script never reads a line dated on or after that day: the Parquet of the research is read with a pyarrow filter on InvoiceDate and the script stops if any row
passes it. The close of the plan evaluates, once, the A/A of the launch cohort over the 18 weeks of the test and calibrates the preregistered test on 500 new draws of the control group; the dry run does the
same thing a period earlier, with the package's own ``evaluation.run_experiment`` (the function the close calls) and the sealed configuration (2.000 permutations for the A/A, 500 draws of 500 permutations for
the calibration, 18 weeks and 18 weeks before): the cohort is the base of 2011-03-28, the 18 weeks "of the test" are 2011-03-28 to 2011-07-31 and the 18 before them give CUPED. The seconds are noted so that,
if the calibration passes the plan's 180 s, the next unit corrects it before the real close (plan section 14).

Nothing is written but its own output, which the caller redirects:  python -I research/p04_close_dry_run.py > research/p04.out
Needs data/interim/analysis.parquet (research/s01_structure.py) and the package (PYTHONPATH=src).
"""
import os
import sys
import time
import warnings
from datetime import date, timedelta
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
warnings.simplefilter("ignore")

import pandas as pd
import pyarrow.parquet as pq

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from personaloffers import base, evaluation, experiment, holdout  # noqa: E402
from personaloffers.config import SealedConfig, load_config  # noqa: E402
from personaloffers.lines import assign_roles  # noqa: E402

ANALYSIS = PROJECT / "data" / "interim" / "analysis.parquet"
TEST_START = pd.Timestamp("2011-08-01")
COHORT_MONDAY = date(2011, 3, 28)           # the first Monday of the pseudo-test: 18 Mondays up to 2011-07-25, which ends on 2011-07-31


def canonical_lines(cfg):
    raw = pq.read_table(ANALYSIS, filters=[("InvoiceDate", "<", TEST_START.to_pydatetime())]).to_pandas()
    if len(raw) and raw["InvoiceDate"].max() >= TEST_START:
        raise SystemExit("a line of the test window was read; stop")
    frame = pd.DataFrame({
        "line_key": range(1, len(raw) + 1), "invoice": raw["Invoice"].astype("string"), "stock_code": raw["StockCode"].astype("string"), "description": raw["Description"].astype("string"),
        "quantity": raw["Quantity"].astype("int64"), "invoice_date": raw["InvoiceDate"].astype("datetime64[us]"), "price": raw["Price"].astype("float64"),
        "customer_id": raw["Customer ID"].astype("Int64"), "country": raw["Country"].astype("string"), "internal_repeat": raw["internal_repeat"].astype(bool)})
    frame["role"] = assign_roles(frame, cfg)
    return frame.reset_index(drop=True), str(raw["InvoiceDate"].max())


def main() -> int:
    started = time.perf_counter()
    cfg = load_config(PROJECT / "config" / "pipeline.toml")
    view = SealedConfig.of(cfg, "0" * 64, "1" * 64, "2" * 64)
    lines, last_line = canonical_lines(cfg)
    print(f"[data] lines before {TEST_START.date()}: {len(lines)}; latest line read {last_line}")
    weeks = view.experiment.cuped_weeks
    test_weeks = [COHORT_MONDAY + timedelta(days=7 * n) for n in range(weeks)]
    earlier = experiment.week_mondays(COHORT_MONDAY, weeks)
    assert test_weeks[-1] + timedelta(days=6) < TEST_START.date(), "the pseudo-test ends before the real one starts"
    t = time.perf_counter()
    cov = base.base_table(base.history_before(lines, COHORT_MONDAY), COHORT_MONDAY, view).sort_values("customer_id").reset_index(drop=True)
    assignment = holdout.assign_cohort(cov, view)
    print(f"[cohort] customers with a purchase in the 365 days before {COHORT_MONDAY}: {len(cov)}; control {int((assignment['grp'] == 'control').sum())}; strata {assignment['stratum'].nunique()}; {time.perf_counter() - t:.1f} s")
    t = time.perf_counter()
    figures = evaluation.run_experiment(cov, assignment, lines, test_weeks, earlier, view)
    total = time.perf_counter() - t
    print(f"[balance] max |SMD| {figures['balance']['max_abs_smd']:.3f} ({figures['balance']['covariate']})")
    for metric, outcome in figures["outcomes"].items():
        print(f"[outcome {metric}] mean {outcome['mean']:.4f}, sd {outcome['sd']:.4f}, sd after CUPED {outcome['sd_adjusted']:.4f}, theta {outcome['theta']:.3f}")
    for metric, tests in figures["aa"].items():
        for kind, found in tests.items():
            print(f"[A/A {metric} {kind}] diff {found['diff']:.4f}, p {found['p']:.3f}, 95 % {found['ci_low']:.4f} to {found['ci_high']:.4f}")
    rates = ", ".join(f"{name} {rate * 100:.1f} %" for name, rate in figures["calibration"]["rejection"].items())
    print(f"[calibration] {figures['calibration']['seeds']} draws of {figures['calibration']['permutations']} permutations: {rates}")
    for row in figures["mde"]:
        print(f"[MDE] holdout {row['holdout_share'] * 100:.0f} % ({row['holdout_size']}): M1 {row['mde_m1'] * 100:.2f} points, M2 {row['mde_m2']:.2f} GBP")
    print(f"[timing] A/A, calibration and MDE together {total:.1f} s (the plan's limit for the calibration is 180 s); script total {time.perf_counter() - started:.1f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
