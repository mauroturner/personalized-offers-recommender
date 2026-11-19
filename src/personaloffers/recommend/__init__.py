"""The recommenders of a round (RF10, RF11; plan section 9; decisions D09 to D13, D18, D23).

Every function here is given the history that ``personaloffers.base.history_before`` cut for the Monday of the round, and each one that reads it starts with ``check_no_leak``
(M01): a line dated at or after the Monday is a ``LeakageError``, so a missing cut is a failure and not a score that is a little too good. None of these modules reads the lines
by itself (a static test checks it), and a line without a customer enters only the popularity and the rules, never a customer (AC08).

What is common is in ``context`` (the catalogue of the round, the base customers, what each one bought, the popularity counts and the order that breaks every tie); the recommenders are
``popularity``, ``repeats``, ``rules`` and ``factor`` (ALS and cosine neighbours, with implicit); ``blend`` mixes a model with the trend and names a recipe; ``artifacts`` writes what was
fitted as flat ``.npy`` arrays with their hashes and reads it back only if the hash is the registered one (M02).
"""
