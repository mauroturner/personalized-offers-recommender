"""Planner fact p01: weekly offer rounds on the validation period only (Online Retail II, cached by s01).

The plan's test window starts on 2011-08-01. This script never reads a line dated on or after that day: the
Parquet is read with a pyarrow filter on InvoiceDate, and the script stops if any row passes it.

Rounds: the 13 Mondays from 2011-05-02 to 2011-07-25. A round r builds a list of 10 products for each customer of
the contact base (at least one purchase line in the 365 days before r) from purchase lines dated before r, and is
scored on what that customer bought in [r, r + 7 days). Evaluated pairs: (round, customer) with the customer in the
base and at least one purchase line in the window. Every window ends before 2011-08-01.

Methods: random (seed 0), global popularity, recent popularity (28 and 90 days), own repeats (the research's
score), pair association rules (at least 10 invoices, lift > 1, guest baskets included), implicit ALS (the
research's fixed hyperparameters), item-item cosine (implicit, K = 100), and the planned offer list: 7 slots of own
repeats and 3 discovery slots from ALS or from the rules (products the customer never bought), each filled with
recent popularity (90 days). Variants: unrestricted and new-only (bought products excluded). Blends, for the
discovery slots: the ALS or rules score divided by the customer's top score, plus w times the 28-day popularity
divided by its maximum (w = 0.5, 1, 2); the offer list is also built with the ALS blends (w = 1, 2) as discovery.

Intervals: bootstrap over customers (clusters: a customer's pairs of every round move together), 1,000 resamples,
seed 0, percentiles 2.5 and 97.5; paired differences use the same resampled customers.
Also: ALS fitted twice on the last round (determinism), and the seconds of each step.
Writes data/interim/plan/p01.json. Run from any directory:  python -I research/p01_weekly_validation.py
"""
import json
import re
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from implicit.als import AlternatingLeastSquares
from implicit.nearest_neighbours import CosineRecommender
from implicit.utils import ParameterWarning
from scipy import sparse

PROJECT = Path(__file__).resolve().parents[1]
ANALYSIS = PROJECT / "data" / "interim" / "analysis.parquet"
OUT = PROJECT / "data" / "interim" / "plan" / "p01.json"
TEST_START = pd.Timestamp("2011-08-01")
ROUNDS = pd.date_range("2011-05-02", "2011-07-25", freq="7D")
WINDOW = pd.Timedelta(days=7)
BASE_LOOKBACK = pd.Timedelta(days=365)
K = 10
REPEAT_SLOTS = 7
BOOT = 1000
RULE_MIN_INVOICES = 10
PRODUCT_CODE = re.compile(r"^\d{5}[A-Za-z]{0,3}$")
# implicit converts a non-CSR matrix inside CosineRecommender.fit and warns with its own file path; the
# conversion does not change any figure, so the warning is silenced to keep local paths out of p01.out
warnings.simplefilter("ignore", ParameterWarning)


def purchase_lines():
    table = pq.read_table(ANALYSIS, filters=[("InvoiceDate", "<", TEST_START.to_pydatetime())])
    df = table.to_pandas()
    if len(df) and df["InvoiceDate"].max() >= TEST_START:
        raise SystemExit("a line of the test window was read; stop")
    inv = df["Invoice"].astype(str)
    product = df["StockCode"].astype(str).str.match(PRODUCT_CODE)
    mask = (df["Quantity"] > 0) & (df["Price"] > 0) & product & ~inv.str.startswith("C") & ~inv.str.startswith("A")
    p = pd.DataFrame({"invoice": inv[mask], "code": df.loc[mask, "StockCode"].astype(str),
                      "date": df.loc[mask, "InvoiceDate"], "customer": df.loc[mask, "Customer ID"]})
    return p, str(df["InvoiceDate"].max())


def topk(scores, k=K):
    part = np.argpartition(-scores, kth=min(k, scores.shape[1] - 1), axis=1)[:, :k]
    order = np.take_along_axis(scores, part, axis=1)
    idx = np.argsort(-order, axis=1, kind="stable")
    return np.take_along_axis(part, idx, axis=1)


