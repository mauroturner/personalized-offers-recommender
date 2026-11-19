-- The products of the archive (ref_product). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).
DROP TABLE IF EXISTS star_dim_product;

CREATE TABLE star_dim_product AS
SELECT product_key, description_es, first_seen, popularity_band FROM ref_product ORDER BY product_key;
