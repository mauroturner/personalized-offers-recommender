-- K05: what a round published adds up where it shows all of it: the base is the offer group and the control group, and nothing was delivered that was not in the offer group (AC17, AC26). A violation is the round.
SELECT round_key, base, offer, control, delivered FROM star_fact_round_ops
WHERE (base IS NOT NULL AND offer IS NOT NULL AND control IS NOT NULL AND base <> offer + control) OR (offer IS NOT NULL AND delivered IS NOT NULL AND delivered > offer);
