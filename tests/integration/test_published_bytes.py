"""What is published (U15; RF20, RNF12, AC26, AC28; decision D30; risk item 3): no table of the star model has a customer number, no cell that counts customers has fewer than the minimum, and a group never hides
just one cell, because a total that is published would give it back by subtraction. The files of the site join this one in U17."""

from __future__ import annotations

import re

import pandas as pd
import pytest

from personaloffers.dashboard.semantic_model import CUSTOMER_COUNT_COLUMNS, MODEL
from tests.fixtures.stars import export_world

CUSTOMER_NUMBER = re.compile(r"(?<![\d.])90[0-3]\d\d(?!\d)")
GROUPS = {"fact_round_group": ["round_key", "group_key"], "fact_method_round": ["method_key", "variant_key", "seal_state"], "fact_segment": ["method_key", "variant_key", "seal_state"]}


def published(folder, name) -> pd.DataFrame:
    return pd.read_parquet(folder / f"{name}.parquet")


def assert_protected(out, minimum: int) -> None:
    """The three rules on every published file: the cells that are shown have at least `minimum` customers, the ones that are hidden hold no number, and a group has none or at least two hidden cells."""
    for name, columns in CUSTOMER_COUNT_COLUMNS.items():
        table = published(out, name)
        for column in columns:
            shown = table[column].dropna()
            assert (shown >= minimum).all(), f"{name}[{column}] has a cell under {minimum}: {sorted(shown[shown < minimum])[:3]}"
        if name in ("fact_round_group", "fact_method_round", "fact_method_total", "fact_segment", "fact_mde"):
            hidden = table[table["suppressed"]]
            assert hidden[list(columns)].isna().all().all(), f"{name}: a hidden cell holds a number"
        if name == "fact_offer_product":
            assert (table["offered_to"] >= minimum).all() and table.loc[table["suppressed"], "bought_by"].isna().all()
        if name in GROUPS:
            if name == "fact_method_round":
                table = table.merge(published(out, "dim_round")[["round_key", "period"]], on="round_key").query("period == 'test'")
            counts = table.groupby(GROUPS[name])["suppressed"].sum()
            assert not (counts == 1).any(), f"{name}: a group hides exactly one cell, which its total would give back"


def test_no_published_cell_counts_fewer_than_ten_customers(exported):
    """AC26, AC28: the model written with the configured minimum of 10 customers a cell."""
    assert exported.view.privacy.min_cell_customers == 10
    assert_protected(exported.out, 10)
    group = published(exported.out, "fact_round_group")
    assert group["suppressed"].all() and group[["customers", "buyers", "buyers_of_listed", "spend"]].isna().all().all(), "in the fixture no cell of the follow-up has 10 buyers: all of it is hidden, and none is shown by mistake"
    ops = published(exported.out, "fact_round_ops")
    assert ops["new_assignments"].isna().all() and ops["buyers_outside_base"].isna().all() and ops["base"].eq(300).all() and ops["suppressed"].all()


@pytest.mark.parametrize("minimum", [2, 12, 36, 50])
def test_the_rules_hold_for_other_minimums_and_the_second_cell_is_hidden_when_a_group_would_hide_one(evaluated, workbook, quick_cfg, tmp_path, minimum):
    star = export_world(evaluated.root, workbook, quick_cfg, tmp_path, minimum=minimum)
    try:
        assert_protected(star.out, minimum)
        if minimum == 2:
            group = published(star.out, "fact_round_group").set_index(["round_key", "group_key", "segment_key"])
            offer, control = group.loc[("R2011-04-04", "offer")], group.loc[("R2011-04-04", "control")]
            assert not offer["suppressed"].any() and offer["customers"].tolist() == [19, 221], "the offer group's two segments have 2 or more buyers"
            assert control["suppressed"].all(), "control|one_invoice has 0 buyers and is hidden, and control|repeat goes with it: the group total would have given it back"
        if minimum == 36:
            rounds = published(star.out, "fact_method_round")
            of_b2 = rounds[(rounds["method_key"] == "b2") & (rounds["variant_key"] == "unrestricted")].set_index("round_key")
            assert of_b2["suppressed"].to_dict() == {"R2011-03-28": True, "R2011-04-04": True, "R2011-04-11": False, "R2011-04-18": True}, "the round of 35 pairs is under 36 and the smallest shown of the test (46) goes with it; the censored one (30) is a group of its own"
            total = published(star.out, "fact_method_total").set_index(["method_key", "variant_key"]).loc[("b2", "unrestricted"), "pairs"]
            assert total == 130 and of_b2["pairs"].dropna().sum() == 49 and total - of_b2["pairs"].dropna().sum() == 35 + 46, "the two hidden rounds of the test are only known together"
        if minimum == 12:
            segments = published(star.out, "fact_segment")
            assert segments["suppressed"].all(), "retail|one_invoice has 11 customers and is hidden; the only other segment goes with it"
        if minimum == 50:
            assert published(star.out, "fact_method_round")["suppressed"].all() and not published(star.out, "fact_method_total")["suppressed"].any(), "no round has 50 pairs and the 130 of the test are shown"
    finally:
        star.conn.close()


