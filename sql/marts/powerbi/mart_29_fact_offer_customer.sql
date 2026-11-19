-- The list of every customer of every round (offer_lists), with whether the customer bought that product in the week of the round (ref_week_purchase). It has customer numbers: export writes it to outputs/private/
-- and it is never versioned (decisions D30, D45). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*). ``bought`` is empty for a round whose week has not arrived.
DROP TABLE IF EXISTS star_fact_offer_customer;

CREATE TABLE star_fact_offer_customer AS
SELECT l.round_id AS round_key, l.customer_id, l.rank, l.stock_code AS product_key, l.source AS source_key, l.grp AS group_key,
       CASE WHEN r.followed = 0 THEN NULL WHEN p.stock_code IS NOT NULL THEN 1 ELSE 0 END AS bought
FROM offer_lists AS l
JOIN ref_round AS r ON r.round_key = l.round_id
LEFT JOIN ref_week_purchase AS p ON p.round_id = l.round_id AND p.customer_id = l.customer_id AND p.stock_code = l.stock_code
ORDER BY round_key, l.customer_id, l.rank;
