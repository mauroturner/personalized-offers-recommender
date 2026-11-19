"""Baselines for «what to offer next» on a time split, with no leakage (Online Retail II, cached by s01).

For each cut T (the first day of the test window), training uses only purchase lines dated before T and
the test set is what each customer bought in [T, T + 90 days). Users are the customers with at least one
training purchase and at least one test purchase. Candidates are the products with a training purchase.

Methods (all fixed before the run; nothing is tuned on the test window):
- random: 10 products drawn uniformly from the catalogue (seed 0), the floor every method must beat;
- popularity: distinct training invoices containing the product (guest baskets included), the same list for everyone;
- recent popularity: the same count over the 90 days before T;
- own repeats: the customer's own products by number of invoices, ties by recency, then popularity;
- association rules: pair rules from all training baskets (guest baskets included), with at least 10 invoices
  and lift > 1. Support, confidence and lift are computed from a sparse co-occurrence matrix; the same values
  are checked against mlxtend (fpgrowth and association_rules) on the 300 most frequent products. A candidate
  scores the highest confidence from any product in the customer's history;
- ALS: implicit's AlternatingLeastSquares on the customer x product matrix (64 factors, regularisation 0.01,
  15 iterations, alpha 20, seed 0, one thread), the implicit-feedback baseline.

Metrics at K = 10 (per user, then averaged over users): hit rate (at least one test product in the top 10),
recall (hits / all test products), precision (hits / 10), NDCG (binary relevance, ideal ordering over
min(test size, 10) positions), and catalogue coverage (distinct products recommended / catalogue size).
Intervals: bootstrap over users (1,000 resamples, seed 0, percentile 95 %) and a Wilson interval for the hit rate.
Two variants: unrestricted (a repeat purchase can be recommended; the primary) and new-only (products the
customer has never bought are the only candidates).
Writes data/interim/s03_baselines.json. Run from any directory:  python -I research/s03_baselines.py
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from implicit.als import AlternatingLeastSquares
from mlxtend.frequent_patterns import association_rules, fpgrowth
from mlxtend.preprocessing import TransactionEncoder
from scipy import sparse

PROJECT = Path(__file__).resolve().parents[1]
ANALYSIS = PROJECT / "data" / "interim" / "analysis.parquet"
OUT = PROJECT / "data" / "interim" / "s03_baselines.json"
PRODUCT_CODE = re.compile(r"^\d{5}[A-Za-z]{0,3}$")
CUTS = ["2011-06-01", "2011-09-01"]  # primary first; the second is a sensitivity cut
HORIZON = pd.Timedelta(days=90)
K = 10
BOOT = 1000
RULE_MIN_INVOICES = 10
CHECK_TOP = 300


def purchase_lines():
    df = pd.read_parquet(ANALYSIS)
    inv = df["Invoice"].astype(str)
    product = df["StockCode"].astype(str).str.match(PRODUCT_CODE)
    mask = (df["Quantity"] > 0) & (df["Price"] > 0) & product & ~inv.str.startswith("C") & ~inv.str.startswith("A")
    return pd.DataFrame({"invoice": inv[mask], "code": df.loc[mask, "StockCode"].astype(str),
                         "date": df.loc[mask, "InvoiceDate"], "customer": df.loc[mask, "Customer ID"]})


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (centre - half, centre + half)


def metrics_from_top(top, test_sets, n_catalogue):
    """top: (n_users, K) catalogue indices; test_sets: list of (number of test products, set of catalogue indices)."""
    n = len(top)
    hit = np.zeros(n)
    rec = np.zeros(n)
    prec = np.zeros(n)
    ndcg = np.zeros(n)
    discounts = 1.0 / np.log2(np.arange(2, K + 2))
    for u in range(n):
        test_all, test_in = test_sets[u]
        rel = np.array([1.0 if j in test_in else 0.0 for j in top[u]])
        hits = rel.sum()
        hit[u] = 1.0 if hits > 0 else 0.0
        rec[u] = hits / test_all
        prec[u] = hits / K
        idcg = float(discounts[: min(test_all, K)].sum())
        ndcg[u] = float((rel * discounts).sum()) / idcg if idcg > 0 else 0.0
    coverage = len(set(top.ravel().tolist())) / n_catalogue
    return {"hit": hit, "recall": rec, "precision": prec, "ndcg": ndcg, "coverage": coverage}


def summarise(per_user):
    out = {}
    n = len(per_user["hit"])
    rng = np.random.default_rng(0)
    idx = rng.integers(0, n, (BOOT, n))
    for name in ("hit", "recall", "precision", "ndcg"):
        arr = per_user[name]
        boot = arr[idx].mean(axis=1)
        out[name] = {"value": round(float(arr.mean()), 4),
                     "ci95_bootstrap": [round(float(np.percentile(boot, 2.5)), 4),
                                        round(float(np.percentile(boot, 97.5)), 4)]}
    lo, hi = wilson(per_user["hit"].sum(), n)
    out["hit_wilson_ci95"] = [round(lo, 4), round(hi, 4)]
    out["coverage"] = round(float(per_user["coverage"]), 4)
    out["n_users"] = n
    return out


def pair_matrices(baskets_idx, n_cat):
    """Co-occurrence counts of products over baskets (each basket a list of catalogue indices)."""
    rows, cols = [], []
    for b, items in enumerate(baskets_idx):
        rows.extend([b] * len(items))
        cols.extend(items)
    B = sparse.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(len(baskets_idx), n_cat))
    co = (B.T @ B).toarray()
    return co


def check_against_mlxtend(baskets_codes, catalogue, co, item_n, n_baskets):
    """Confidences of pairs among the most frequent products, mlxtend against the matrix."""
    order = np.argsort(-item_n, kind="stable")[:CHECK_TOP]
    keep = {catalogue[i] for i in order}
    sub = [[c for c in b if c in keep] for b in baskets_codes]
    te = TransactionEncoder()
    onehot = pd.DataFrame(te.fit(sub).transform(sub), columns=te.columns_)
    frequent = fpgrowth(onehot, min_support=RULE_MIN_INVOICES / n_baskets, use_colnames=True, max_len=2)
    rules = association_rules(frequent, metric="confidence", min_threshold=0.0)
    rules = rules[(rules["antecedents"].apply(len) == 1) & (rules["consequents"].apply(len) == 1)]
    cat_idx = {c: i for i, c in enumerate(catalogue)}
    max_diff = 0.0
    compared = 0
    for r in rules.itertuples(index=False):
        a = cat_idx[next(iter(r.antecedents))]
        b = cat_idx[next(iter(r.consequents))]
        matrix_conf = co[a, b] / item_n[a]
        max_diff = max(max_diff, abs(matrix_conf - r.confidence))
        compared += 1
    # every pair with at least RULE_MIN_INVOICES co-occurrences among the subset must be in mlxtend's output
    sub_idx = [cat_idx[c] for c in keep]
    expected = sum(1 for i in sub_idx for j in sub_idx if i < j and co[i, j] >= RULE_MIN_INVOICES)
    return {"subset_products": len(keep), "pairs_mlxtend": compared, "pairs_matrix_at_least_10": int(expected),
            "max_abs_confidence_difference": float(max_diff)}


def run_cut(p, cut, results):
    T = pd.Timestamp(cut)
    train = p[p["date"] < T]
    test = p[(p["date"] >= T) & (p["date"] < T + HORIZON)]
    catalogue = sorted(train["code"].unique())
    cat_idx = {c: i for i, c in enumerate(catalogue)}
    n_cat = len(catalogue)

    train_c = train[train["customer"].notna()].copy()
    test_c = test[test["customer"].notna()].copy()
    train_c["customer"] = train_c["customer"].astype(int)
    test_c["customer"] = test_c["customer"].astype(int)
    train_users = sorted(train_c["customer"].unique())
    test_users = set(test_c["customer"].unique())
    eval_users = [u for u in train_users if u in test_users]
    user_pos = {u: i for i, u in enumerate(eval_users)}
    n_eval = len(eval_users)

    test_by_user = test_c.groupby("customer")["code"].apply(lambda s: set(s)).to_dict()
    test_sets = []
    for u in eval_users:
        items = test_by_user[u]
        test_sets.append((len(items), {cat_idx[c] for c in items if c in cat_idx}))
    test_items_total = sum(t[0] for t in test_sets)
    test_items_unseen = sum(t[0] - len(t[1]) for t in test_sets)

    pair = train_c.drop_duplicates(["invoice", "code", "customer"]).groupby(["customer", "code"]).agg(
        n_inv=("invoice", "size"), last=("date", "max")).reset_index()
    seen_mask = np.zeros((n_eval, n_cat), dtype=bool)
    own_count = np.zeros((n_eval, n_cat))
    own_recency = np.zeros((n_eval, n_cat))
    pair = pair[pair["customer"].isin(user_pos)]
    for row in pair.itertuples(index=False):
        i = user_pos[row.customer]
        j = cat_idx[row.code]
        seen_mask[i, j] = True
        own_count[i, j] = row.n_inv
        own_recency[i, j] = (row.last - (T - HORIZON)) / HORIZON
    shares = []
    for u in eval_users:
        items = test_by_user[u]
        i = user_pos[u]
        repeated = sum(1 for c in items if c in cat_idx and seen_mask[i, cat_idx[c]])
        shares.append(repeated / max(len(items), 1))
    repeat_share = float(np.mean(shares))
    cold_users = len(test_users) - len(test_users & set(train_users))

    inv_items = train.drop_duplicates(["invoice", "code"])
    pop = inv_items.groupby("code").size().reindex(catalogue).fillna(0).to_numpy(float)
    recent = train[train["date"] >= T - HORIZON].drop_duplicates(["invoice", "code"])
    recent_pop = recent.groupby("code").size().reindex(catalogue).fillna(0).to_numpy(float)
    tiebreak = pop / (pop.max() + 1.0) * 1e-6

    scores = {}
    rng = np.random.default_rng(0)
    scores["random"] = rng.random((n_eval, n_cat))
    scores["popularity"] = np.tile(pop + tiebreak, (n_eval, 1))
    scores["recent_popularity"] = np.tile(recent_pop + tiebreak, (n_eval, 1))
    scores["own_repeats"] = own_count + 0.5 * own_recency + tiebreak

    # Pair rules on every training basket (guest baskets included), from a sparse co-occurrence matrix
    baskets = train.groupby("invoice")["code"].apply(lambda s: sorted(set(s)))
    n_baskets = len(baskets)
    baskets_idx = [[cat_idx[c] for c in items] for items in baskets.tolist()]
    co = pair_matrices(baskets_idx, n_cat)
    item_n = np.diag(co).copy()
    item_rate = item_n / n_baskets
    with np.errstate(divide="ignore", invalid="ignore"):
        conf = np.where(item_n[:, None] > 0, co / item_n[:, None], 0.0)
        lift = np.where(item_rate[None, :] > 0, conf / item_rate[None, :], 0.0)
    rule_mask = (co >= RULE_MIN_INVOICES) & (lift > 1.0)
    np.fill_diagonal(rule_mask, False)
    conf_rules = np.where(rule_mask, conf, 0.0)
    n_rules = int(rule_mask.sum())
    check = check_against_mlxtend(baskets.tolist(), catalogue, co, item_n, n_baskets)
    print(f"    mlxtend check on the {check['subset_products']} most frequent products: "
          f"{check['pairs_mlxtend']} pairs from mlxtend, {check['pairs_matrix_at_least_10']} pairs with >= 10 invoices "
          f"in the matrix, max |confidence difference| {check['max_abs_confidence_difference']:.2e}")
    rule_scores = np.zeros((n_eval, n_cat))
    for i in range(n_eval):
        seen_idx = np.flatnonzero(seen_mask[i])
        if len(seen_idx):
            rule_scores[i] = conf_rules[seen_idx].max(axis=0)
    scores["association_rules"] = rule_scores + tiebreak

    # ALS on every training customer, then the evaluated users' rows
    tu = {u: i for i, u in enumerate(train_users)}
    rows = train_c["customer"].map(tu).to_numpy()
    cols = train_c["code"].map(cat_idx).to_numpy()
    m = sparse.coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(len(train_users), n_cat)).tocsr()
    m.data[:] = 1.0
    model = AlternatingLeastSquares(factors=64, regularization=0.01, iterations=15, random_state=0,
                                    num_threads=1, use_gpu=False)
    model.fit((m * 20.0).astype(np.float32), show_progress=False)
    U = np.asarray(model.user_factors)
    V = np.asarray(model.item_factors)
    eval_rows = [tu[u] for u in eval_users]
    scores["als"] = U[eval_rows] @ V.T + tiebreak

    results[cut] = {
        "train_purchase_lines": int(len(train)),
        "train_baskets": int(n_baskets),
        "catalogue_products": n_cat,
        "association_rules_pairs": n_rules,
        "rule_min_invoices": RULE_MIN_INVOICES,
        "rule_lift_min": 1.0,
        "mlxtend_check": check,
        "test_window": [str(T.date()), str((T + HORIZON - pd.Timedelta(days=1)).date())],
        "eval_users": n_eval,
        "test_customers_all": int(len(test_users)),
        "test_customers_without_training_history": int(cold_users),
        "test_items_total": int(test_items_total),
        "test_items_unseen_in_training_catalogue_share": round(test_items_unseen / max(test_items_total, 1), 4),
        "test_items_repeat_share_for_eval_users": round(repeat_share, 4),
        "methods": {},
    }
    print(f"[cut {cut}] train lines {len(train)}, baskets {n_baskets}, catalogue {n_cat}, rule pairs {n_rules}; "
          f"eval users {n_eval}; test customers {len(test_users)} ({cold_users} without training history); "
          f"test items {test_items_total} ({test_items_unseen / max(test_items_total, 1) * 100:.1f} % not in catalogue); "
          f"repeat share {repeat_share * 100:.1f} %")
    for name, S in scores.items():
        for variant in ("unrestricted", "new_only"):
            M = S.copy()
            if variant == "new_only":
                M[seen_mask] = -np.inf
            top = np.argsort(-M, axis=1, kind="stable")[:, :K]
            summary = summarise(metrics_from_top(top, test_sets, n_cat))
            results[cut]["methods"].setdefault(name, {})[variant] = summary
            print(f"    {name:18s} {variant:12s} hit {summary['hit']['value']:.4f} "
                  f"{summary['hit']['ci95_bootstrap']} recall {summary['recall']['value']:.4f} "
                  f"prec {summary['precision']['value']:.4f} ndcg {summary['ndcg']['value']:.4f} "
                  f"coverage {summary['coverage']:.3f}")
            del M
    del scores


def main():
    p = purchase_lines()
    results = {"k": K, "bootstrap_resamples": BOOT, "cuts": {}}
    for cut in CUTS:
        run_cut(p, cut, results["cuts"])
    OUT.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[out] {OUT.relative_to(PROJECT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
