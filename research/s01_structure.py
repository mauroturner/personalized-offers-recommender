"""Structure of Online Retail II: rows per sheet, the duplicated week, cancellations, missing customers,
non-product stock codes, zero and negative prices, countries and the date range.

Reads data/raw/online_retail_II.xlsx (written by s00). It writes two git-ignored caches for the later
scripts: data/interim/lines.parquet (every raw row with its sheet name) and data/interim/analysis.parquet
(the rows after removing the copies of the overlapping week; repeats inside the data are kept and flagged,
as the project 04 README does). It writes data/interim/s01_structure.json with every number printed.
Run from any directory:  python -I research/s01_structure.py
"""
import json
import re
import sys
from pathlib import Path

import pandas as pd

PROJECT = Path(__file__).resolve().parents[1]
RAW = PROJECT / "data" / "raw" / "online_retail_II.xlsx"
INTERIM = PROJECT / "data" / "interim"
LINES = INTERIM / "lines.parquet"
ANALYSIS = INTERIM / "analysis.parquet"
OUT = INTERIM / "s01_structure.json"
COLUMNS = ["Invoice", "StockCode", "Description", "Quantity", "InvoiceDate", "Price", "Customer ID", "Country"]
# A product code in this dataset starts with five digits, optionally followed by letters (e.g. 85123A, 22423).
PRODUCT_CODE = re.compile(r"^\d{5}[A-Za-z]{0,3}$")


def load_lines():
    if LINES.exists():
        return pd.read_parquet(LINES)
    sheets = pd.read_excel(RAW, sheet_name=None, engine="openpyxl",
                           dtype={"Invoice": str, "StockCode": str, "Description": str, "Country": str})
    frames = []
    for name, df in sheets.items():
        assert list(df.columns) == COLUMNS, (name, list(df.columns))
        df = df.copy()
        df.insert(0, "sheet", name)
        frames.append(df)
    lines = pd.concat(frames, ignore_index=True)
    INTERIM.mkdir(parents=True, exist_ok=True)
    lines.to_parquet(LINES, index=False)
    return lines


def remove_overlap_copies(lines):
    """Drop, from the second sheet, the rows that have an exact copy in the first sheet (one copy each)."""
    first, second = lines["sheet"].iloc[0], lines["sheet"].iloc[-1]
    a = lines[lines["sheet"] == first]
    b = lines[lines["sheet"] == second].copy()
    counts_a = a.groupby(COLUMNS, dropna=False).size().rename("count_first").reset_index()
    b["position"] = b.groupby(COLUMNS, dropna=False).cumcount()
    b = b.merge(counts_a, on=COLUMNS, how="left")
    b["count_first"] = b["count_first"].fillna(0)
    is_copy = b["position"] < b["count_first"]
    kept_b = b.loc[~is_copy, ["sheet"] + COLUMNS].reset_index(drop=True)
    copies = int(is_copy.sum())
    return pd.concat([a[["sheet"] + COLUMNS], kept_b], ignore_index=True), copies


