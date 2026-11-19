-- A run that loaded a delivery has the instant of that delivery, and a run that is still ``running`` has not finished.
SELECT r.run_key AS run_key, r.status AS status, r.as_of AS run_as_of, d.as_of AS delivery_as_of
FROM pipeline_runs r LEFT JOIN deliveries d ON d.delivery_id = r.delivery_id
WHERE (r.delivery_id IS NOT NULL AND (d.delivery_id IS NULL OR r.as_of IS NOT d.as_of))
   OR (r.status = 'running' AND r.finished_at IS NOT NULL)
