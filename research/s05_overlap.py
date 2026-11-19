"""Overlap with projects 02 and 04, which use the same archive (Online Retail II, cached by s01).

This script does not read the projects' data. It re-derives two numbers their READMEs state, from the
public archive and the definitions their READMEs give, so P8 knows what the same file already supports:
1. P4 (churn): the population of customers with a net purchase in the 90 days before a cut and the share
   with no net purchase in the 90 days after it. P4's README gives 2,017 and 1,918 customers and a churn
   rate of 34.4 % in the two test cuts (2011-08-01 and 2011-09-01). Two proxies are computed: "net" (the sum of
   quantity x price over every line of the customer's invoices, cancellations included, is above 0) and
   "gross" (at least one positive purchase line). Differences from P4 are expected: P4 also applies its own
   data rules, which this proxy does not.
2. P2 (segments): the wholesale rule, median units per line >= 24 with >= 3 lines in the 12 months before
   the launch cut 2011-05-31. P2's README gives 335 wholesale customers and 26.8 % of the window's revenue.
Writes data/interim/s05_overlap.json. Run from any directory:  python -I research/s05_overlap.py
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT = Path(__file__).resolve().parents[1]
ANALYSIS = PROJECT / "data" / "interim" / "analysis.parquet"
OUT = PROJECT / "data" / "interim" / "s05_overlap.json"
PRODUCT_CODE = re.compile(r"^\d{5}[A-Za-z]{0,3}$")
HORIZON = pd.Timedelta(days=90)
P4_CLAIMS = {"2011-08-01": {"customers": 2017, "churn": None}, "2011-09-01": {"customers": 1918, "churn": None}}
P4_PAIR = {"rows": 3935, "churn": 0.344}
P2_LAUNCH = pd.Timestamp("2011-05-31")
P2_CLAIMS = {"wholesale_customers": 335, "revenue_share_window": 0.268}


def main():
    df = pd.read_parquet(ANALYSIS)
    df = df[df["Customer ID"].notna()].copy()
    df["customer"] = df["Customer ID"].astype(int)
    inv = df["Invoice"].astype(str)
    df["value"] = (df["Quantity"] * df["Price"]).astype(float)
    df["is_purchase"] = (df["Quantity"] > 0) & (df["Price"] > 0) & df["StockCode"].astype(str).str.match(PRODUCT_CODE) \
        & ~inv.str.startswith("C") & ~inv.str.startswith("A")
    res = {"p4_replication": {}, "p2_wholesale": {}}

    print("[P4] churn proxy at the test cuts (P4 README: 2,017 and 1,918 customers; 34.4 % over 3,935 rows)")
    rows_total = 0
    churn_total = {"net": 0, "gross": 0}
    for cut_s, claim in P4_CLAIMS.items():
        cut = pd.Timestamp(cut_s)
        before = df[(df["InvoiceDate"] >= cut - HORIZON) & (df["InvoiceDate"] < cut)]
        after = df[(df["InvoiceDate"] >= cut) & (df["InvoiceDate"] < cut + HORIZON)]
        net_before = before.groupby("customer")["value"].sum()
        active_net = net_before[net_before > 0].index
        active_gross = before[before["is_purchase"]]["customer"].unique()
        net_after = after.groupby("customer")["value"].sum()
        gross_after = set(after[after["is_purchase"]]["customer"].unique())
        out = {}
        for variant, population in (("net", active_net), ("gross", active_gross)):
            pop = pd.Index(population)
            if variant == "net":
                kept = pop
                churned = [c for c in kept if not (net_after.get(c, 0.0) > 0)]
            else:
                kept = pop
                churned = [c for c in kept if c not in gross_after]
            rate = len(churned) / len(kept) if len(kept) else float("nan")
            out[variant] = {"customers": int(len(kept)), "churned": int(len(churned)), "churn_rate": round(float(rate), 4)}
            churn_total[variant] += len(churned)
        rows_total += out["net"]["customers"]
        res["p4_replication"][cut_s] = {"p4_customers": claim["customers"], **out}
        print(f"    {cut_s}: net proxy {out['net']['customers']} customers, churn {out['net']['churn_rate'] * 100:.1f} %; "
              f"gross proxy {out['gross']['customers']} customers, churn {out['gross']['churn_rate'] * 100:.1f} % "
              f"(P4 reports {claim['customers']} customers at this cut)")
    res["p4_replication"]["pair_churn_rate"] = {
        "net": round(churn_total["net"] / rows_total, 4) if rows_total else None,
        "gross": round(churn_total["gross"] / sum(v["net"]["customers"] for v in res["p4_replication"].values()
                                                 if isinstance(v, dict) and "net" in v), 4),
        "p4_reported": P4_PAIR["churn"], "p4_rows": P4_PAIR["rows"]}
    print(f"    pooled churn rate: net {res['p4_replication']['pair_churn_rate']['net'] * 100:.1f} %, "
          f"gross {res['p4_replication']['pair_churn_rate']['gross'] * 100:.1f} %; P4 reports 34.4 %")

    print("[P2] wholesale rule at the launch cut 2011-05-31 (P2 README: 335 customers, 26.8 % of the window's revenue)")
    purchases = df[df["is_purchase"]]
    last12 = purchases[(purchases["InvoiceDate"] >= P2_LAUNCH - pd.Timedelta(days=365))
                       & (purchases["InvoiceDate"] < P2_LAUNCH)]
    stats = last12.groupby("customer")["Quantity"].agg(["median", "size"])
    wholesale = stats[(stats["median"] >= 24) & (stats["size"] >= 3)].index
    # P2 says "192 días siguientes": 2011-06-01 to 2011-12-09 inclusive is 192 calendar days
    window = purchases[(purchases["InvoiceDate"] >= pd.Timestamp("2011-06-01"))
                       & (purchases["InvoiceDate"] < pd.Timestamp("2011-12-10"))]
    days = (pd.Timestamp("2011-12-09") - pd.Timestamp("2011-06-01")).days + 1
    share = float(window[window["customer"].isin(wholesale)]["value"].sum() / window["value"].sum())
    res["p2_wholesale"] = {"wholesale_customers": int(len(wholesale)), "window_days": int(days),
                           "revenue_share_window": round(share, 4), "p2_reported": P2_CLAIMS,
                           "rule": "median units per purchase line >= 24 and >= 3 purchase lines in the 12 months before 2011-05-31"}
    print(f"    wholesale customers {len(wholesale)} (P2 reports {P2_CLAIMS['wholesale_customers']}); "
          f"revenue share of 2011-06-01 to 2011-12-09 ({days} days): {share * 100:.1f} % (P2 reports 26.8 %)")

    OUT.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[out] {OUT.relative_to(PROJECT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
