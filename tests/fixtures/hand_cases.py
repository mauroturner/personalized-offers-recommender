"""Cases worked out by hand (U03, plan section 24): popularity, own repeats, association rules, the factorization and the similarity on a matrix of 6 by 8, the
list, the metrics, the experiment (SMD, CUPED, an exact permutation test, the minimum detectable effect) and the choice among candidates.

Every expected value is written here as a literal, from arithmetic anyone can redo (the comment of each case shows it); ``tests/unit/test_hand_cases.py``
checks each one against a second, independent computation, so a typo in a case is found before a unit trusts it. The units that write the code use these as
the right answers and never compute them with the code under test.
"""

from __future__ import annotations

from datetime import date
from fractions import Fraction

# --- popularity (RF10, D18) and own repeats ---------------------------------------------------------------------------------
# History lines (invoice, customer or None, day, product), purchase lines only; the round is the Monday 2011-08-01, so the last line (2011-08-02) never counts.
# I2 has the line of product A twice, and I5 too: an invoice counts once for a product.
POPULARITY_MONDAY = date(2011, 8, 1)
POPULARITY_HISTORY = (
    ("I1", 1, date(2011, 7, 1), "A"), ("I1", 1, date(2011, 7, 1), "B"),
    ("I2", 2, date(2011, 7, 10), "A"), ("I2", 2, date(2011, 7, 10), "A"), ("I2", 2, date(2011, 7, 10), "C"),
    ("I3", 3, date(2011, 7, 20), "A"), ("I3", 3, date(2011, 7, 20), "B"),
    ("I4", None, date(2011, 7, 25), "B"),                                  # a guest: counts for popularity, never as a customer
    ("I5", 1, date(2011, 7, 30), "A"), ("I5", 1, date(2011, 7, 30), "A"),
    ("I6", 2, date(2011, 8, 2), "C"),                                       # after the Monday
    ("I7", 4, date(2011, 3, 1), "D"),                                       # old: in the global count, outside the 28 days
)
GLOBAL_POPULARITY = {"A": 4, "B": 3, "C": 1, "D": 1}                          # A: I1 I2 I3 I5; B: I1 I3 I4; C: I2; D: I7
RECENT_POPULARITY_28_DAYS = {"A": 3, "B": 2, "C": 1}                         # from 2011-07-04: A: I2 I3 I5; B: I3 I4; C: I2 (I1 is 07-01, I7 is old)
# score = invoices of the customer with the product + 0.5 x (last day - (Monday - 90 days)) / 90 days; the Monday - 90 days is 2011-05-03.
# The term is not clamped: customer 4's purchase is 63 days before that point, so it is negative.
REPEAT_SCORES = {
    (1, "A"): Fraction(112, 45),    # 2 + 0.5 x 88 / 90  (last purchase 07-30)
    (1, "B"): Fraction(239, 180),   # 1 + 0.5 x 59 / 90  (07-01)
    (2, "A"): Fraction(62, 45),     # 1 + 0.5 x 68 / 90  (07-10)
    (2, "C"): Fraction(62, 45),     # the same day, the same score
    (3, "A"): Fraction(43, 30),     # 1 + 0.5 x 78 / 90  (07-20)
    (3, "B"): Fraction(43, 30),
    (4, "D"): Fraction(13, 20),     # 1 + 0.5 x (-63) / 90
}
REPEAT_ORDER = {1: ("A", "B"), 2: ("A", "C"), 3: ("A", "B"), 4: ("D",)}       # a tie goes to the more popular product (A has 4 invoices, C one)

