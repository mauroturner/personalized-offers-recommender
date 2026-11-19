"""Planner fact p02: the prepared control group, measured on a pre-test period only (Online Retail II, cached by s01).

The plan's test window starts on 2011-08-01. This script never reads a line dated on or after that day (pyarrow
filter on InvoiceDate, and a stop if any row passes it).

A pseudo-launch on Monday 2011-04-04 stands in for the plan's launch. Cohort: the customers with at least one
purchase line in the 365 days before it. Covariates at the pseudo-launch: days since the last purchase, invoices
and spend in 365 days, days since the first purchase, and P2's bulk-buyer rule (median units per line >= 24 with
>= 3 lines in 365 days), used only as a stratum. Outcomes over the 17 weeks from 2011-04-04 to 2011-07-31, on which
no offer acted: M1, the share of weeks with a purchase; M2, the spend in GBP (quantity x price of purchase lines).
Pre-period for CUPED: the same two quantities over the 17 weeks before the pseudo-launch.

Holdout: 20 %. Two procedures: simple random and stratified (recency tercile x frequency tercile x bulk flag,
the first round(0.2 n) of a seeded permutation inside each stratum). Balance: standardised mean differences.
Tests of the treated - holdout difference: Welch normal on the raw outcome, Welch normal on the CUPED outcome, and
a stratified permutation test on the CUPED outcome (500 permutations). A/A calibration: 500 seeded stratified
holdouts (seeds 1 to 500), with the rejection rate of each test at alpha 0.05. MDE: alpha 0.05 two-sided, power
0.80, from the outcome's standard deviation (raw and CUPED), for holdouts of 10, 20 and 30 %.
Writes data/interim/plan/p02.json. Run from any directory:  python -I research/p02_control_preperiod.py
"""
import json
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

PROJECT = Path(__file__).resolve().parents[1]
ANALYSIS = PROJECT / "data" / "interim" / "analysis.parquet"
OUT = PROJECT / "data" / "interim" / "plan" / "p02.json"
TEST_START = pd.Timestamp("2011-08-01")
LAUNCH = pd.Timestamp("2011-04-04")
WEEKS = 17
HOLDOUT = 0.20
SEEDS = 500
PERMS = 500
Z = 1.959964 + 0.841621
PRODUCT_CODE = re.compile(r"^\d{5}[A-Za-z]{0,3}$")


def purchase_lines():
    df = pq.read_table(ANALYSIS, filters=[("InvoiceDate", "<", TEST_START.to_pydatetime())]).to_pandas()
    if len(df) and df["InvoiceDate"].max() >= TEST_START:
        raise SystemExit("a line of the test window was read; stop")
    inv = df["Invoice"].astype(str)
    product = df["StockCode"].astype(str).str.match(PRODUCT_CODE)
    mask = (df["Quantity"] > 0) & (df["Price"] > 0) & product & ~inv.str.startswith("C") & ~inv.str.startswith("A")
    mask &= df["Customer ID"].notna()
    p = pd.DataFrame({"invoice": inv[mask], "date": df.loc[mask, "InvoiceDate"],
                      "customer": df.loc[mask, "Customer ID"].astype(int),
                      "qty": df.loc[mask, "Quantity"].astype(float),
                      "value": (df.loc[mask, "Quantity"] * df.loc[mask, "Price"]).astype(float)})
    return p, str(df["InvoiceDate"].max())


