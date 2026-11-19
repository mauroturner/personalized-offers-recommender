"""Planner fact p03: the dry run of the launch and of the first weekly round on the real archive, before the test window (plan section 14: the time of a round is not discovered in the real run).

The plan's test window starts on 2011-08-01. This script never reads a line dated on or after that day: the Parquet of the research is read with a pyarrow filter on InvoiceDate and the script stops if any row
passes it. The launch of the plan is exactly that, the history up to 2011-07-31, so the whole of it runs: the lines are published as the launch delivery, validated and loaded into a scratch warehouse, the
recipe is chosen in the 13 validation rounds (the seconds of each round are noted), the seal is written (into the scratch folder, never into the project's reports), the first round's models are fitted and
registered, and the lists and the baselines of R2011-08-01 are emitted (the weekly round's cost without the follow-up, which needs the week's lines). Nothing of the project is written: the scratch folder is
a new one under the system's temporary folder and its path is not printed.

Writes nothing in the project but its own output, which the caller redirects:  python -I research/p03_launch_dry_run.py > research/p03.out
Needs data/interim/analysis.parquet (research/s01_structure.py) and the package (PYTHONPATH=src).
"""
import dataclasses
import os
import sys
import tempfile
import time
import warnings
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
warnings.simplefilter("ignore")

import pandas as pd
import pyarrow.parquet as pq

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from personaloffers import choose, deliveries, launch, validate, warehouse, weekly  # noqa: E402
from personaloffers import calendar as cal  # noqa: E402
from personaloffers.config import SealedConfig, load_config  # noqa: E402
from personaloffers.lines import assign_roles  # noqa: E402

ANALYSIS = PROJECT / "data" / "interim" / "analysis.parquet"
TEST_START = pd.Timestamp("2011-08-01")


def canonical_lines(cfg):
    table = pq.read_table(ANALYSIS, filters=[("InvoiceDate", "<", TEST_START.to_pydatetime())])
    raw = table.to_pandas()
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
    cfg0 = load_config(PROJECT / "config" / "pipeline.toml")
    lines, last_line = canonical_lines(cfg0)
    print(f"[data] lines before {TEST_START.date()}: {len(lines)}; latest line read {last_line}")
    scratch = Path(tempfile.mkdtemp(prefix="p08_dry_run_"))
    paths = dataclasses.replace(cfg0.paths, **{f.name: scratch / f.name for f in dataclasses.fields(cfg0.paths) if f.name not in ("seal", "dashboard_html", "readme")},
                                seal=scratch / "reports" / "model_seal.json", dashboard_html=scratch / "d.html", readme=scratch / "README.md")
    cfg = dataclasses.replace(cfg0, paths=paths, project_root=scratch)
    view = SealedConfig.of(cfg, "0" * 64, "1" * 64, "2" * 64)
    plan = deliveries.delivery_plan(view)
    spec = plan[0]
    t = time.perf_counter()
    deliveries.publish_delivery(cfg, lines, spec)
    conn = warehouse.connect(cfg.paths.warehouse)
    path = deliveries.delivery_path(cfg, spec)
    report = validate.validate_delivery(spec, path, conn, view, run_key="dry-run")
    print(f"[launch delivery] {spec.delivery_id}: {report.rows} rows published and validated in {time.perf_counter() - t:.1f} s")
    t = time.perf_counter()
    warehouse.load_delivery(conn, spec, deliveries.read_delivery(path), report, "dry-run", started_at=pd.Timestamp("2011-08-01").to_pydatetime(), config_sha256="3" * 64)
    print(f"[load] {time.perf_counter() - t:.1f} s")
    t = time.perf_counter()
    stored = warehouse.read_lines(conn)
    print(f"[read lines back] {len(stored)} rows in {time.perf_counter() - t:.1f} s")

    seconds_per_round: list[tuple[str, float]] = []
    original = choose.round_figures

    def timed(history_lines, monday, recipes, view_):
        begun = time.perf_counter()
        try:
            return original(history_lines, monday, recipes, view_)
        finally:
            seconds_per_round.append((cal.round_id(monday), round(time.perf_counter() - begun, 1)))

    choose.round_figures = timed
    t = time.perf_counter()
    result = launch.run_launch(conn, view, "dry-run", models_dir=cfg.paths.models_dir, seal_path=cfg.paths.seal)
    choose.round_figures = original
    print(f"[launch] mode {result.mode}, {time.perf_counter() - t:.1f} s: " + ", ".join(f"{k} {v} s" for k, v in result.seconds.items()))
    for round_id, seconds in seconds_per_round:
        print(f"    [validation round {round_id}] {seconds} s for {len(choose.candidates_of(view))} candidates")
    figures = result.choice
    print(f"[choice] chosen {figures.chosen.name}: hit@10 on new products {figures.chosen.hit_new:.4f} over {figures.chosen.pairs} pairs, coverage {figures.chosen.coverage:.3f}")
    print("[baselines] " + ", ".join(f"{key} {c.name}" for key, c in sorted(figures.baselines.items())))
    t = time.perf_counter()
    emitted = weekly.emit_round(conn, view, "dry-run", view.calendar.test_first_round, models_dir=cfg.paths.models_dir, seal_path=cfg.paths.seal)
    print(f"[round {emitted.round_id}] base {emitted.base}, offer {emitted.offer}, control {emitted.control}, offer rows {emitted.lists}, baseline rows {emitted.baseline_rows}: "
          f"{time.perf_counter() - t:.1f} s ({', '.join(f'{k} {v} s' for k, v in emitted.seconds.items())}; the round was in the registry already, so the fit is the second one)")
    conn.close()
    print(f"[warehouse] {Path(cfg.paths.warehouse).stat().st_size / 1e6:.0f} MB with the lines of the launch, the base, the lists and the baselines of one round")
    print(f"[timing] total {time.perf_counter() - started:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