# --- association rules (RF10, AC11) -----------------------------------------------------------------------------------------
# Five baskets over A B C D. Counts: A 4, B 4, C 3, D 2; pairs: AB 3, AC 2, AD 1, BC 2, BD 2, CD 1.
# confidence(X -> Y) = n(XY) / n(X); rule_lift = n(XY) x 5 / (n(X) x n(Y)).
RULE_BASKETS = (("A", "B", "C"), ("A", "B"), ("A", "C"), ("B", "C", "D"), ("A", "B", "D"))
RULE_ITEM_COUNTS = {"A": 4, "B": 4, "C": 3, "D": 2}
RULE_PAIR_COUNTS = {("A", "B"): 3, ("A", "C"): 2, ("A", "D"): 1, ("B", "C"): 2, ("B", "D"): 2, ("C", "D"): 1}
RULES = {   # (antecedent, consequent): (support in invoices, confidence, rule_lift)
    ("A", "B"): (3, Fraction(3, 4), Fraction(15, 16)), ("B", "A"): (3, Fraction(3, 4), Fraction(15, 16)),
    ("A", "C"): (2, Fraction(1, 2), Fraction(5, 6)), ("C", "A"): (2, Fraction(2, 3), Fraction(5, 6)),
    ("A", "D"): (1, Fraction(1, 4), Fraction(5, 8)), ("D", "A"): (1, Fraction(1, 2), Fraction(5, 8)),
    ("B", "C"): (2, Fraction(1, 2), Fraction(5, 6)), ("C", "B"): (2, Fraction(2, 3), Fraction(5, 6)),
    ("B", "D"): (2, Fraction(1, 2), Fraction(5, 4)), ("D", "B"): (2, Fraction(1, 1), Fraction(5, 4)),
    ("C", "D"): (1, Fraction(1, 3), Fraction(5, 6)), ("D", "C"): (1, Fraction(1, 2), Fraction(5, 6)),
}
# The rules that pass (minimum support in invoices, minimum lift; the lift must be strictly greater)
RULES_KEPT = {
    (2, Fraction(1)): {("B", "D"), ("D", "B")},
    (2, Fraction(0)): {("A", "B"), ("B", "A"), ("A", "C"), ("C", "A"), ("B", "C"), ("C", "B"), ("B", "D"), ("D", "B")},
    (1, Fraction(0)): set(RULES),
}
# With minimum support 2 and minimum lift 0, the score of a product for a customer is the highest confidence from a product the customer bought
RULE_SCORES = {
    ("A",): {"B": Fraction(3, 4), "C": Fraction(1, 2)},
    ("B",): {"A": Fraction(3, 4), "C": Fraction(1, 2), "D": Fraction(1, 2)},
    ("A", "D"): {"B": Fraction(1), "C": Fraction(1, 2)},      # B: the best of A -> B (3/4) and D -> B (1); D -> A and D -> C have support 1
}

# --- the factorization and the similarity on 6 customers by 8 products (RF10, AC11) -------------------------------------------
# Two blocks that never mix: customers 0-2 buy products 0-3, customers 3-5 buy products 4-7, each missing one product of its block.
MATRIX_PURCHASES = {0: (0, 1, 2), 1: (0, 1, 3), 2: (1, 2, 3), 3: (4, 5, 6), 4: (4, 5, 7), 5: (5, 6, 7)}
MATRIX_MISSING = {0: 3, 1: 2, 2: 0, 3: 7, 4: 6, 5: 4}        # the one product of its block that each customer has not bought: the top of the list for both models
# Cosine between product columns, e.g. products 3 and 1: 2 / (sqrt(2) x sqrt(3)); the score of a customer for a product is the sum of the similarities from what they bought.
# For the missing product that is 1/2 + 2/sqrt(6) + 1/2 = 1 + 0.8164965809277260..., and every product of the other block scores exactly 0.
COSINE_TOP_SCORE = 1.8164965809277258