def per_user_metrics(top, test_sets, test_sizes):
    n = len(top)
    hit = np.zeros(n)
    recall = np.zeros(n)
    ndcg = np.zeros(n)
    disc = 1.0 / np.log2(np.arange(2, K + 2))
    for u in range(n):
        rel = np.fromiter((1.0 if j in test_sets[u] else 0.0 for j in top[u]), float, K)
        h = rel.sum()
        hit[u] = 1.0 if h > 0 else 0.0
        recall[u] = h / test_sizes[u]
        idcg = disc[: min(test_sizes[u], K)].sum()
        ndcg[u] = (rel * disc).sum() / idcg
    return hit, recall, ndcg


def mix(repeat_scores, discovery_scores, seen, fill, slots=REPEAT_SLOTS):
    """Up to `slots` own products by their score, the rest from discovery among never-bought products, then fill."""
    n, m = repeat_scores.shape
    out = np.empty((n, K), dtype=np.int64)
    for u in range(n):
        own = np.flatnonzero(seen[u])
        own = own[np.argsort(-repeat_scores[u, own], kind="stable")][:slots]
        chosen = list(own)
        taken = set(chosen)
        d = discovery_scores[u].copy()
        d[seen[u]] = -np.inf
        for j in np.argsort(-d, kind="stable"):
            if len(chosen) >= K:
                break
            if np.isfinite(d[j]) and d[j] > 0 and j not in taken:
                chosen.append(j)
                taken.add(j)
        for j in fill:
            if len(chosen) >= K:
                break
            if j not in taken:
                chosen.append(j)
                taken.add(j)
        out[u] = chosen[:K]
    return out


