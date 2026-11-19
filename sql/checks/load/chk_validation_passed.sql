-- No run loaded a delivery whose validation failed a blocking rule (the load refuses it before writing; this is the same rule read from what is stored).
SELECT run_key, rule_id
FROM validation_results
WHERE severity = 'bloqueante' AND passed = 0
