-- What each round built and delivered (round_ops), with the small cells hidden (plan section 19; decision D30). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).
-- A cell that counts customers is empty when it has fewer than :min_cell_customers. The base is the total of the round and ``offer`` and ``control`` are its two parts: if either part, or the base, is hidden the two
-- parts are hidden, because the one that is shown would give the other back by subtraction; ``delivered`` goes with ``offer`` for the same reason (a complete delivery is the offer group).
DROP TABLE IF EXISTS star_fact_round_ops;

CREATE TABLE star_fact_round_ops AS
WITH cells AS (
    SELECT o.round_id AS round_key, o.base, o.offer, o.control, o.new_assignments, o.delivered, o.fallback_share, r.buyers_outside_base, o.seconds,
           (o.base < :min_cell_customers) AS h_base,
           (o.base < :min_cell_customers OR o.offer < :min_cell_customers OR o.control < :min_cell_customers) AS h_split,
           (o.new_assignments < :min_cell_customers) AS h_new,
           (o.base < :min_cell_customers OR o.offer < :min_cell_customers OR o.control < :min_cell_customers OR o.delivered < :min_cell_customers) AS h_delivered,
           (r.buyers_outside_base < :min_cell_customers) AS h_outside
    FROM round_ops AS o
    JOIN ref_round AS r ON r.round_key = o.round_id
)
SELECT round_key,
       CASE WHEN h_base THEN NULL ELSE base END AS base,
       CASE WHEN h_split THEN NULL ELSE offer END AS offer,
       CASE WHEN h_split THEN NULL ELSE control END AS control,
       CASE WHEN h_new THEN NULL ELSE new_assignments END AS new_assignments,
       CASE WHEN h_delivered THEN NULL ELSE delivered END AS delivered,
       fallback_share,
       CASE WHEN h_outside THEN NULL ELSE buyers_outside_base END AS buyers_outside_base,
       seconds,
       (h_base OR h_split OR h_new OR h_delivered OR h_outside) AS suppressed
FROM cells
ORDER BY round_key;
