"""A warehouse with one round and a handful of customers written by hand (U13): the lists, the groups the lists say, the groups the assignments say and the descriptions of the products are the
test's, so a rule about who is delivered can be broken one customer at a time, which the replayed fixture, whose tables only take what the flow wrote, cannot do."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from personaloffers import warehouse

ROUND = "R2011-03-28"
RUN = "run-1"


def code_of(customer: int, rank: int) -> str:
    return f"{95000 + 12 * ((customer + rank) % 40)}"


def tiny_warehouse(path: Path, listed: Mapping[int, str], assigned: Mapping[int, str | None], *, descriptions: Mapping[str, str | None] | None = None, k: int = 10, round_id: str = ROUND):
    """The warehouse at `path` (schema applied) with the round `round_id` and, for each customer of `listed` (customer -> the group its list says), a list of `k` products; `assigned` is the group each
    customer has in ``holdout_assignments`` (None: no assignment). `descriptions` is ``{stock_code: description_es}`` for ``products``; a code that is not there has no row."""
    conn = warehouse.connect(path)
    warehouse.apply_schema(conn)
    conn.execute("INSERT INTO pipeline_runs (run_key, started_at, status) VALUES (?, '2011-04-04 08:00:00', 'running')", (RUN,))
    conn.execute("INSERT INTO rounds VALUES (?, ?, 'test', ?, ?, ?, ?)", (round_id, round_id[1:], RUN, len(listed), sum(g == "offer" for g in listed.values()), sum(g == "control" for g in listed.values())))
    for customer, group in assigned.items():
        if group is not None:
            conn.execute("INSERT INTO holdout_assignments VALUES (?, ?, 'stratified', 0, ?, ?)", (customer, group, round_id, RUN))
    for customer, group in listed.items():
        for rank in range(1, k + 1):
            conn.execute("INSERT INTO offer_lists VALUES (?, ?, ?, ?, ?, 1.0, ?, ?)", (round_id, customer, rank, code_of(customer, rank), ("repeat", "discovery", "fallback")[min(rank // 4, 2)], group, RUN))
    for code, text in (descriptions or {}).items():
        conn.execute("INSERT INTO products VALUES (?, ?, '2011-01-03', 1)", (code, text))
    return conn
