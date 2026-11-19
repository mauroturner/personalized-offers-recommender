"""The role of every line (RF04, AC04; decision D04).

A line has exactly one role, the first of these that it meets, in this order:

1. ``cancellation``: the invoice starts with a capital «C».
2. ``adjustment``: the invoice starts with a capital «A» (the «adjust bad debt» lines).
3. ``non_product``: the code is not a product code by ``[catalogue] product_code_regex`` (service codes, vouchers, the ``DCGS`` lines).
4. ``bad_price``: the price or the quantity is zero or less, outside a cancellation.
5. ``guest_purchase``: no customer. It makes a basket (it counts for popularity and for the rules) and is never a customer.
6. ``purchase``: everything else, a line of a customer.

The code rule is applied with Python's ``re`` to each distinct code (about five thousand in the archive) with ``re.ASCII``: the ``\\d`` of the rule means the digits
0 to 9 and not the digits of other scripts, so a code written with Arabic-Indic digits is not a product, and a trailing line break is not either (the rule is applied
with ``fullmatch``). ``assign_roles`` reads five columns, takes the configuration or its sealed view (both carry ``catalogue``) and changes nothing.
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd

ROLES = ("cancellation", "adjustment", "non_product", "bad_price", "guest_purchase", "purchase")
PRODUCT_ROLES = ("purchase", "guest_purchase")      # the lines of a basket: the catalogue, the popularity and the rules count these


def assign_roles(frame: pd.DataFrame, view: Any) -> pd.Series:
    """The role of each line of `frame` (columns ``invoice``, ``stock_code``, ``quantity``, ``price`` and ``customer_id``), in its index and its order, as a ``string`` series.
    `view` is the configuration or the sealed view: only ``view.catalogue.product_code_regex`` is read."""
    pattern = re.compile(view.catalogue.product_code_regex, re.ASCII)
    invoice = frame["invoice"].astype("string")
    cancellation = invoice.str.startswith("C").fillna(False).to_numpy(dtype=bool)
    adjustment = invoice.str.startswith("A").fillna(False).to_numpy(dtype=bool)
    codes = frame["stock_code"].astype("string")
    verdict = {code: pattern.fullmatch(code) is not None for code in codes.dropna().unique()}
    is_product = codes.map(verdict).fillna(False).to_numpy(dtype=bool)
    bad_price = ((frame["price"] <= 0) | (frame["quantity"] <= 0)).to_numpy(dtype=bool)
    guest = frame["customer_id"].isna().to_numpy(dtype=bool)
    chosen = np.select([cancellation, adjustment, ~is_product, bad_price, guest], ROLES[:5], default=ROLES[5])
    return pd.Series(pd.array(chosen, dtype="string"), index=frame.index, name="role")
