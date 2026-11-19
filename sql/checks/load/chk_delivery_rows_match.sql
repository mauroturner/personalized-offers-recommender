-- A loaded delivery says how many lines it brought and the warehouse holds exactly that many lines for it.
SELECT d.delivery_id AS delivery_id, d.rows AS declared, (SELECT COUNT(*) FROM lines l WHERE l.delivery_id = d.delivery_id) AS found
FROM deliveries d
WHERE d.status = 'loaded' AND d.rows != (SELECT COUNT(*) FROM lines l WHERE l.delivery_id = d.delivery_id)
