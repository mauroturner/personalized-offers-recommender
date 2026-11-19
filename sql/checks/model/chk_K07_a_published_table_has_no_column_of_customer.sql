-- K07: no published table has a column that holds a customer (decision D30): the private list is the only one, and it is not a published table. A violation is the table and the column.
SELECT m.name AS table_name, p.name AS column_name
FROM sqlite_master AS m, pragma_table_info(m.name) AS p
WHERE m.type = 'table' AND m.name LIKE 'star\_%' ESCAPE '\' AND m.name <> 'star_fact_offer_customer' AND p.name IN ('customer_id', 'customer', 'contact_id', 'email');