def run_round(p, r, timing):
    t0 = time.perf_counter()
    train = p[p["date"] < r]
    window = p[(p["date"] >= r) & (p["date"] < r + WINDOW)]
    catalogue = np.array(sorted(train["code"].unique()))
    cat_idx = {c: i for i, c in enumerate(catalogue)}
    n_cat = len(catalogue)

    train_c = train[train["customer"].notna()].copy()
    train_c["customer"] = train_c["customer"].astype(int)
    win_c = window[window["customer"].notna()].copy()
    win_c["customer"] = win_c["customer"].astype(int)
    last_buy = train_c.groupby("customer")["date"].max()
    base = set(last_buy[last_buy >= r - BASE_LOOKBACK].index)
    buyers = set(win_c["customer"].unique())
    eval_users = sorted(base & buyers)
    unreachable = len(buyers - base)
    first_timers = len(buyers - set(train_c["customer"].unique()))
    upos = {u: i for i, u in enumerate(eval_users)}
    n_eval = len(eval_users)

    tests = win_c.groupby("customer")["code"].apply(set).to_dict()
    test_sets, test_sizes = [], []
    for u in eval_users:
        items = tests[u]
        test_sizes.append(len(items))
        test_sets.append({cat_idx[c] for c in items if c in cat_idx})

    pair = train_c.drop_duplicates(["invoice", "code", "customer"]).groupby(["customer", "code"]).agg(
        n_inv=("invoice", "size"), last=("date", "max")).reset_index()
    pair = pair[pair["customer"].isin(upos)]
    seen = np.zeros((n_eval, n_cat), dtype=bool)
    own = np.zeros((n_eval, n_cat), dtype=np.float32)
    ii = pair["customer"].map(upos).to_numpy()
    jj = pair["code"].map(cat_idx).to_numpy()
    seen[ii, jj] = True
    own[ii, jj] = (pair["n_inv"].to_numpy() + 0.5 * ((pair["last"] - (r - pd.Timedelta(days=90)))
                                                     / pd.Timedelta(days=90)).to_numpy()).astype(np.float32)
    repeat_share = float(np.mean([sum(1 for j in test_sets[u] if seen[u, j]) / test_sizes[u] for u in range(n_eval)]))

    inv_items = train.drop_duplicates(["invoice", "code"])
    pop = inv_items.groupby("code").size().reindex(catalogue).fillna(0).to_numpy(np.float64)
    tie = (pop / (pop.max() + 1.0) * 1e-6).astype(np.float32)
    rec = {}
    for days in (28, 90):
        w = train[train["date"] >= r - pd.Timedelta(days=days)].drop_duplicates(["invoice", "code"])
        rec[days] = w.groupby("code").size().reindex(catalogue).fillna(0).to_numpy(np.float64)
    fill90 = np.argsort(-(rec[90] + tie), kind="stable")
    timing["prepare"] += time.perf_counter() - t0

    scores = {}
    rng = np.random.default_rng(0)
    scores["random"] = rng.random((n_eval, n_cat)).astype(np.float32)
    scores["popularity"] = np.tile((pop + tie).astype(np.float32), (n_eval, 1))
    scores["recent_popularity_28"] = np.tile((rec[28] + tie).astype(np.float32), (n_eval, 1))
    scores["recent_popularity_90"] = np.tile((rec[90] + tie).astype(np.float32), (n_eval, 1))
    scores["own_repeats"] = own + tie

    t1 = time.perf_counter()
    baskets = train.groupby("invoice")["code"].apply(lambda s: sorted(set(s)))
    rows = np.repeat(np.arange(len(baskets)), baskets.apply(len).to_numpy())
    cols = np.fromiter((cat_idx[c] for items in baskets for c in items), np.int64)
    B = sparse.csr_matrix((np.ones(len(rows), np.float32), (rows, cols)), shape=(len(baskets), n_cat))
    co = (B.T @ B).toarray()
    item_n = np.diag(co).copy()
    rate = item_n / len(baskets)
    with np.errstate(divide="ignore", invalid="ignore"):
        conf = np.where(item_n[:, None] > 0, co / item_n[:, None], 0.0).astype(np.float32)
        lift = np.where(rate[None, :] > 0, conf / rate[None, :], 0.0)
    keep = (co >= RULE_MIN_INVOICES) & (lift > 1.0)
    np.fill_diagonal(keep, False)
    conf = np.where(keep, conf, 0.0).astype(np.float32)
    n_rules = int(keep.sum())
    del co, lift, keep
    rules = np.zeros((n_eval, n_cat), dtype=np.float32)
    for u in range(n_eval):
        s = np.flatnonzero(seen[u])
        if len(s):
            rules[u] = conf[s].max(axis=0)
    scores["association_rules"] = rules + tie
    timing["rules"] += time.perf_counter() - t1

    t2 = time.perf_counter()
    train_users = sorted(train_c["customer"].unique())
    tu = {u: i for i, u in enumerate(train_users)}
    m = sparse.csr_matrix((np.ones(len(train_c), np.float32),
                           (train_c["customer"].map(tu).to_numpy(), train_c["code"].map(cat_idx).to_numpy())),
                          shape=(len(train_users), n_cat))
    m.data[:] = 1.0
    als = AlternatingLeastSquares(factors=64, regularization=0.01, iterations=15, random_state=0,
                                  num_threads=1, use_gpu=False)
    als.fit((m * 20.0).astype(np.float32), show_progress=False)
    rows_eval = [tu[u] for u in eval_users]
    scores["als"] = np.asarray(als.user_factors)[rows_eval] @ np.asarray(als.item_factors).T + tie
    timing["als"] += time.perf_counter() - t2

    t3 = time.perf_counter()
    cos = CosineRecommender(K=100, num_threads=1)
    cos.fit(m, show_progress=False)
    S = cos.similarity.tocsr()
    scores["item_cosine"] = np.asarray((m[rows_eval] @ S).todense(), dtype=np.float32) + tie
    timing["item_cosine"] += time.perf_counter() - t3

    t4 = time.perf_counter()
    trend = (rec[28] / max(rec[28].max(), 1.0)).astype(np.float32)
    for disc in ("als", "association_rules"):
        sc = scores[disc] - tie
        top_u = np.maximum(sc.max(axis=1, keepdims=True), 1e-9)
        norm = np.clip(sc / top_u, 0.0, None)
        for w in (0.5, 1.0, 2.0):
            scores[f"blend_{disc}_trend_{w:g}"] = norm + w * trend[None, :] + tie
    tops = {}
    for name, sc in scores.items():
        tops[(name, "unrestricted")] = topk(sc)
        nw = sc.copy()
        nw[seen] = -np.inf
        tops[(name, "new_only")] = topk(nw)
    for disc in ("als", "association_rules"):
        tops[(f"offer_7_3_{disc}", "unrestricted")] = mix(own, scores[disc], seen, fill90, slots=REPEAT_SLOTS)
    for w in ("1", "2"):
        tops[(f"offer_7_3_blend_als_trend_{w}", "unrestricted")] = mix(own, scores[f"blend_als_trend_{w}"], seen, fill90)
    for slots in (10, 8, 5, 3):
        tops[(f"offer_{slots}_{K - slots}_als", "unrestricted")] = mix(own, scores["als"], seen, fill90, slots=slots)
    timing["rank"] += time.perf_counter() - t4

    out = {}
    for key, top in tops.items():
        out[key] = per_user_metrics(top, test_sets, test_sizes)
    coverage = {f"{k[0]}|{k[1]}": len(set(v.ravel().tolist())) / n_cat for k, v in tops.items()}
    info = {"round": str(r.date()), "base": len(base), "window_buyers": len(buyers), "eval_pairs": n_eval,
            "window_buyers_not_in_base": unreachable, "window_first_time_buyers": first_timers,
            "catalogue": n_cat, "rule_pairs": n_rules, "repeat_share": round(repeat_share, 4),
            "test_items": int(sum(test_sizes)),
            "test_items_outside_catalogue_share": round(1 - sum(len(s) for s in test_sets) / sum(test_sizes), 4)}
    return out, coverage, info, eval_users, (als if r == ROUNDS[-1] else None), m