def test_no_customer_number_in_a_published_file_and_the_private_file_holds_them_all(exported):
    for table in MODEL.public:
        data = published(exported.out, table.name)
        for column in data.columns:
            if data[column].dtype == object:
                text = " ".join(str(v) for v in data[column].dropna().unique())
                assert not CUSTOMER_NUMBER.search(text), f"{table.name}[{column}] has what looks like a customer number"
            elif pd.api.types.is_integer_dtype(data[column]):
                assert not data[column].dropna().between(90001, 90300).any(), f"{table.name}[{column}] has a number in the range of the customers"
    private = published(exported.private, "fact_offer_customer")
    assert set(private["customer_id"]) == set(range(90001, 90301)) and private["bought"].notna().all()
    assert set(private["group_key"]) == {"offer", "control"} and set(private["source_key"]) <= {"repeat", "discovery", "fallback"}


def test_the_private_list_is_every_customers_list_with_what_they_bought_in_the_week(exported):
    private = published(exported.private, "fact_offer_customer")
    first = private[(private["round_key"] == "R2011-03-28") & (private["customer_id"] == 90001)].sort_values("rank")
    assert first["rank"].tolist() == list(range(1, 11)) and first["product_key"].is_unique
    assert len(private) == 12000 and private.groupby(["round_key", "customer_id"]).size().eq(10).all()
    assert private["bought"].sum() > 0 and private.groupby(["round_key", "customer_id"])["bought"].sum().max() <= 10


def test_the_totals_are_hidden_when_the_test_has_fewer_pairs_than_the_minimum(evaluated, workbook, quick_cfg, tmp_path):
    star = export_world(evaluated.root, workbook, quick_cfg, tmp_path, minimum=200)
    try:
        assert_protected(star.out, 200)
        total = published(star.out, "fact_method_total")
        assert total["suppressed"].all() and total[["pairs", "hit_rate", "ci_low", "ci_high", "wilson_low", "wilson_high", "recall", "precision", "ndcg", "coverage"]].isna().all().all(), "the 130 pairs of the test are under 200"
        assert published(star.out, "fact_mde")["suppressed"].eq(published(star.out, "fact_mde")["holdout_size"].isna()).all()
    finally:
        star.conn.close()


def test_a_segment_is_judged_by_its_customers_and_not_by_its_pairs(evaluated, workbook, quick_cfg, tmp_path):
    """A customer is in several rounds, so a segment can have enough pairs and too few customers: the cell counts customers (D30)."""
    probe = export_world(evaluated.root, workbook, quick_cfg, tmp_path / "probe")
    customers, pairs = probe.conn.execute("SELECT customers, pairs FROM eval_segments WHERE segment = 'retail|repeat' AND method = 'b2' AND variant = 'unrestricted'").fetchone()
    probe.conn.close()
    assert customers < pairs, "the fixture has customers that bought in more than one round"
    star = export_world(evaluated.root, workbook, quick_cfg, tmp_path / "judged", minimum=customers + 1)
    try:
        segments = published(star.out, "fact_segment")
        assert segments["suppressed"].all() and segments["pairs"].isna().all(), f"{pairs} pairs but {customers} customers: under {customers + 1}"
    finally:
        star.conn.close()
