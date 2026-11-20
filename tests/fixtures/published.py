"""What no published file may hold, written once for every test that reads the published files (the site, the Parquet files and the design): a number of an invented customer and a path of the machine that wrote them."""

from __future__ import annotations

import re

from tests.fixtures.make_workbook import CUSTOMER_FIRST, CUSTOMER_LAST

# a drive («C:» and a separator, not the end of a word such as «https:»), a home folder or a users folder
LOCAL_PATH = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]|/(?:home|Users)/|\\Users\\")
# five digits that are not part of a longer number or of a decimal
FIVE_DIGITS = re.compile(r"(?<![\d.])\d{5}(?!\d)")


def customer_numbers_in(text: str) -> list[str]:
    """The numbers of the fixture's customers (``CUSTOMER_FIRST`` to ``CUSTOMER_LAST``) that `text` holds, in order: five digits alone, not a part of a longer number or of a decimal."""
    return [number for number in FIVE_DIGITS.findall(text) if CUSTOMER_FIRST <= int(number) <= CUSTOMER_LAST]


def example_list_problems(conn, examples: list[dict], minimum: int) -> list[str]:
    """What makes the example lists of ``algorithms.json`` able to single out a customer (D30, D46; B1 of the evaluation), counted **within the published profile** (``segment_key``) and its round, from the
    lists the warehouse issued: a list that is a customer's own (it carries ranks, or from 1 to ``minimum - 1`` customers of the profile hold every product of it: a handful, so the profile and the public
    archive narrow it down), a product whose published number of customers is not the one the warehouse gives for its origin, or a product held by fewer than ``minimum`` customers. ``[]`` when none."""
    problems = []
    for example in examples:
        where = f"{example.get('segment_key')} {example.get('round_key')}"
        rows = conn.execute("SELECT o.customer_id, o.stock_code, o.source FROM offer_lists o JOIN contact_base c ON c.round_id = o.round_id AND c.customer_id = o.customer_id "
                            "WHERE o.round_id = ? AND c.segment = ?", (example["round_key"], example["segment_key"])).fetchall()
        held: dict[int, set[str]] = {}
        by_origin: dict[tuple[str, str], set[int]] = {}
        for customer, code, source in rows:
            held.setdefault(customer, set()).add(code)
            by_origin.setdefault((code, source), set()).add(customer)
        products = example["products"]
        codes = {p["stock_code"] for p in products}
        whole = sum(1 for mine in held.values() if codes <= mine)
        if 0 < whole < minimum:
            problems.append(f"{where}: {whole} customers of the profile hold every product of the list")
        if any("rank" in p for p in products):
            problems.append(f"{where}: the products carry the ranks of one customer's list")
        for p in products:
            count = len(by_origin.get((p["stock_code"], p["source_key"]), ()))
            if p.get("customers") != count:
                problems.append(f"{where}: {p['stock_code']} says {p.get('customers')} customers and the warehouse gives {count} with the origin {p['source_key']}")
            elif count < minimum:
                problems.append(f"{where}: {p['stock_code']} is held by {count} customers, under the minimum of {minimum}")
    return problems


def stratum_leaks(node, where: str, strata: dict, allowed=()) -> list[str]:
    """What shows the holdout's strata in a parsed JSON, matched by **field or key**, never by the value of an offer and control pair alone (an aggregate can hold the same two numbers as a stratum by
    chance): a field whose name says «strat» (but the ``allowed`` paths, such as the control file's count of strata), a member keyed by a stratum's id whose offer and control are that stratum's, or a
    container that holds the pair of **every** stratum (a list of sizes with no id). ``strata`` is the seal's ``launch.holdout.sizes.strata`` (id to ``{"offer", "control"}``). ``[]`` when none."""
    pairs = {(groups["offer"], groups["control"]) for groups in strata.values()}
    found: list[str] = []

    def pair_of(value) -> tuple[int, int] | None:
        if isinstance(value, dict) and isinstance(value.get("offer"), int) and isinstance(value.get("control"), int):
            return value["offer"], value["control"]
        return None

    def visit(value, path: str) -> None:
        members = value.items() if isinstance(value, dict) else enumerate(value) if isinstance(value, list) else ()
        held = {pair for pair in (pair_of(member) for _, member in members) if pair is not None}
        if pairs and pairs <= held:
            found.append(f"{path}: holds the size of every stratum")
        for key, member in members:
            child = f"{path}/{key}" if isinstance(value, dict) else f"{path}[{key}]"
            if isinstance(key, str):
                if "strat" in key.lower() and child not in allowed:
                    found.append(f"{child}: a field of the strata")
                if key in strata and pair_of(member) == (strata[key]["offer"], strata[key]["control"]):
                    found.append(f"{child}: the size of a stratum")
            visit(member, child)

    visit(node, where)
    return found
