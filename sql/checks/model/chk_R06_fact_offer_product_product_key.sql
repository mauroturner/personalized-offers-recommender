-- R06: every fact_offer_product[product_key] is a dim_product[product_key] (AC26). A violation is the key that has no row in the dimension and how many fact rows have it.
SELECT f.product_key AS fact_key, COUNT(*) AS fact_rows
FROM star_fact_offer_product AS f
WHERE f.product_key IS NULL OR f.product_key NOT IN (SELECT product_key FROM star_dim_product)
GROUP BY f.product_key;
