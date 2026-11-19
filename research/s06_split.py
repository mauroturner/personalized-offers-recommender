"""Leakage risks and a proposed split for project 08 (Online Retail II, cached by s01).

The proposed split follows project 04's README (launch, deliveries, close), so the two projects can be
compared on the same calendar: launch at 2011-07-31, four monthly deliveries (2011-08 to 2011-11), close
with the nine days of 2011-12. Each risk is measured, not argued:
1. Random invoice split against the time split: share of test invoices whose customer also has training
   invoices dated AFTER the test invoice (information from the future inside the training set).
2. Popularity counted on the full archive (test window included) against training-only counts, on the
   same evaluated customers at the cut 2011-06-01 (hit rate at K = 10).
3. Cancellations: the share of cancelled value (cancellation lines with a customer and a product code) that
   matches an earlier purchase of the same customer and product with enough quantity. P4's README says 95.2 %
   of cancelled value finds its purchase and 713,010 GBP is cancelled; both are re-derived here.
4. Weekly cuts with a 90-day horizon: how many cuts share each test day (the overlap a weekly flow creates).
Writes data/interim/s06_split.json. Run from any directory:  python -I research/s06_split.py
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT = Path(__file__).resolve().parents[1]
ANALYSIS = PROJECT / "data" / "interim" / "analysis.parquet"
OUT = PROJECT / "data" / "interim" / "s06_split.json"
PRODUCT_CODE = re.compile(r"^\d{5}[A-Za-z]{0,3}$")
CUT = pd.Timestamp("2011-06-01")
HORIZON = pd.Timedelta(days=90)
K = 10
SEED = 0

PROPOSED = [
    ("history (launch)", "2009-12-01", "2011-07-31"),
    ("delivery 1", "2011-08-01", "2011-08-31"),
    ("delivery 2", "2011-09-01", "2011-09-30"),
    ("delivery 3", "2011-10-01", "2011-10-31"),
    ("delivery 4", "2011-11-01", "2011-11-30"),
    ("close", "2011-12-01", "2011-12-09"),
]


def main():
    df = pd.read_parquet(ANALYSIS)
    inv = df["Invoice"].astype(str)
    is_c = inv.str.startswith("C")
    product = df["StockCode"].astype(str).str.match(PRODUCT_CODE)
    purchase = (df["Quantity"] > 0) & (df["Price"] > 0) & product & ~is_c & ~inv.str.startswith("A")
    res = {"proposed_split": [], "random_split_future_leak": {}, "popularity_full_archive": {},
           "cancellations": {}, "weekly_cut_overlap": {}}

    print("[split] proposed windows (project 04's calendar)")
    for name, start, end in PROPOSED:
        s, e = pd.Timestamp(start), pd.Timestamp(end) + pd.Timedelta(days=1)
        w = df[(df["InvoiceDate"] >= s) & (df["InvoiceDate"] < e)]
        wp = w[purchase.loc[w.index]]
        entry = {"window": name, "from": start, "to": end, "rows": int(len(w)),
                 "purchase_lines": int(len(wp)), "purchase_invoices": int(wp["Invoice"].nunique()),
                 "customers_with_purchase": int(wp["Customer ID"].dropna().nunique())}
        res["proposed_split"].append(entry)
        print(f"    {name:18s} {start} to {end}: rows {entry['rows']}, purchase lines {entry['purchase_lines']}, "
              f"purchase invoices {entry['purchase_invoices']}, customers {entry['customers_with_purchase']}")

    pur = df[purchase].copy()
    pur["invoice"] = pur["Invoice"].astype(str)
    pur_c = pur[pur["Customer ID"].notna()].copy()
    pur_c["customer"] = pur_c["Customer ID"].astype(int)
    inv_c = pur_c.drop_duplicates("invoice")[["invoice", "customer", "InvoiceDate"]]

    # 1. Random invoice split against the time split
    shuffled = inv_c.sample(frac=1.0, random_state=SEED).reset_index(drop=True)
    cut_n = int(0.8 * len(shuffled))
    train_r, test_r = shuffled.iloc[:cut_n], shuffled.iloc[cut_n:]
    latest_train = train_r.groupby("customer")["InvoiceDate"].max()
    earliest_test = test_r.groupby("customer")["InvoiceDate"].min()
    common = earliest_test.index.intersection(latest_train.index)
    leak_inv = test_r[test_r["customer"].isin(common)]
    future_hits = leak_inv.apply(lambda r: latest_train[r["customer"]] > r["InvoiceDate"], axis=1)
    res["random_split_future_leak"] = {
        "test_invoices": int(len(test_r)),
        "share_test_invoices_with_later_training_invoice_of_same_customer": round(float(future_hits.sum() / len(test_r)), 4),
        "time_split_share": 0.0,
        "note": "a random 80/20 split of purchase invoices lets the model see the customer's later purchases"}
    print(f"[leak] random 80/20 invoice split: {res['random_split_future_leak']['share_test_invoices_with_later_training_invoice_of_same_customer'] * 100:.1f} % "
          f"of test invoices have a later training invoice of the same customer; the time split has 0 %")

    # 2. Popularity on the full archive vs training only, same evaluated customers
    train_inv = pur_c[pur_c["InvoiceDate"] < CUT].drop_duplicates(["invoice", "StockCode"])
    test_win = pur_c[(pur_c["InvoiceDate"] >= CUT) & (pur_c["InvoiceDate"] < CUT + HORIZON)]
    train_users = set(pur_c[pur_c["InvoiceDate"] < CUT]["customer"].unique())
    eval_users = sorted(train_users & set(test_win["customer"].unique()))
    test_sets = test_win[test_win["customer"].isin(eval_users)].groupby("customer")["StockCode"].apply(set).to_dict()
    full_counts = pur_c.drop_duplicates(["invoice", "StockCode"]).groupby("StockCode").size().sort_values(ascending=False)
    train_counts = train_inv.groupby("StockCode").size().sort_values(ascending=False)

    def hit_rate(ranking):
        top = set(ranking[:K])
        hits = sum(1 for u in eval_users if top & test_sets[u])
        return hits / len(eval_users)

    hr_train = hit_rate(list(train_counts.index))
    hr_full = hit_rate(list(full_counts.index))
    res["popularity_full_archive"] = {"eval_users": len(eval_users), "hit_at_10_training_only": round(hr_train, 4),
                                      "hit_at_10_full_archive": round(hr_full, 4),
                                      "note": "the full-archive ranking uses the test window's purchases, so it is leaked"}
    print(f"[leak] popularity hit@10 with training counts {hr_train * 100:.1f} %, with full-archive counts "
          f"{hr_full * 100:.1f} % ({len(eval_users)} customers)")

    # 3. Cancellations: how much cancelled value finds an earlier purchase of the same customer and product
    c = df[is_c & df["Customer ID"].notna() & product].copy()
    c["row_id"] = np.arange(len(c))
    c["customer"] = c["Customer ID"].astype(int)
    c["cancel_qty"] = c["Quantity"].abs()
    c["cancel_value"] = (c["Quantity"] * c["Price"]).abs()
    prior = pur_c[["customer", "StockCode", "InvoiceDate", "Quantity"]].rename(columns={"StockCode": "code_p"})
    merged = c[["row_id", "customer", "StockCode", "InvoiceDate", "cancel_qty", "cancel_value"]].merge(
        prior, left_on=["customer", "StockCode"], right_on=["customer", "code_p"], how="left", suffixes=("", "_p"))
    merged = merged[merged["InvoiceDate_p"] <= merged["InvoiceDate"]]
    enough = merged[merged["Quantity"] >= merged["cancel_qty"]]
    matched_mask = c["row_id"].isin(enough["row_id"].unique()).to_numpy()
    total_value = float(c["cancel_value"].sum())
    res["cancellations"] = {
        "cancel_lines_with_customer_and_product": int(len(c)),
        "cancel_value_gbp": round(total_value, 2),
        "share_value_with_earlier_purchase_of_enough_quantity": round(float(c.loc[matched_mask, "cancel_value"].sum() / total_value), 4),
        "share_lines_matched": round(float(matched_mask.mean()), 4),
        "p4_reported": {"lines": 17641, "value_gbp": 713010, "share_value_matched": 0.952}}
    print(f"[cancel] cancellation lines with customer and product {len(c)}, value {total_value:,.0f} GBP; "
          f"{res['cancellations']['share_value_with_earlier_purchase_of_enough_quantity'] * 100:.1f} % of the value finds an "
          f"earlier purchase with enough quantity (P4 reports 95.2 %)")

    # 4. Weekly cuts with a 90-day horizon: how many cuts share each test day
    cuts = pd.date_range("2011-06-01", "2011-09-01", freq="7D")
    res["weekly_cut_overlap"] = {"weekly_cuts_between_2011_06_01_and_2011_09_01": int(len(cuts)),
                                 "cuts_whose_90_day_test_window_covers_one_day": int(np.ceil(90 / 7)),
                                 "note": "consecutive weekly test windows share about 12 of 13 weeks"}
    print(f"[weekly] {len(cuts)} weekly cuts between 2011-06-01 and 2011-09-01; one day falls in "
          f"{int(np.ceil(90 / 7))} of the 90-day test windows")

    OUT.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[out] {OUT.relative_to(PROJECT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