def main():
    lines = load_lines()
    res = {"rows_total_raw": int(len(lines))}
    names = list(lines["sheet"].drop_duplicates())
    print(f"[rows] total raw {len(lines)}")
    for name in names:
        df = lines[lines["sheet"] == name]
        res[f"rows_sheet[{name}]"] = int(len(df))
        res[f"dates_sheet[{name}]"] = [str(df["InvoiceDate"].min()), str(df["InvoiceDate"].max())]
        print(f"[sheet] {name}: {len(df)} rows, {df['InvoiceDate'].min()} to {df['InvoiceDate'].max()}")

    raw_internal = int(sum(lines[lines["sheet"] == n].duplicated(subset=COLUMNS).sum() for n in names))
    res["repeats_inside_sheets_raw"] = raw_internal
    print(f"[overlap] repeats inside the sheets before removing the overlap: {raw_internal}")

    analysis, copies = remove_overlap_copies(lines)
    res["overlap_copies_removed"] = copies
    res["rows_after_overlap"] = int(len(analysis))
    internal_flag = analysis.duplicated(subset=COLUMNS, keep="first")
    analysis["internal_repeat"] = internal_flag.values
    res["internal_repeats_kept_and_flagged"] = int(internal_flag.sum())
    print(f"[overlap] copies of the overlapping week removed: {copies}; rows kept: {len(analysis)}; "
          f"internal repeats kept and flagged: {int(internal_flag.sum())}")
    analysis.to_parquet(ANALYSIS, index=False)

    inv = analysis["Invoice"].astype(str)
    cancel = inv.str.startswith("C")
    adjust = inv.str.startswith("A")
    has_customer = analysis["Customer ID"].notna()
    product = analysis["StockCode"].astype(str).str.match(PRODUCT_CODE)
    value = analysis["Quantity"] * analysis["Price"]
    res["cancel_rows"] = int(cancel.sum())
    res["cancel_invoices_distinct"] = int(inv[cancel].nunique())
    res["cancel_rows_with_customer"] = int((cancel & has_customer).sum())
    res["cancel_rows_with_customer_and_product_code"] = int((cancel & has_customer & product).sum())
    res["cancel_value_abs_gbp_all"] = round(float(value[cancel].abs().sum()), 2)
    res["adjust_A_rows"] = int(adjust.sum())
    res["invoices_distinct"] = int(inv.nunique())
    print(f"[cancel] C-invoice rows {res['cancel_rows']} in {res['cancel_invoices_distinct']} invoices; "
          f"with customer {res['cancel_rows_with_customer']}; with customer and product code "
          f"{res['cancel_rows_with_customer_and_product_code']}; A-invoice rows {res['adjust_A_rows']}")
    print(f"[invoice] distinct invoice numbers {res['invoices_distinct']}")

    res["rows_negative_quantity"] = int((analysis["Quantity"] < 0).sum())
    res["rows_zero_price"] = int((analysis["Price"] == 0).sum())
    res["rows_negative_price"] = int((analysis["Price"] < 0).sum())
    res["rows_missing_description"] = int(analysis["Description"].isna().sum())
    print(f"[qty] negative quantity rows {res['rows_negative_quantity']}; zero price {res['rows_zero_price']}; "
          f"negative price {res['rows_negative_price']}; missing description {res['rows_missing_description']}")

    missing = ~has_customer
    res["rows_missing_customer"] = int(missing.sum())
    res["share_rows_missing_customer"] = round(float(missing.mean()), 4)
    res["share_abs_value_missing_customer"] = round(float(value[missing].abs().sum() / value.abs().sum()), 4)
    res["customers_distinct"] = int(analysis["Customer ID"].dropna().nunique())
    print(f"[customer] missing customer rows {res['rows_missing_customer']} "
          f"({res['share_rows_missing_customer'] * 100:.2f} % of rows, "
          f"{res['share_abs_value_missing_customer'] * 100:.2f} % of absolute value); "
          f"distinct customers {res['customers_distinct']}")

    res["codes_distinct"] = int(analysis["StockCode"].nunique())
    res["rows_product_code"] = int(product.sum())
    res["rows_non_product_code"] = int((~product).sum())
    res["codes_non_product_distinct"] = int(analysis.loc[~product, "StockCode"].nunique())
    print(f"[codes] distinct stock codes {res['codes_distinct']}; product-pattern rows {res['rows_product_code']}; "
          f"non-product rows {res['rows_non_product_code']} across {res['codes_non_product_distinct']} codes")
    top = (analysis.loc[~product].groupby("StockCode")
           .agg(rows=("Invoice", "size"),
                description=("Description", lambda x: str(x.dropna().iloc[0]) if x.notna().any() else ""))
           .sort_values("rows", ascending=False).head(25))
    res["top_non_product_codes"] = [{"code": c, "rows": int(r.rows), "description": r.description}
                                    for c, r in top.iterrows()]
    for c, r in top.head(12).iterrows():
        print(f"    non-product {c!r}: {int(r.rows)} rows, {r.description}")

    countries = analysis["Country"].value_counts()
    res["countries_distinct"] = int(countries.size)
    res["share_rows_united_kingdom"] = round(float(countries.get("United Kingdom", 0) / len(analysis)), 4)
    print(f"[country] distinct countries {res['countries_distinct']}; United Kingdom share of rows "
          f"{res['share_rows_united_kingdom'] * 100:.2f} %")

    dates = analysis["InvoiceDate"]
    res["date_min"] = str(dates.min())
    res["date_max"] = str(dates.max())
    res["calendar_days_covered"] = int((dates.max().normalize() - dates.min().normalize()).days) + 1
    print(f"[dates] {res['date_min']} to {res['date_max']} ({res['calendar_days_covered']} calendar days)")

    INTERIM.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"[out] {OUT.relative_to(PROJECT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
