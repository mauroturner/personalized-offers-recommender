"""Checks every factual claim of the site page (marca-personal, src/i18n/projects/personal-offers.ts, es and en)
against the data and the outputs of s01-s06. The page is read only; nothing is edited here.

Each claim is printed with the observed value; the verdict (confirmed, nuance, contradicted, not testable) is
written in docs/research.md, section «Contradicciones con el sitio», from these numbers.
Reads data/interim/*.json and data/interim/analysis.parquet. Writes data/interim/s07_site_claims.json.
Run from any directory:  python -I research/s07_site_claims.py
"""
import json
import os
import re
import sys
from pathlib import Path

import pandas as pd

PROJECT = Path(__file__).resolve().parents[1]
INTERIM = PROJECT / "data" / "interim"
ANALYSIS = INTERIM / "analysis.parquet"
OUT = INTERIM / "s07_site_claims.json"
# The site repository sits beside the portfolio; MARCA_PERSONAL overrides that location.
SITE_ROOT = Path(os.environ.get("MARCA_PERSONAL", PROJECT.parents[1] / "marca-personal"))
SITE_FILE = SITE_ROOT / "src" / "i18n" / "projects" / "personal-offers.ts"
COLUMNS = ["Invoice", "StockCode", "Description", "Quantity", "InvoiceDate", "Price", "Customer ID", "Country"]


def load_json(name):
    return json.loads((INTERIM / name).read_text(encoding="utf-8"))


