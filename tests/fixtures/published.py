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
