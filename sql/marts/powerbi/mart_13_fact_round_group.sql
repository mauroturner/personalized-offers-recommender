-- The follow-up of each round by group and segment (contact_base, holdout_assignments, round_outcomes), with the small cells hidden and a second one where a group would hide only one (plan section 19; decision
-- D30). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).
-- A cell is hidden when its customers, its buyers or its buyers of a product of the list are fewer than :min_cell_customers: then all its numbers are empty. ``fact_round_ops`` publishes the customers of each group
-- of the round and ``fact_method_round`` the pairs of the round (the buyers of both groups), so a group with exactly one hidden cell would give it back by subtraction: then the smallest shown cell of that
-- group (fewest customers, then the lowest segment) is hidden too. With two or more hidden cells no one of them can be recovered, and with none there is nothing to protect.
DROP TABLE IF EXISTS star_fact_round_group;

CREATE TABLE star_fact_round_group AS
WITH members AS (
    SELECT c.round_id, h.grp AS group_key, c.segment AS segment_key, o.customer_id IS NOT NULL AS followed, o.bought, o.products_in_offer, o.spend
    FROM contact_base AS c
    JOIN holdout_assignments AS h ON h.customer_id = c.customer_id
    JOIN ref_round AS r ON r.round_key = c.round_id
    LEFT JOIN round_outcomes AS o ON o.round_id = c.round_id AND o.customer_id = c.customer_id
),
cells AS (
    SELECT round_id, group_key, segment_key, COUNT(*) AS customers, MAX(followed) AS followed, SUM(bought) AS buyers, SUM(CASE WHEN products_in_offer > 0 THEN 1 ELSE 0 END) AS buyers_of_listed,
           SUM(CAST(spend AS REAL)) AS spend
    FROM members
    GROUP BY round_id, group_key, segment_key
),
flagged AS (
    SELECT *, (customers < :min_cell_customers OR (followed = 1 AND (buyers < :min_cell_customers OR buyers_of_listed < :min_cell_customers))) AS small FROM cells
),
ranked AS (
    SELECT *, SUM(small) OVER (PARTITION BY round_id, group_key) AS hidden,
           ROW_NUMBER() OVER (PARTITION BY round_id, group_key, small ORDER BY customers, segment_key) AS order_in_kind
    FROM flagged
),
decided AS (
    SELECT *, (small = 1 OR (hidden = 1 AND small = 0 AND order_in_kind = 1)) AS suppressed FROM ranked
)
SELECT round_id AS round_key, group_key, segment_key,
       CASE WHEN suppressed THEN NULL ELSE customers END AS customers,
       CASE WHEN suppressed OR followed = 0 THEN NULL ELSE buyers END AS buyers,
       CASE WHEN suppressed OR followed = 0 THEN NULL ELSE buyers_of_listed END AS buyers_of_listed,
       CASE WHEN suppressed OR followed = 0 THEN NULL ELSE ROUND(spend, 2) END AS spend,
       suppressed
FROM decided
ORDER BY round_key, group_key, segment_key;
