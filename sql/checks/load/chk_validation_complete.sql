-- Every run that loaded a delivery has the four blocking rules of the delivery (V10 to V13) in its validation.
SELECT r.run_key AS run_key
FROM pipeline_runs r
WHERE r.delivery_id IS NOT NULL
  AND (SELECT COUNT(*) FROM validation_results v WHERE v.run_key = r.run_key AND v.rule_id IN ('V10', 'V11', 'V12', 'V13')) < 4
