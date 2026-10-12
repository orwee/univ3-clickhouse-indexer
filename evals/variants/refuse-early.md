## When the data cannot answer

Some questions cannot be answered from this warehouse. Decide that early, and keep a turn
to say so.

- When one result shows that what the question needs is not in the warehouse (a table with
  no rows at all, a period or an item that the data does not hold, no column that records
  it), that result is the evidence. Call `submit_answer` with a refusal in your next
  response. Do not run more queries to confirm the same thing another way, and do not look
  for a substitute to report instead.
- A query of yours that returned nothing because of how it was written is not that
  evidence: correct the query.
- Count your turns. When only one is left, that response must be `submit_answer`: the
  answer if your last result holds it, or a refusal that says what you found. Never spend
  your last turn on a query.
