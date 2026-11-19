"""Lines made by hand for the tests of the deliveries, the warehouse, the base and the control group (U05 on): each row says only what it needs and the rest is an ordinary purchase."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from personaloffers import workbook as wb


def hand_frame(*rows: dict) -> pd.DataFrame:
    """Lines with the columns of the canonical file; each row says only what it needs and the rest is an ordinary purchase."""
    base = dict(invoice="500001", stock_code="95000", description="PRODUCTO SINTÉTICO 1", quantity=1, price=2.5, customer_id=90001, country="United Kingdom",
                internal_repeat=False, role="purchase", invoice_date=datetime(2011, 3, 29, 10, 0))
    data = [base | row | {"line_key": row.get("line_key", 20_000_001 + i)} for i, row in enumerate(rows)]
    frame = pd.DataFrame(data)
    frame["customer_id"] = pd.array(frame["customer_id"], dtype="Int64")
    for column in ("invoice", "stock_code", "description", "country", "role"):
        frame[column] = pd.array(frame[column], dtype="string")
    frame["invoice_date"] = frame["invoice_date"].astype("datetime64[us]")
    return frame[list(wb.LINE_COLUMNS)]
