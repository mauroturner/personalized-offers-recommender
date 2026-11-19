-- A line without a customer is a guest line and never a purchase of a customer, and a purchase always has its customer (AC08): a guest is never counted as a customer.
SELECT line_key, role, customer_id IS NOT NULL AS has_customer
FROM lines
WHERE (role = 'purchase' AND customer_id IS NULL) OR (role = 'guest_purchase' AND customer_id IS NOT NULL)
