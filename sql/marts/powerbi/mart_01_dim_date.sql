-- The calendar of the project (ref_date). Built by export.build_powerbi_marts inside its transaction, after the reference tables (ref_*).
DROP TABLE IF EXISTS star_dim_date;

CREATE TABLE star_dim_date AS
SELECT date_key, date, week_monday, period FROM ref_date ORDER BY date_key;
