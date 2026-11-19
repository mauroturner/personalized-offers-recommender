"""The control group the site promises, measured as far as the data allows (Online Retail II, cached by s01).

The archive records purchases only: no offer was sent, no customer was held out, no campaign flag exists.
So no uplift can be estimated here. This script does what the data can support:
1. Population: the customers active in the 90 days before the cut 2011-06-01 (same cut as s03).
2. A seeded random holdout (20 %, seed 0) that a real operation would set aside, and its balance on
   pre-cut covariates (standardised mean differences).
3. An A/A check: the holdout split is applied to outcomes that no offer touched. Across 500 seeds the
   two-sided 95 % test should reject about 5 % of the time; the script reports the rate.
4. The minimum detectable difference (MDE) for this population and holdout size, from the observed outcome
   variance (alpha 0.05 two-sided, power 0.80). It is a planning number for the size of an operation, not an
   effect: no lift is assumed anywhere.
Writes data/interim/s04_control.json. Run from any directory:  python -I research/s04_control.py
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT = Path(__file__).resolve().parents[1]
ANALYSIS = PROJECT / "data" / "interim" / "analysis.parquet"
OUT = PROJECT / "data" / "interim" / "s04_control.json"
PRODUCT_CODE = re.compile(r"^\d{5}[A-Za-z]{0,3}$")
CUT = pd.Timestamp("2011-06-01")
HORIZON = pd.Timedelta(days=90)
HOLDOUT = 0.20
SEED = 0
SEEDS = 500
Z_ALPHA = 1.959964
Z_POWER = 0.841621


def build_population():
    df = pd.read_parquet(ANALYSIS)
    inv = df["Invoice"].astype(str)
    product = df["StockCode"].astype(str).str.match(PRODUCT_CODE)
    purchase = (df["Quantity"] > 0) & (df["Price"] > 0) & product & ~inv.str.startswith("C") & ~inv.str.startswith("A")
    p = pd.DataFrame({"invoice": inv[purchase], "date": df.loc[purchase, "InvoiceDate"],
                      "customer": df.loc[purchase, "Customer ID"],
                      "value": (df.loc[purchase, "Quantity"] * df.loc[purchase, "Price"]).astype(float)})
    p = p[p["customer"].notna()].copy()
    p["customer"] = p["customer"].astype(int)

    before = p[p["date"] < CUT]
    active_ids = before[before["date"] >= CUT - HORIZON]["customer"].unique()
    g = before.groupby("customer").agg(prior_invoices=("invoice", "nunique"), last=("date", "max"),
                                       prior_value=("value", "sum"))
    pop = g.loc[np.sort(active_ids)].copy()
    pop["recency_days"] = (CUT - pop["last"]).dt.total_seconds() / 86400
    window = p[(p["date"] >= CUT) & (p["date"] < CUT + HORIZON)]
    win = window.groupby("customer").agg(n=("invoice", "size"), value=("value", "sum"))
    pop["buys_in_window"] = pop.index.isin(win.index).astype(float)
    pop["value_in_window"] = win["value"].reindex(pop.index).fillna(0.0).to_numpy()
    return pop.drop(columns=["last"])


def smd(x, t, c):
    pooled = np.sqrt((x[t].var(ddof=1) + x[c].var(ddof=1)) / 2)
    return float((x[t].mean() - x[c].mean()) / pooled) if pooled > 0 else 0.0


def main():
    pop = build_population()
    n = len(pop)
    n_t = int(round(HOLDOUT * n))
    res = {"cut": str(CUT.date()), "horizon_days": int(HORIZON.days), "population_active_90_days": int(n),
           "holdout_share": HOLDOUT, "holdout_size": n_t, "seed": SEED}
    print(f"[population] customers active in the 90 days before {CUT.date()}: {n}; holdout {HOLDOUT:.0%} = {n_t}")

    rng = np.random.default_rng(SEED)
    treated = np.zeros(n, dtype=bool)
    treated[rng.choice(n, size=n_t, replace=False)] = True
    res["balance_smd"] = {}
    for col in ["prior_invoices", "recency_days", "prior_value"]:
        x = pop[col].to_numpy(float)
        res["balance_smd"][col] = round(smd(pd.Series(x), treated, ~treated), 4)
    print(f"[balance] standardised mean differences (|SMD| < 0.1 is usual): "
          + ", ".join(f"{k} {v:+.3f}" for k, v in res["balance_smd"].items()))

    y_any = pop["buys_in_window"].to_numpy(float)
    y_val = pop["value_in_window"].to_numpy(float)
    res["outcome_rates"] = {
        "any_purchase_in_window": round(float(y_any.mean()), 4),
        "value_per_customer_in_window_gbp": round(float(y_val.mean()), 2),
        "value_sd_gbp": round(float(y_val.std(ddof=1)), 2),
        "value_median_gbp": round(float(np.median(y_val)), 2),
    }
    print(f"[outcomes] any purchase in the 90 days {res['outcome_rates']['any_purchase_in_window'] * 100:.1f} %; "
          f"value per customer mean {res['outcome_rates']['value_per_customer_in_window_gbp']} GBP, "
          f"sd {res['outcome_rates']['value_sd_gbp']} GBP, median {res['outcome_rates']['value_median_gbp']} GBP")

    def diff_test(y, t):
        a, b = y[t], y[~t]
        d = a.mean() - b.mean()
        se = np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
        return float(d), float(se)

    d_any, se_any = diff_test(y_any, treated)
    d_val, se_val = diff_test(y_val, treated)
    res["aa_one_split"] = {
        "any_purchase_diff": round(d_any, 4), "any_purchase_ci95": [round(d_any - 1.96 * se_any, 4), round(d_any + 1.96 * se_any, 4)],
        "value_diff_gbp": round(d_val, 2), "value_ci95_gbp": [round(d_val - 1.96 * se_val, 2), round(d_val + 1.96 * se_val, 2)],
    }
    print(f"[A/A seed {SEED}] any purchase: difference {d_any * 100:+.2f} points, 95 % CI "
          f"{(d_any - 1.96 * se_any) * 100:+.2f} to {(d_any + 1.96 * se_any) * 100:+.2f}; value: "
          f"{d_val:+.2f} GBP, 95 % CI {d_val - 1.96 * se_val:+.2f} to {d_val + 1.96 * se_val:+.2f}")

    reject_any = 0
    reject_val = 0
    for s in range(SEEDS):
        r = np.random.default_rng(1000 + s)
        t = np.zeros(n, dtype=bool)
        t[r.choice(n, size=n_t, replace=False)] = True
        da, sa = diff_test(y_any, t)
        dv, sv = diff_test(y_val, t)
        reject_any += abs(da) > 1.96 * sa
        reject_val += abs(dv) > 1.96 * sv
    res["aa_calibration"] = {"seeds": SEEDS, "rejection_rate_any_purchase": round(reject_any / SEEDS, 4),
                             "rejection_rate_value": round(reject_val / SEEDS, 4),
                             "nominal": 0.05, "note": "a valid test rejects about 5 % of null splits"}
    print(f"[A/A calibration] {SEEDS} seeded holdouts: rejects {reject_any / SEEDS * 100:.1f} % (any purchase), "
          f"{reject_val / SEEDS * 100:.1f} % (value); nominal 5 %")

    p0 = float(y_any.mean())
    sd_val = float(y_val.std(ddof=1))
    res["mde_by_holdout_share"] = {}
    for share in (0.10, 0.20, 0.30):
        nt = int(round(share * n))
        nc = n - nt
        mde_any = (Z_ALPHA + Z_POWER) * np.sqrt(p0 * (1 - p0) * (1 / nc + 1 / nt))
        mde_val = (Z_ALPHA + Z_POWER) * sd_val * np.sqrt(1 / nc + 1 / nt)
        res["mde_by_holdout_share"][f"{int(share * 100)}%"] = {
            "holdout_size": nt, "mde_any_purchase_points": round(float(mde_any) * 100, 2),
            "mde_any_purchase_relative_to_base": round(float(mde_any / p0), 4),
            "mde_value_gbp_per_customer": round(float(mde_val), 2)}
        print(f"[MDE planning] holdout {share:.0%} ({nt} customers): smallest detectable difference in the "
              f"repeat rate {mde_any * 100:.2f} points ({mde_any / p0 * 100:.0f} % of the base {p0 * 100:.1f} %); "
              f"in value {mde_val:.2f} GBP per customer")

    res["what_offline_data_cannot_measure"] = [
        "any effect of an offer: no offer, campaign or holdout exists in the archive",
        "whether the customer would have bought the recommended product anyway (no counterfactual)",
        "the offer's cost, response rate or margin, which decide whether a lift pays",
    ]

    OUT.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[out] {OUT.relative_to(PROJECT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