def boot_ci(values, clusters, rng_idx):
    vals = []
    for idx in rng_idx:
        vals.append(values[idx].mean())
    return [round(float(np.percentile(vals, 2.5)), 4), round(float(np.percentile(vals, 97.5)), 4)]


def main():
    started = time.perf_counter()
    p, max_date = purchase_lines()
    print(f"[data] purchase lines before {TEST_START.date()}: {len(p)}; latest line read {max_date}")
    timing = {k: 0.0 for k in ("prepare", "rules", "als", "item_cosine", "rank")}
    per_key = {}
    cov = {}
    infos = []
    customers = []
    last_m = None
    last_als = None
    for r in ROUNDS:
        t = time.perf_counter()
        out, coverage, info, users, als, m = run_round(p, r, timing)
        info["seconds"] = round(time.perf_counter() - t, 2)
        infos.append(info)
        customers.extend(users)
        for k, v in out.items():
            per_key.setdefault(k, ([], [], []))
            for slot, arr in zip(per_key[k], v):
                slot.append(arr)
        for k, v in coverage.items():
            cov.setdefault(k, []).append(v)
        if als is not None:
            last_als, last_m = als, m
        print(f"[round {info['round']}] base {info['base']}, buyers {info['window_buyers']}, pairs {info['eval_pairs']}, "
              f"buyers outside the base {info['window_buyers_not_in_base']} ({info['window_first_time_buyers']} first "
              f"purchases), catalogue {info['catalogue']}, rules {info['rule_pairs']}, repeat share "
              f"{info['repeat_share'] * 100:.1f} %, {info['seconds']} s")

    customers = np.array(customers)
    uniq, inverse = np.unique(customers, return_inverse=True)
    members = [np.flatnonzero(inverse == g) for g in range(len(uniq))]
    rng = np.random.default_rng(0)
    draws = [np.concatenate([members[g] for g in rng.integers(0, len(uniq), len(uniq))]) for _ in range(BOOT)]
    res = {"rounds": [str(r.date()) for r in ROUNDS], "window_days": 7, "k": K, "bootstrap": BOOT,
           "latest_line_read": max_date, "pairs": int(len(customers)), "customers": int(len(uniq)),
           "per_round": infos, "methods": {}, "differences": {}, "timing_seconds": {}}
    print(f"[pairs] {len(customers)} evaluated (round, customer) pairs from {len(uniq)} customers")
    arrays = {}
    for (name, variant), (hits, recs, ndcgs) in sorted(per_key.items()):
        h = np.concatenate(hits)
        arrays[(name, variant)] = h
        rc = np.concatenate(recs)
        nd = np.concatenate(ndcgs)
        entry = {"hit10": round(float(h.mean()), 4), "hit10_ci95": boot_ci(h, None, draws),
                 "recall10": round(float(rc.mean()), 4), "ndcg10": round(float(nd.mean()), 4),
                 "coverage_mean": round(float(np.mean(cov[f"{name}|{variant}"])), 4)}
        res["methods"].setdefault(name, {})[variant] = entry
        print(f"    {name:24s} {variant:12s} hit@10 {entry['hit10'] * 100:5.1f} % {[round(x * 100, 1) for x in entry['hit10_ci95']]}"
              f" recall {entry['recall10']:.3f} ndcg {entry['ndcg10']:.3f} coverage {entry['coverage_mean']:.3f}")
    pairs = [
        (("offer_7_3_als", "unrestricted"), ("recent_popularity_90", "unrestricted")),
        (("offer_7_3_als", "unrestricted"), ("recent_popularity_28", "unrestricted")),
        (("offer_7_3_als", "unrestricted"), ("own_repeats", "unrestricted")),
        (("offer_7_3_association_rules", "unrestricted"), ("own_repeats", "unrestricted")),
        (("offer_10_0_als", "unrestricted"), ("own_repeats", "unrestricted")),
        (("als", "new_only"), ("recent_popularity_90", "new_only")),
        (("als", "new_only"), ("recent_popularity_28", "new_only")),
        (("association_rules", "new_only"), ("recent_popularity_90", "new_only")),
        (("association_rules", "new_only"), ("recent_popularity_28", "new_only")),
        (("item_cosine", "new_only"), ("recent_popularity_90", "new_only")),
        (("item_cosine", "new_only"), ("recent_popularity_28", "new_only")),
        (("als", "new_only"), ("association_rules", "new_only")),
        (("offer_7_3_blend_als_trend_1", "unrestricted"), ("own_repeats", "unrestricted")),
        (("offer_7_3_blend_als_trend_2", "unrestricted"), ("own_repeats", "unrestricted")),
        (("offer_7_3_blend_als_trend_1", "unrestricted"), ("recent_popularity_28", "unrestricted")),
    ] + [((f"blend_{d}_trend_{w}", "new_only"), ("recent_popularity_28", "new_only"))
         for d in ("als", "association_rules") for w in ("0.5", "1", "2")]
    for a, b in pairs:
        d = arrays[a] - arrays[b]
        key = f"{a[0]}:{a[1]} - {b[0]}:{b[1]}"
        res["differences"][key] = {"value": round(float(d.mean()), 4), "ci95": boot_ci(d, None, draws)}
        print(f"[difference] {key}: {d.mean() * 100:+.2f} points {[round(x * 100, 2) for x in res['differences'][key]['ci95']]}")

    again = AlternatingLeastSquares(factors=64, regularization=0.01, iterations=15, random_state=0,
                                    num_threads=1, use_gpu=False)
    again.fit((last_m * 20.0).astype(np.float32), show_progress=False)
    diff_u = float(np.abs(np.asarray(again.user_factors) - np.asarray(last_als.user_factors)).max())
    diff_i = float(np.abs(np.asarray(again.item_factors) - np.asarray(last_als.item_factors)).max())
    res["als_refit_max_abs_difference"] = {"user_factors": diff_u, "item_factors": diff_i}
    print(f"[determinism] ALS fitted twice on the last round, one thread, seed 0: max |difference| user factors "
          f"{diff_u:.3g}, item factors {diff_i:.3g}")
    res["timing_seconds"] = {k: round(v, 2) for k, v in timing.items()}
    res["timing_seconds"]["total"] = round(time.perf_counter() - started, 2)
    print(f"[timing] " + ", ".join(f"{k} {v} s" for k, v in res["timing_seconds"].items()))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[out] {OUT.relative_to(PROJECT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