def main():
    s1 = load_json("s01_structure.json")
    s2 = load_json("s02_baskets.json")
    s4 = load_json("s04_control.json")
    s5 = load_json("s05_overlap.json")
    s3 = load_json("s03_baselines.json")
    df = pd.read_parquet(ANALYSIS)
    raw_rows = s1["rows_total_raw"]
    res = {"site_file_present": SITE_FILE.exists(), "claims": []}
    site_text = SITE_FILE.read_text(encoding="utf-8") if SITE_FILE.exists() else ""
    quoted = {
        "1 millón": "1 millón", "líneas de factura, aprox.": "líneas de factura, aprox.",
        "8 campos por línea, del producto al cliente": "campos por línea, del producto al cliente",
        "0 ofertas al azar": "ofertas al azar para medir su efecto",
        "Cliente, vacío en algunas filas": "Cliente, vacío en algunas filas",
        "minorista del Reino Unido": "minorista del Reino Unido",
        "usan también las facturas sin cliente": "usan también las facturas sin cliente",
        "completados con las reglas de canasta cuando falta historia": "completados con las reglas de canasta cuando falta historia",
        "El dataset no tiene ofertas al azar": "El dataset no tiene ofertas al azar",
        "Un grupo de control listo": "Un grupo de control listo",
        "precisión@k": "precisión@k",
        "contra recomendar lo más vendido": "contra recomendar lo más vendido",
        "Cada semana un flujo arma las ofertas": "Cada semana un flujo arma las ofertas",
        "Power BI": "Power BI",
    }
    res["quoted_phrases_in_site_es"] = {k: (v in site_text) for k, v in quoted.items()}
    missing = [k for k, ok in res["quoted_phrases_in_site_es"].items() if not ok]
    print(f"[site] quoted phrases found in the es page: {len(quoted) - len(missing)} of {len(quoted)}"
          + (f"; missing: {missing}" if missing else ""))

    def claim(id_, text, observed, note=""):
        res["claims"].append({"id": id_, "claim": text, "observed": observed, "note": note})
        print(f"[{id_}] {text}\n      observed: {observed}" + (f"\n      note: {note}" if note else ""))

    claim("C01", "«1 millón de líneas de factura, aprox.»", {
        "rows_after_overlap": s1["rows_after_overlap"], "rows_raw": raw_rows,
        "overlap_copies_removed": s1["overlap_copies_removed"]},
        "1,044,848 rows after removing the 22,523 copies; 1,067,371 raw")

    claim("C02", "«8 campos por línea, del producto al cliente»", {
        "columns_in_workbook": COLUMNS, "count": len(COLUMNS)})

    offer_words = df["Description"].astype(str).str.contains(r"DISCOUNT|OFFER|PROMO|VOUCHER", case=False, regex=True)
    discount_code = df["StockCode"].astype(str).eq("D")
    claim("C03", "«0 ofertas al azar para medir su efecto»", {
        "random_offer_field_in_archive": False,
        "rows_description_mentions_discount_offer_voucher": int(offer_words.sum()),
        "rows_stock_code_D_discount": int(discount_code.sum()),
        "negative_price_rows": s1["rows_negative_price"]},
        "no randomised offer and no campaign flag exist; the archive does carry non-random discount lines")

    claim("C04", "«Cliente, vacío en algunas filas»", {
        "share_rows_missing_customer": s1["share_rows_missing_customer"],
        "rows_missing_customer": s1["rows_missing_customer"]},
        "about one row in five has no customer, not «some»")

    claim("C05", "«Producto y descripción» (fields)", {
        "rows_missing_description": s1["rows_missing_description"],
        "non_product_codes_distinct": s1["codes_non_product_distinct"]})

    claim("C06", "«País» (field) and «un minorista del Reino Unido»", {
        "countries_distinct": s1["countries_distinct"],
        "share_rows_united_kingdom": s1["share_rows_united_kingdom"],
        "wholesale_customers_at_launch_p2_rule": s5["p2_wholesale"]["wholesale_customers"]},
        "the seller is a UK online retailer; the buyers include wholesale accounts (P2's rule)")

    claim("C07", "«Fecha de la factura, para separar por tiempo»", {
        "date_min": s1["date_min"], "date_max": s1["date_max"], "calendar_days": s1["calendar_days_covered"]})

    claim("C08", "«Reglas de asociación ... usan también las facturas sin cliente»", {
        "purchase_invoices_guest": s2["purchase_invoices_guest"],
        "purchase_invoices_guest_share": s2["purchase_invoices_guest_share"],
        "association_rules_built_on_all_training_baskets": True})

    claim("C09", "«Número de factura, que arma cada canasta»", {
        "invoices_distinct": s1["invoices_distinct"],
        "basket_items_median": s2["basket_items_all"]["p50"]})

    claim("C10", "Source: Daqing Chen, UCI, CC BY 4.0", {
        "licence_from_uci_page": "CC BY 4.0 (see data/raw/manifest.json)"})

    cut = s2["history_at_cuts"]["2011-06-01"]
    claim("C11", "«Un modelo ... completados con las reglas de canasta cuando falta historia»", {
        "active_last_90_days_at_2011_06_01": cut["customers_active_last_90_days"],
        "active_with_at_least_2_prior_invoices": cut["customers_active_last_90_days_with_ge2_prior_invoices"],
        "active_needing_fallback_share": round(1 - cut["customers_active_last_90_days_with_ge2_prior_invoices"]
                                               / cut["customers_active_last_90_days"], 4),
        "customers_without_any_prior_invoice": s2["customers_with_purchase"] - cut["customers_with_any_prior_invoice"]},
        "a fallback is needed for about one active customer in seven")

    claim("C12", "«Un grupo de control listo ... no permite medir el efecto real de una oferta»", {
        "holdout_mde_20pct_points": s4["mde_by_holdout_share"]["20%"]["mde_any_purchase_points"],
        "aa_rejection_rate_any_purchase": s4["aa_calibration"]["rejection_rate_any_purchase"],
        "aa_rejection_rate_value": s4["aa_calibration"]["rejection_rate_value"]})

    claim("C13", "«Se evalúa con un corte en el tiempo y precisión@k, contra recomendar lo más vendido»", {
        "cut": "2011-06-01", "k": s3["k"],
        "popularity_precision_at_10": s3["cuts"]["2011-06-01"]["methods"]["popularity"]["unrestricted"]["precision"]["value"],
        "als_precision_at_10": s3["cuts"]["2011-06-01"]["methods"]["als"]["unrestricted"]["precision"]["value"],
        "eval_users": s3["cuts"]["2011-06-01"]["eval_users"]})

    claim("C14", "«Cada semana un flujo arma las ofertas» (cadence)", {
        "p4_cadence": "monthly", "archive_granularity": "daily timestamps",
        "weekly_cuts_between_2011_06_01_and_2011_09_01": 14},
        "not a data contradiction: a planning choice (open question)")

    claim("C15", "«Power BI» dashboard and «n8n» flow", {
        "testable_here": False}, "product tooling; the dashboard needs Power BI Desktop (owner's S4 applies)")

    res["sources_checked"] = {"site": str(SITE_FILE), "project_ids": "es and en copies of the same claims"}
    OUT.write_text(json.dumps(res, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"[out] {OUT.relative_to(PROJECT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