def weekly_outcomes(p, start, cohort):
    end = start + pd.Timedelta(weeks=WEEKS)
    w = p[(p["date"] >= start) & (p["date"] < end)].copy()
    w["week"] = ((w["date"] - start) // pd.Timedelta(weeks=1)).astype(int)
    weeks = w.groupby("customer")["week"].nunique().reindex(cohort).fillna(0).to_numpy(float) / WEEKS
    spend = w.groupby("customer")["value"].sum().reindex(cohort).fillna(0).to_numpy(float)
    return weeks, spend


def smd(x, t):
    a, b = x[t], x[~t]
    pooled = np.sqrt((a.var(ddof=1) + b.var(ddof=1)) / 2)
    return float((a.mean() - b.mean()) / pooled) if pooled > 0 else 0.0


def stratified(strata, rng):
    holdout = np.zeros(len(strata), dtype=bool)
    for s in np.unique(strata):
        idx = np.flatnonzero(strata == s)
        k = int(round(HOLDOUT * len(idx)))
        holdout[rng.permutation(idx)[:k]] = True
    return holdout


def simple(n, rng):
    holdout = np.zeros(n, dtype=bool)
    holdout[rng.choice(n, size=int(round(HOLDOUT * n)), replace=False)] = True
    return holdout


def welch(y, holdout):
    a, b = y[~holdout], y[holdout]
    d = a.mean() - b.mean()
    se = np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
    return float(d), float(se)


def cuped(y, x):
    theta = np.cov(y, x, ddof=1)[0, 1] / x.var(ddof=1)
    return y - theta * (x - x.mean()), float(theta)


def permutation_p(y, holdout, groups, rng):
    """Two-sided p-value of the treated - holdout mean difference, permuting the holdout inside each stratum."""
    n = len(y)
    obs = y[~holdout].mean() - y[holdout].mean()
    A = np.zeros((PERMS, n), dtype=bool)
    for idx, k in groups:
        keys = rng.random((PERMS, len(idx)))
        ranks = keys.argsort(axis=1).argsort(axis=1)
        A[:, idx] = ranks < k
    nc = A.sum(axis=1)
    sum_c = A.astype(float) @ y
    diffs = (y.sum() - sum_c) / (n - nc) - sum_c / nc
    return float((np.sum(np.abs(diffs) >= abs(obs) - 1e-12) + 1) / (PERMS + 1)), float(diffs.std(ddof=1))


def main():
    started = time.perf_counter()
    p, max_date = purchase_lines()
    before = p[p["date"] < LAUNCH]
    last = before.groupby("customer")["date"].max()
    cohort = np.sort(last[last >= LAUNCH - pd.Timedelta(days=365)].index.to_numpy())
    n = len(cohort)
    year = before[before["date"] >= LAUNCH - pd.Timedelta(days=365)]
    g = year.groupby("customer")
    cov = pd.DataFrame(index=cohort)
    cov["recency_days"] = ((LAUNCH - last.reindex(cohort)).dt.total_seconds() / 86400).to_numpy()
    cov["invoices_365"] = g["invoice"].nunique().reindex(cohort).to_numpy(float)
    cov["spend_365"] = g["value"].sum().reindex(cohort).to_numpy(float)
    cov["tenure_days"] = ((LAUNCH - before.groupby("customer")["date"].min().reindex(cohort)).dt.total_seconds()
                          / 86400).to_numpy()
    bulk = (g["qty"].median().reindex(cohort) >= 24) & (g["qty"].size().reindex(cohort) >= 3)
    cov["bulk"] = bulk.to_numpy(float)
    rec_t = pd.qcut(cov["recency_days"].rank(method="first"), 3, labels=False).to_numpy()
    frq_t = pd.qcut(cov["invoices_365"].rank(method="first"), 3, labels=False).to_numpy()
    strata = rec_t * 6 + frq_t * 2 + cov["bulk"].to_numpy().astype(int)
    groups = []
    for s in np.unique(strata):
        idx = np.flatnonzero(strata == s)
        groups.append((idx, int(round(HOLDOUT * len(idx)))))
    print(f"[data] lines read before {TEST_START.date()}; latest {max_date}")
    print(f"[cohort] customers with a purchase in the 365 days before {LAUNCH.date()}: {n}; "
          f"bulk buyers {int(cov['bulk'].sum())}; strata {len(groups)} (smallest {min(len(i) for i, _ in groups)})")

    res = {"pseudo_launch": str(LAUNCH.date()), "weeks": WEEKS, "latest_line_read": max_date, "cohort": int(n),
           "bulk_buyers": int(cov["bulk"].sum()), "strata": len(groups), "holdout_share": HOLDOUT}
    cols = list(cov.columns)
    X = {c: cov[c].to_numpy(float) for c in cols}
    for name, proc in (("simple", lambda r: simple(n, r)), ("stratified", lambda r: stratified(strata, r))):
        h0 = proc(np.random.default_rng(0))
        res.setdefault("balance_seed0", {})[name] = {c: round(smd(X[c], h0), 4) for c in cols}
        maxes = []
        for s in range(1, SEEDS + 1):
            h = proc(np.random.default_rng(s))
            maxes.append(max(abs(smd(X[c], h)) for c in cols))
        maxes = np.array(maxes)
        res.setdefault("balance_over_seeds", {})[name] = {
            "max_abs_smd_median": round(float(np.median(maxes)), 4),
            "max_abs_smd_p95": round(float(np.percentile(maxes, 95)), 4),
            "share_of_seeds_with_max_abs_smd_over_0_10": round(float((maxes > 0.10).mean()), 4)}
        print(f"[balance {name}] seed 0: " + ", ".join(f"{c} {v:+.3f}" for c, v in res['balance_seed0'][name].items())
              + f"; over {SEEDS} seeds max |SMD| median {np.median(maxes):.3f}, p95 {np.percentile(maxes, 95):.3f}, "
              f"share over 0.10 {(maxes > 0.10).mean() * 100:.1f} %")

    y1, y2 = weekly_outcomes(p, LAUNCH, cohort)
    x1, x2 = weekly_outcomes(p, LAUNCH - pd.Timedelta(weeks=WEEKS), cohort)
    y1c, th1 = cuped(y1, x1)
    y2c, th2 = cuped(y2, x2)
    res["outcomes"] = {
        "m1_purchase_week_share_mean": round(float(y1.mean()), 4), "m1_sd": round(float(y1.std(ddof=1)), 4),
        "m1_sd_cuped": round(float(y1c.std(ddof=1)), 4), "m1_theta": round(th1, 4),
        "m1_any_purchase_share": round(float((y1 > 0).mean()), 4),
        "m2_spend_mean_gbp": round(float(y2.mean()), 2), "m2_spend_median_gbp": round(float(np.median(y2)), 2),
        "m2_sd_gbp": round(float(y2.std(ddof=1)), 2), "m2_sd_cuped_gbp": round(float(y2c.std(ddof=1)), 2),
        "m2_theta": round(th2, 4),
        "corr_m1_pre": round(float(np.corrcoef(y1, x1)[0, 1]), 4), "corr_m2_pre": round(float(np.corrcoef(y2, x2)[0, 1]), 4)}
    print("[outcomes] " + ", ".join(f"{k} {v}" for k, v in res["outcomes"].items()))

    h0 = stratified(strata, np.random.default_rng(0))
    one = {}
    for label, y in (("m1_raw", y1), ("m1_cuped", y1c), ("m2_raw", y2), ("m2_cuped", y2c)):
        d, se = welch(y, h0)
        one[label] = {"diff": round(d, 4), "ci95_normal": [round(d - 1.96 * se, 4), round(d + 1.96 * se, 4)]}
    for label, y in (("m1_cuped", y1c), ("m2_cuped", y2c)):
        pv, _ = permutation_p(y, h0, groups, np.random.default_rng(10_000))
        one[label]["permutation_p"] = round(pv, 4)
    res["aa_seed0_stratified"] = one
    print("[A/A seed 0, stratified] " + "; ".join(f"{k} {v}" for k, v in one.items()))

    t = time.perf_counter()
    rejects = {k: 0 for k in ("m1_normal_raw", "m1_normal_cuped", "m1_permutation_cuped",
                              "m2_normal_raw", "m2_normal_cuped", "m2_permutation_cuped")}
    perm_sd = {"m1": [], "m2": []}
    for s in range(1, SEEDS + 1):
        h = stratified(strata, np.random.default_rng(s))
        for key, y in (("m1_normal_raw", y1), ("m1_normal_cuped", y1c), ("m2_normal_raw", y2), ("m2_normal_cuped", y2c)):
            d, se = welch(y, h)
            rejects[key] += abs(d) > 1.96 * se
        prng = np.random.default_rng(100_000 + s)
        p1, sd1 = permutation_p(y1c, h, groups, prng)
        p2, sd2 = permutation_p(y2c, h, groups, prng)
        rejects["m1_permutation_cuped"] += p1 < 0.05
        rejects["m2_permutation_cuped"] += p2 < 0.05
        perm_sd["m1"].append(sd1)
        perm_sd["m2"].append(sd2)
    res["aa_calibration"] = {"seeds": SEEDS, "permutations": PERMS, "nominal": 0.05,
                             "binomial_band_95": [round(0.05 - 1.96 * np.sqrt(0.05 * 0.95 / SEEDS), 4),
                                                  round(0.05 + 1.96 * np.sqrt(0.05 * 0.95 / SEEDS), 4)],
                             "rejection_rate": {k: round(v / SEEDS, 4) for k, v in rejects.items()},
                             "seconds": round(time.perf_counter() - t, 2)}
    print(f"[A/A calibration] {SEEDS} stratified holdouts: " + ", ".join(
        f"{k} {v / SEEDS * 100:.1f} %" for k, v in rejects.items()) + f"; {res['aa_calibration']['seconds']} s")

    res["mde"] = {}
    for share in (0.10, 0.20, 0.30):
        nt = int(round(share * n))
        nc = n - nt
        f = Z * np.sqrt(1 / nt + 1 / nc)
        res["mde"][f"{int(share * 100)}%"] = {
            "holdout_size": nt,
            "m1_points_raw": round(float(f * y1.std(ddof=1)) * 100, 2),
            "m1_points_cuped": round(float(f * y1c.std(ddof=1)) * 100, 2),
            "m1_relative_to_mean_cuped": round(float(f * y1c.std(ddof=1) / y1.mean()), 4),
            "m2_gbp_raw": round(float(f * y2.std(ddof=1)), 2), "m2_gbp_cuped": round(float(f * y2c.std(ddof=1)), 2),
            "m2_relative_to_mean_cuped": round(float(f * y2c.std(ddof=1) / y2.mean()), 4)}
        print(f"[MDE] holdout {share:.0%} ({nt}): " + ", ".join(f"{k} {v}" for k, v in res["mde"][f"{int(share * 100)}%"].items()))
    res["mde_20_from_permutation_sd"] = {"m1_points": round(float(Z * np.mean(perm_sd["m1"])) * 100, 2),
                                         "m2_gbp": round(float(Z * np.mean(perm_sd["m2"])), 2)}
    print(f"[MDE 20 % from the permutation distribution] {res['mde_20_from_permutation_sd']}")
    res["seconds_total"] = round(time.perf_counter() - started, 2)
    print(f"[timing] total {res['seconds_total']} s")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[out] {OUT.relative_to(PROJECT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
