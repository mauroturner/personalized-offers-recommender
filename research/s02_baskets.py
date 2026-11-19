"""Baskets, customers and repeat purchases on Online Retail II (cached by s01).

Definitions (fixed here, reported in the research document):
- purchase line: Quantity > 0, Price > 0, a product-pattern stock code (s01), and an invoice that is neither
  a cancellation (C) nor an adjustment (A);
- purchase invoice: an invoice with at least one purchase line. Its basket is the set of its product codes;
- customer: the Customer ID of the invoice; purchase invoices without a Customer ID are guest baskets.
Writes data/interim/s02_baskets.json. Run from any directory:  python -I research/s02_baskets.py
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT = Path(__file__).resolve().parents[1]
ANALYSIS = PROJECT / "data" / "interim" / "analysis.parquet"
OUT = PROJECT / "data" / "interim" / "s02_baskets.json"
PRODUCT_CODE = re.compile(r"^\d{5}[A-Za-z]{0,3}$")
DCGS = re.compile(r"^DCGS")
COUNT_CUTS = ["2011-06-01", "2011-09-01"]  # the cuts used by s03 and s06 (the test window follows each)


def quant(s, qs=(0.25, 0.5, 0.75, 0.9)):
    return {f"p{int(q * 100)}": round(float(s.quantile(q)), 2) for q in qs}


def main():
    df = pd.read_parquet(ANALYSIS)
    inv = df["Invoice"].astype(str)
    is_cancel = inv.str.startswith("C")
    is_adjust = inv.str.startswith("A")
    product = df["StockCode"].astype(str).str.match(PRODUCT_CODE)
    purchase = (df["Quantity"] > 0) & (df["Price"] > 0) & product & ~is_cancel & ~is_adjust
    p = df.loc[purchase, ["Invoice", "StockCode", "Quantity", "InvoiceDate", "Customer ID", "internal_repeat"]].copy()
    p["Invoice"] = p["Invoice"].astype(str)
    p = p.rename(columns={"Customer ID": "customer"})
    res = {"definitions": {
        "purchase_lines": int(len(p)),
        "purchase_lines_share_of_analysis_rows": round(len(p) / len(df), 4),
    }}
    dcgs_rows = df.loc[df["StockCode"].astype(str).str.match(DCGS) & (df["Quantity"] > 0) & (df["Price"] > 0)
                       & ~is_cancel & ~is_adjust]
    res["dcgs_positive_lines_not_in_product_pattern"] = int(len(dcgs_rows))
    res["dcgs_positive_lines_revenue_gbp"] = round(float((dcgs_rows["Quantity"] * dcgs_rows["Price"]).sum()), 2)
    print(f"[def] purchase lines {len(p)} ({res['definitions']['purchase_lines_share_of_analysis_rows'] * 100:.2f} % "
          f"of analysis rows); DCGS-prefixed positive lines outside the pattern: {len(dcgs_rows)}")

    inv_tab = p.groupby("Invoice").agg(customer=("customer", "first"), date=("InvoiceDate", "min"),
                                       items=("StockCode", "nunique"), units=("Quantity", "sum"))
    inv_tab["guest"] = inv_tab["customer"].isna()
    res["purchase_lines_with_customer"] = int(p["customer"].notna().sum())
    res["customers_with_purchase_line"] = int(p["customer"].dropna().nunique())
    print(f"[def] purchase lines with a customer {res['purchase_lines_with_customer']}; "
          f"customers with a purchase line {res['customers_with_purchase_line']}")
    res["purchase_invoices"] = int(len(inv_tab))
    res["purchase_invoices_guest"] = int(inv_tab["guest"].sum())
    res["purchase_invoices_guest_share"] = round(float(inv_tab["guest"].mean()), 4)
    print(f"[invoices] purchase invoices {len(inv_tab)}; guest (no customer) {int(inv_tab['guest'].sum())} "
          f"({inv_tab['guest'].mean() * 100:.1f} %)")

    named = inv_tab[~inv_tab["guest"]]
    res["basket_items_all"] = quant(inv_tab["items"])
    res["basket_items_customer"] = quant(named["items"])
    res["basket_items_guest"] = quant(inv_tab.loc[inv_tab["guest"], "items"])
    res["basket_units_all"] = quant(inv_tab["units"])
    res["basket_items_mean_all"] = round(float(inv_tab["items"].mean()), 2)
    res["basket_items_1_share"] = round(float((inv_tab["items"] == 1).mean()), 4)
    print(f"[basket] distinct products per purchase invoice: median {inv_tab['items'].median():.0f}, "
          f"mean {inv_tab['items'].mean():.2f}, single-product invoices {res['basket_items_1_share'] * 100:.1f} %")
    print(f"[basket] units per invoice: median {inv_tab['units'].median():.0f}; "
          f"guest basket median items {res['basket_items_guest']['p50']}")

    per_cust = named.groupby("customer").agg(invoices=("items", "size"), first=("date", "min"), last=("date", "max"))
    res["customers_with_purchase"] = int(len(per_cust))
    res["invoices_per_customer"] = quant(per_cust["invoices"], (0.5, 0.75, 0.9, 0.99))
    res["invoices_per_customer_mean"] = round(float(per_cust["invoices"].mean()), 2)
    res["customers_1_invoice_share"] = round(float((per_cust["invoices"] == 1).mean()), 4)
    res["customers_ge2_invoices_share"] = round(float((per_cust["invoices"] >= 2).mean()), 4)
    res["customers_ge3_invoices_share"] = round(float((per_cust["invoices"] >= 3).mean()), 4)
    res["customers_ge5_invoices_share"] = round(float((per_cust["invoices"] >= 5).mean()), 4)
    print(f"[customers] with purchase {len(per_cust)}; invoices per customer median {per_cust['invoices'].median():.0f}, "
          f"mean {per_cust['invoices'].mean():.1f}; 1 invoice {res['customers_1_invoice_share'] * 100:.1f} %, "
          f">=2 {res['customers_ge2_invoices_share'] * 100:.1f} %, >=5 {res['customers_ge5_invoices_share'] * 100:.1f} %")

    prod_inv = p.drop_duplicates(["Invoice", "StockCode"]).groupby("StockCode").size().sort_values(ascending=False)
    res["products_distinct"] = int(len(prod_inv))
    res["products_in_1_invoice"] = int((prod_inv == 1).sum())
    res["products_in_1_invoice_share"] = round(float((prod_inv == 1).mean()), 4)
    res["products_le_5_invoices_share"] = round(float((prod_inv <= 5).mean()), 4)
    total_pl = int(prod_inv.sum())
    cum = prod_inv.cumsum() / total_pl
    for share in (0.01, 0.05, 0.10, 0.20):
        k = int(np.ceil(share * len(prod_inv)))
        res[f"top_{int(share * 100)}pct_products_share_of_invoice_lines"] = round(float(prod_inv.iloc[:k].sum() / total_pl), 4)
    res["products_for_80pct_of_invoice_lines"] = int((cum < 0.8).sum() + 1)
    res["products_for_80pct_share"] = round(float((cum < 0.8).sum() + 1) / len(prod_inv), 4)
    res["top10_products"] = [{"code": str(c), "invoices": int(v)} for c, v in prod_inv.head(10).items()]
    print(f"[items] distinct products {len(prod_inv)}; in one invoice only {res['products_in_1_invoice']} "
          f"({res['products_in_1_invoice_share'] * 100:.1f} %); top 1 % of products hold "
          f"{res['top_1pct_products_share_of_invoice_lines'] * 100:.1f} % of invoice lines; "
          f"{res['products_for_80pct_of_invoice_lines']} products make 80 % "
          f"({res['products_for_80pct_share'] * 100:.1f} % of the catalogue)")

    # Repeat purchases: a customer's (customer, product) pair seen in more than one of their invoices
    cp = p.loc[p["customer"].notna()].drop_duplicates(["Invoice", "StockCode"]).copy()
    cp["customer"] = cp["customer"].astype(int)
    pairs = cp.groupby(["customer", "StockCode"]).size()
    res["customer_product_pairs"] = int(len(pairs))
    res["pairs_bought_more_than_once_share"] = round(float((pairs >= 2).mean()), 4)
    cp = cp.sort_values(["customer", "InvoiceDate"])
    cp["seen_before"] = cp.groupby(["customer", "StockCode"]).cumcount() > 0
    res["lines_that_repeat_a_customers_earlier_product_share"] = round(float(cp["seen_before"].mean()), 4)
    print(f"[repeat] customer-product pairs {len(pairs)}; bought in more than one invoice "
          f"{res['pairs_bought_more_than_once_share'] * 100:.1f} %; purchase lines that repeat an earlier product "
          f"of the same customer {res['lines_that_repeat_a_customers_earlier_product_share'] * 100:.1f} %")

    # Inter-purchase times between consecutive invoices of one customer (days, invoice timestamps)
    named_sorted = named.reset_index().sort_values(["customer", "date"])
    gaps = named_sorted.groupby("customer")["date"].diff().dt.total_seconds().dropna() / 86400
    res["inter_purchase_days"] = {"n_gaps": int(len(gaps)), **{k: round(float(v), 2) for k, v in
                                                              gaps.quantile([0.25, 0.5, 0.75, 0.9]).items()}}
    res["inter_purchase_days"]["mean"] = round(float(gaps.mean()), 2)
    res["inter_purchase_days_within_90"] = round(float((gaps <= 90).mean()), 4)
    print(f"[gaps] consecutive invoices {len(gaps)}; days median {gaps.median():.1f}, p75 {gaps.quantile(0.75):.1f}, "
          f"p90 {gaps.quantile(0.9):.1f}; gap <= 90 days {res['inter_purchase_days_within_90'] * 100:.1f} %")

    # History available at each cut: enough prior purchase invoices to personalise, and active in the 90 days before
    res["history_at_cuts"] = {}
    for cut in COUNT_CUTS:
        cut_ts = pd.Timestamp(cut)
        before = named[named["date"] < cut_ts]
        n_before = before.groupby("customer").size()
        active = before[before["date"] >= cut_ts - pd.Timedelta(days=90)].groupby("customer").size()
        distinct_products = cp[cp["InvoiceDate"] < cut_ts].groupby("customer")["StockCode"].nunique()
        entry = {
            "customers_with_any_prior_invoice": int(len(n_before)),
            "customers_with_ge2_prior_invoices": int((n_before >= 2).sum()),
            "customers_with_ge3_prior_invoices": int((n_before >= 3).sum()),
            "customers_active_last_90_days": int(len(active)),
            "customers_active_last_90_days_with_ge2_prior_invoices": int(((n_before >= 2) & n_before.index.isin(active.index)).sum()),
            "customers_with_ge5_distinct_products_before_cut": int((distinct_products >= 5).sum()),
        }
        res["history_at_cuts"][cut] = entry
        print(f"[history] cut {cut}: any prior invoice {entry['customers_with_any_prior_invoice']}, "
              f">=2 prior {entry['customers_with_ge2_prior_invoices']}, active 90 days {entry['customers_active_last_90_days']}, "
              f">=2 prior and active {entry['customers_active_last_90_days_with_ge2_prior_invoices']}, "
              f">=5 distinct products {entry['customers_with_ge5_distinct_products_before_cut']}")

    OUT.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[out] {OUT.relative_to(PROJECT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
