## Days with no row

The daily table `fct_pool_daily` has one row for each pool and day on which that pool had at
least one swap. A day with no swap has no row. The data covers the days from 2026-08-09 to
2026-09-25; the first and the last of them only in part.

- For a pool that is in `dim_pools` and a day within those dates, a missing row in
  `fct_pool_daily` means the pool had no swap that day, or none in the part of the day the
  data covers. Its swaps, its volumes and its fees for that day are 0. Answer 0; do not
  refuse.
- The first or the last row of one pool is not the start or the end of the data. Use the
  dates above, not the range of one pool's rows.
- For a day outside those dates, or a pool that is not in `dim_pools`, the data does not
  cover it: refuse, and say why.