# --- the list (RF11, AC12; D10) ----------------------------------------------------------------------------------------------
# 12 products (0 to 11); the fallback is the order of the 28-day popularity, most sold first. A list is (product, source) in order.
LIST_FALLBACK = (3, 1, 4, 0, 5, 2, 8, 6, 7, 9, 10, 11)
LIST_CASES = {
    # nine own products: the seven best by repeat score, then the three best never bought (the scores of the bought ones are high and ignored)
    "rich": {"repeat": {0: 9.0, 1: 8.0, 2: 7.0, 3: 6.0, 4: 5.0, 5: 4.0, 6: 3.0, 7: 2.0, 8: 1.0},
             "discovery": {0: 5.0, 1: 5.0, 2: 5.0, 3: 5.0, 4: 5.0, 5: 5.0, 6: 5.0, 7: 5.0, 8: 5.0, 9: 0.9, 10: 0.7, 11: 0.8},
             "expected": [(0, "repeat"), (1, "repeat"), (2, "repeat"), (3, "repeat"), (4, "repeat"), (5, "repeat"), (6, "repeat"),
                          (9, "discovery"), (11, "discovery"), (10, "discovery")]},
    # one invoice, two products: the discovery takes the eight places that the repeats leave free; product 1 scores 0 and is out
    "one_invoice": {"repeat": {2: 2.1, 3: 2.3},
                    "discovery": {2: 3.0, 3: 3.0, 0: 0.4, 1: 0.0, 4: 0.9, 5: 0.3, 6: 0.8, 7: 0.2, 8: 0.7, 9: 0.6, 10: 0.1, 11: 0.5},
                    "expected": [(3, "repeat"), (2, "repeat"), (4, "discovery"), (6, "discovery"), (8, "discovery"), (9, "discovery"), (11, "discovery"),
                                 (0, "discovery"), (5, "discovery"), (7, "discovery")]},
    # the model has two candidates only: the rest is the fallback in its order, skipping what the list already holds
    "few_candidates": {"repeat": {5: 1.4}, "discovery": {7: 0.6, 2: 0.3},
                       "expected": [(5, "repeat"), (7, "discovery"), (2, "discovery"), (3, "fallback"), (1, "fallback"), (4, "fallback"), (0, "fallback"),
                                    (8, "fallback"), (6, "fallback"), (9, "fallback")]},
    # no discovery at all: the fallback starts with product 3, which the list holds already, and goes on after it
    "no_discovery": {"repeat": {3: 1.0}, "discovery": {},
                     "expected": [(3, "repeat"), (1, "fallback"), (4, "fallback"), (0, "fallback"), (5, "fallback"), (2, "fallback"), (8, "fallback"),
                                  (6, "fallback"), (7, "fallback"), (9, "fallback")]},
}
# Ties: the same score goes to the more popular product, and the same popularity to the lower code (D11)
TIE_SCORES = {4: 0.5, 5: 0.5, 6: 0.5}
TIE_POPULARITY = {4: 3, 5: 3, 6: 7}
TIE_ORDER = (6, 4, 5)

# --- the metrics at 5 (RF18, AC21; D08) ------------------------------------------------------------------------------------
# hit = some product of the list was bought; recall = hits / distinct products bought; precision = hits / 5; NDCG = DCG / IDCG with 1 / log2(rank + 1).
# Purchases are sets: product b is bought twice by u1 and counts once. u1's lists holds b (rank 2) and e (rank 5) of {b, e, z}.
METRIC_K = 5
METRIC_LISTS = {"u1": ("a", "b", "c", "d", "e"), "u2": ("f", "g", "h", "a", "b"), "u3": ("a", "i", "j", "k", "l")}
METRIC_BOUGHT = {"u1": ("b", "b", "e", "z"), "u2": ("x", "y"), "u3": ("a",)}
METRIC_EXPECTED = {   # hit, recall, precision, ndcg
    "u1": (1.0, 2 / 3, 0.4, 0.4776237035032179),    # DCG = 1/log2(3) + 1/log2(6); IDCG = 1 + 1/log2(3) + 1/log2(4) = 2.1309...
    "u2": (0.0, 0.0, 0.0, 0.0),
    "u3": (1.0, 1.0, 0.2, 1.0),                      # the only product bought is first: DCG = IDCG = 1
}
METRIC_MEANS = (2 / 3, 5 / 9, 0.2, 0.4925412345010726)
METRIC_CATALOGUE = 20      # products with a purchase in the last 365 days
METRIC_COVERAGE = 0.6      # the lists hold 12 distinct products: a b c d e f g h i j k l
# Wilson interval of 95 % (z = 1.959963984540054) for hits out of pairs
WILSON_CASES = ((8, 10, (0.4901624715366418, 0.9433178485456247)), (0, 10, (0.0, 0.2775327998628892)), (10, 10, (0.7224672001371106, 1.0)))
# Resampling by customer: every pair of a customer moves with it. Pairs (customer, hit of the list, hit of the baseline); the customers drawn are c1, c1, c3:
# c1's two pairs twice and c3's one: hits of the list 1 1 1 1 1 -> 5/5; of the baseline 0 1 0 1 0 -> 2/5; the paired difference is 3/5.
RESAMPLE_PAIRS = (("c1", 1, 0), ("c1", 1, 1), ("c2", 0, 0), ("c3", 1, 0))
RESAMPLE_DRAW = ("c1", "c1", "c3")
RESAMPLE_EXPECTED = (1.0, 0.4, 0.6)

