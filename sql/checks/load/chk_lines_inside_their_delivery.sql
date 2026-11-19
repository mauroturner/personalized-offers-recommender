-- Every line has its date inside the days of the delivery that brought it (V12, read from what is stored).
SELECT l.line_key AS line_key, l.delivery_id AS delivery_id
FROM lines l JOIN deliveries d ON d.delivery_id = l.delivery_id
WHERE substr(l.invoice_date, 1, 10) NOT BETWEEN d.first_day AND d.last_day
