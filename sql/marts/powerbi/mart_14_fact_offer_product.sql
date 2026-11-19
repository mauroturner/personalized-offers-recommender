-- The products of the lists of the offer group, with their origin, and how many of those customers bought them in the week (offer_lists, ref_week_purchase), with the small cells out (plan section 19; decision D30).
-- Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).
-- Only the rows offered to :min_cell_customers customers or more are there. A list has the same number of products for everyone, so the total offered of a round is known and a round with exactly one row left out
-- would give it back by subtraction: then the smallest row shown of that round (fewest customers, then the lowest key) is left out too. ``bought_by`` is empty when fewer than :min_cell_customers customers bought
-- the product (``suppressed``), and for a round whose week has not arrived.
DROP TABLE IF EXISTS star_fact_offer_product;

CREATE TABLE star_fact_offer_product AS
WITH offered AS (
    SELECT l.round_id, l.stock_code AS product_key, l.source AS source_key, COUNT(*) AS offered_to
    FROM offer_lists AS l
    JOIN ref_round AS r ON r.round_key = l.round_id
    WHERE l.grp = 'offer'
    GROUP BY l.round_id, l.stock_code, l.source
),
bought AS (
    SELECT l.round_id, l.stock_code AS product_key, l.source AS source_key, COUNT(*) AS bought_by
    FROM offer_lists AS l
    JOIN ref_week_purchase AS p ON p.round_id = l.round_id AND p.customer_id = l.customer_id AND p.stock_code = l.stock_code
    WHERE l.grp = 'offer'
    GROUP BY l.round_id, l.stock_code, l.source
),
flagged AS (
    SELECT o.round_id, o.product_key, o.source_key, o.offered_to, COALESCE(b.bought_by, 0) AS bought_by, r.followed, (o.offered_to < :min_cell_customers) AS small
    FROM offered AS o
    JOIN ref_round AS r ON r.round_key = o.round_id
    LEFT JOIN bought AS b ON b.round_id = o.round_id AND b.product_key = o.product_key AND b.source_key = o.source_key
),
ranked AS (
    SELECT *, SUM(small) OVER (PARTITION BY round_id) AS left_out,
           ROW_NUMBER() OVER (PARTITION BY round_id, small ORDER BY offered_to, product_key, source_key) AS order_in_kind
    FROM flagged
)
SELECT round_id AS round_key, product_key, source_key, offered_to,
       CASE WHEN followed = 0 OR bought_by < :min_cell_customers THEN NULL ELSE bought_by END AS bought_by,
       (followed = 1 AND bought_by < :min_cell_customers) AS suppressed
FROM ranked
WHERE small = 0 AND NOT (left_out = 1 AND order_in_kind = 1)
ORDER BY round_key, product_key, source_key;