# --- the experiment (RF18, AC22; D15) -----------------------------------------------------------------------------------------
# Standardized mean difference with the sample variances: (6.5 - 5) / sqrt((35/3 + 20/3) / 2)
SMD_CONTROL = (2.0, 4.0, 6.0, 8.0)
SMD_OFFER = (3.0, 5.0, 7.0, 11.0)
SMD_EXPECTED = 0.49543369430686224
# CUPED: theta = cov(y, x) / var(x) = 33.5 / 17.5; adjusted y = y - theta (x - mean x). The variance goes from 13.1 to 0.2743...
CUPED_X = (1.0, 2.0, 3.0, 4.0, 5.0, 6.0)
CUPED_Y = (3.0, 4.0, 7.0, 8.0, 11.0, 12.0)
CUPED_THETA = 1.9142857142857144
CUPED_ADJUSTED = (7.785714285714286, 6.871428571428572, 7.957142857142857, 7.042857142857143, 8.128571428571428, 7.214285714285714)
# Exact stratified permutation: customers 1-4 are stratum 1 and 5-8 stratum 2, two of each stratum in control (36 assignments: 6 x 6). The observed control
# is {1, 2, 5, 6}: offer mean (4 + 6 + 3 + 7) / 4 = 5, control mean (10 + 12 + 2 + 8) / 4 = 8, difference -3; 10 of the 36 assignments are as far from 0.
PERMUTATION_STRATA = {1: 1, 2: 1, 3: 1, 4: 1, 5: 2, 6: 2, 7: 2, 8: 2}
PERMUTATION_Y = {1: 10.0, 2: 12.0, 3: 4.0, 4: 6.0, 5: 2.0, 6: 8.0, 7: 3.0, 8: 7.0}
PERMUTATION_CONTROL = (1, 2, 5, 6)
PERMUTATION_DIFFERENCE = -3.0
PERMUTATION_ASSIGNMENTS = 36
PERMUTATION_AS_EXTREME = 10
PERMUTATION_P = Fraction(10, 36)
# Minimum detectable effect: (z(0.975) + z(0.80)) x sd x sqrt(1 / n_offer + 1 / n_control), with 3,456 offered and 864 in control (20 % of 4,320): the
# research's figures, 0.71 points of the share of weeks with a purchase (sd 0.0669) and 164.22 pounds of spend (sd 1,541.05)
MDE_Z = (1.959963984540054, 0.8416212335729143)
MDE_CASES = ((0.0669, 3456, 864, 0.007128991392157736), (1541.05, 3456, 864, 164.2172224945393))

# --- the choice among candidates (RF12, AC14; D12) ----------------------------------------------------------------------------
# A candidate is (name, base model, factors or neighbours or minimum invoices, trend weight, hit@10 on new products, coverage). The choice keeps those within
# half a point of the best hit, takes the highest coverage, then the lowest weight, then the simplest base (rules, cosine, ALS), then the smallest size.
CHOICE_CASES = (
    # c2 is 0.4 points under c1 and covers more; c3 covers most but is 0.9 points under, out of the tolerance
    ((("als_64_w1", "als", 64, 1.0, 0.340, 0.05), ("cosine_100_w0.5", "cosine", 100, 0.5, 0.336, 0.12), ("rules_10_w0", "rules", 10, 0.0, 0.331, 0.30)),
     "cosine_100_w0.5"),
    # all the same hit and coverage: the lowest weight (0.5), then the simplest base: rules before ALS
    ((("als_128_w1", "als", 128, 1.0, 0.300, 0.10), ("cosine_50_w1", "cosine", 50, 1.0, 0.300, 0.10), ("rules_5_w1", "rules", 5, 1.0, 0.300, 0.10),
      ("rules_5_w0.5", "rules", 5, 0.5, 0.300, 0.10), ("als_32_w0.5", "als", 32, 0.5, 0.300, 0.10)), "rules_5_w0.5"),
    ((("als_128_w1", "als", 128, 1.0, 0.300, 0.10), ("als_32_w0.5", "als", 32, 0.5, 0.300, 0.10), ("cosine_50_w0.5", "cosine", 50, 0.5, 0.300, 0.10)),
     "cosine_50_w0.5"),
    # the same base and weight: the smaller size
    ((("als_128_w1", "als", 128, 1.0, 0.300, 0.10), ("als_64_w1", "als", 64, 1.0, 0.300, 0.10)), "als_64_w1"),
)
CHOICE_TOLERANCE = 0.005
