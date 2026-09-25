# Analysis report

Database `onchain` (1,240,618 swaps, through block 26,050,795) and the dbt marts in `onchain_dbt`, generated 2026-09-25 00:37 UTC by `make analysis`. Numbers only; what they mean is in docs/ROUND_TRIPS.md and docs/CROSS_POOL.md. Every query ran with the query condition cache off.

## Round trips in the same block

### 10_round_trips_by_pool.sql

Read 188 rows in 4 ms.

| pool | pool_days | pool_days_with_any | all_swaps | pairs | legs | legs_in_one_transaction_pairs | all_usd | legs_usd | net_usd | share_of_usd | share_of_swaps | median_daily_share_of_usd | largest_daily_share_of_usd |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| USDC/WETH 0.05% | 48 | 47 | 307,171 | 2,065 | 3,616 | 2,003 | 3,709,409,985.82 | 35,691,714.94 | 3,673,718,270.88 | 0.00962194 | 0.0117719 | 0.000579753 | 0.111841 |
| USDC/WETH 0.01% | 48 | 47 | 926,420 | 3,147 | 5,759 | 344 | 2,256,005,098.41 | 551,362,564.97 | 1,704,642,533.44 | 0.244398 | 0.0062164 | 0.248128 | 0.494191 |
| wstETH/USDC 0.05% | 47 | 36 | 6,096 | 81 | 162 | 2 | 26,398,379.60 | 106,758.88 | 26,291,620.72 | 0.00404415 | 0.0265748 | 0.162146 | 0.91061 |
| wstETH/USDC 0.3% | 45 | 5 | 931 | 6 | 12 | 0 | 92,811.68 | 5,340.19 | 87,471.49 | 0.0575379 | 0.0128894 | 0 | 0.906658 |
|  | 188 | 135 | 1,240,618 | 5,299 | 9,549 | 2,349 | 5,991,906,275.51 | 587,166,378.97 | 5,404,739,896.53 | 0.0979933 | 0.00769697 | 0.0158624 | 0.91061 |

### 11_round_trips_by_hour.sql

Read 1,250,171 rows in 199 ms.

| hour_utc | hour_swaps | hour_usd | leg_swaps | leg_usd | share_of_usd |
|---|---|---|---|---|---|
| 0 | 53,435 | 221,454,062.23 | 406 | 14,575,026.69 | 0.0658151 |
| 1 | 53,972 | 234,974,643.81 | 433 | 23,403,780.41 | 0.0996013 |
| 2 | 51,421 | 210,803,046.08 | 446 | 21,404,574.78 | 0.101538 |
| 3 | 48,519 | 169,067,939.46 | 422 | 18,539,112.07 | 0.109655 |
| 4 | 45,689 | 149,308,658.37 | 322 | 14,247,386.88 | 0.0954224 |
| 5 | 48,828 | 216,320,498.68 | 470 | 36,569,320.69 | 0.169052 |
| 6 | 47,128 | 161,549,156.35 | 369 | 14,520,433.45 | 0.0898824 |
| 7 | 46,009 | 165,793,446.05 | 321 | 12,453,781.18 | 0.0751162 |
| 8 | 49,206 | 230,323,373.06 | 326 | 27,507,830.83 | 0.119431 |
| 9 | 49,112 | 243,031,540.65 | 356 | 18,264,503.51 | 0.0751528 |
| 10 | 48,250 | 188,714,425.14 | 401 | 13,226,255.35 | 0.0700861 |
| 11 | 49,505 | 182,219,022.66 | 370 | 17,332,740.90 | 0.0951204 |
| 12 | 53,185 | 304,739,992.05 | 365 | 20,955,248.87 | 0.0687644 |
| 13 | 56,585 | 409,217,882.31 | 389 | 50,953,556.54 | 0.124514 |
| 14 | 58,419 | 468,399,680.93 | 519 | 51,018,152.58 | 0.10892 |
| 15 | 56,101 | 444,494,832.49 | 408 | 39,251,472.18 | 0.0883058 |
| 16 | 55,504 | 372,253,867.64 | 486 | 54,259,395.09 | 0.145759 |
| 17 | 53,238 | 250,634,309.99 | 436 | 17,165,246.25 | 0.0684872 |
| 18 | 53,950 | 265,096,448.02 | 438 | 29,335,171.65 | 0.110658 |
| 19 | 53,936 | 225,539,708.81 | 385 | 18,144,698.94 | 0.0804501 |
| 20 | 52,225 | 238,032,922.04 | 368 | 20,140,137.11 | 0.0846107 |
| 21 | 54,429 | 260,419,268.30 | 372 | 25,411,526.72 | 0.0975793 |
| 22 | 51,342 | 221,844,089.59 | 414 | 19,389,875.57 | 0.0874032 |
| 23 | 50,630 | 157,673,460.82 | 327 | 9,097,150.73 | 0.0576961 |

### 12_round_trips_concentration.sql

Read 9,549 rows in 6 ms.

| senders | total_legs | total_usd | top1_share_of_usd | top3_share_of_usd | top10_share_of_usd | top1_share_of_legs | top10_share_of_legs | senders_with_one_pair_at_most |
|---|---|---|---|---|---|---|---|---|
| 124 | 9,549 | 587,166,378.97 | 0.253019 | 0.697603 | 0.974681 | 0.0561315 | 0.31197 | 49 |

### 13_round_trips_tolerance.sql

Read 9,924,950 rows in 1,617 ms.

| tolerance | pairs | legs | legs_usd | share_of_usd | share_of_swaps |
|---|---|---|---|---|---|
| 0 | 113 | 226 | 7,224,566.34 | 0.00120572 | 0.000182167 |
| 0.01 | 1,841 | 3,239 | 437,463,798.82 | 0.0730091 | 0.0026108 |
| 0.05 | 3,126 | 5,558 | 547,587,345.48 | 0.0913878 | 0.00448003 |
| 0.1 | 5,299 | 9,549 | 587,166,378.97 | 0.0979933 | 0.00769697 |
| 0.2 | 7,676 | 13,488 | 611,523,041.40 | 0.102058 | 0.010872 |
| 0.5 | 15,089 | 24,316 | 639,276,541.44 | 0.10669 | 0.0195999 |

### 14_round_trips_leg_sizes.sql

Read 19,098 rows in 10 ms.

| leg_size_usd | legs | usd | share_of_round_trip_usd | usd_of_legs_that_undo |
|---|---|---|---|---|
| 1. under 1k | 5,509 | 913,925.52 | 0.0015565 | 465,177.14 |
| 2. 1k to 10k | 1,068 | 3,512,508.81 | 0.00598214 | 1,792,358.18 |
| 3. 10k to 100k | 1,526 | 69,678,062.49 | 0.118668 | 34,662,400.10 |
| 4. 100k to 1M | 1,352 | 353,302,522.28 | 0.601708 | 175,589,884.88 |
| 5. 1M and more | 94 | 159,759,359.87 | 0.272085 | 79,751,393.28 |
|  | 9,549 | 587,166,378.97 | 1.00 | 292,261,213.58 |

## Cross-pool: USDC/WETH 0.01% against USDC/WETH 0.05%

Combined fee: 6 bps. `lo` is USDC/WETH 0.01%, `hi` is USDC/WETH 0.05%.

### USDC/WETH: 01_cross_pool_gap.sql

Read 2,576,810 rows (115,541,274 bytes) in 235 ms, 211,471,754 bytes of memory.

| moved | swaps | abs_gap_p50_bps | abs_gap_p95_bps | abs_gap_p99_bps | abs_gap_max_bps | mean_signed_gap_bps | beyond_combined_fee |
|---|---|---|---|---|---|---|---|
| hi | 307,171 | 3.00 | 7.14 | 16.93 | 14,355.46 | 0.273635 | 23,249 |
| lo | 926,413 | 2.79 | 6.10 | 11.15 | 16,029.47 | 0.211993 | 49,579 |
|  | 1,233,584 | 2.85 | 6.30 | 12.64 | 16,029.47 | 0.227343 | 72,828 |

### USDC/WETH: 02_cross_pool_gap_histogram.sql

Read 2,576,810 rows (115,541,274 bytes) in 159 ms, 113,639,937 bytes of memory.

| bucket_bps | swaps |
|---|---|
| 0 | 209,281 |
| 1 | 213,653 |
| 2 | 231,092 |
| 3 | 296,840 |
| 4 | 156,257 |
| 5 | 53,633 |
| 6 | 27,150 |
| 7 | 13,093 |
| 8 | 7,886 |
| 9 | 5,138 |
| 10 | 3,570 |
| 11 | 2,447 |
| 12 | 1,763 |
| 13 | 1,378 |
| 14 | 1,051 |
| 15 | 809 |
| 16 | 639 |
| 17 | 567 |
| 18 | 424 |
| 19 | 392 |
| 20 | 6,521 |

### USDC/WETH: 03_cross_pool_episodes.sql

Read 2,576,810 rows (156,287,424 bytes) in 428 ms, 267,948,337 bytes of memory.

| episodes | still_open_at_the_end | closed_in_the_same_block | closed_one_block_later | closed_two_or_more_blocks_later | blocks_open_p50 | blocks_open_p90 | blocks_open_p99 | blocks_open_max | opened_by_lo | opened_by_hi | closed_by_lo | closed_by_hi | closed_by_the_other_pool | closed_by_the_same_pool | opened_by_lo_closed_by_hi | opened_by_hi_closed_by_lo | never_left_one_transaction | peak_gap_p50_bps | peak_gap_p99_bps |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 29,474 | 0 | 23,829 | 5,008 | 637 | 0 | 1 | 2 | 6 | 22,652 | 6,822 | 21,437 | 8,037 | 12,529 | 16,945 | 6,872 | 5,657 | 3,874 | 8.01 | 187.03 |

### USDC/WETH: 04_cross_pool_block_ends.sql

Read 2,576,810 rows (115,541,274 bytes) in 186 ms, 147,234,198 bytes of memory.

| blocks | blocks_ending_within_the_fee | share_within_the_fee | end_gap_p50_bps | end_gap_p99_bps |
|---|---|---|---|---|
| 290,270 | 284,248 | 0.979254 | 2.68 | 6.78 |

### USDC/WETH: what the primary key kept, per scan of 01_cross_pool_gap.sql

| table | condition | kept | total |
|---|---|---|---|
| onchain.raw_swaps | (pool_address in ['0xe0554a476a092703abdb3ef35c80e0d76d32939f', '0xe0554a476a092703abdb3ef35c80e0d76d32939f']) | 117 | 153 |
| onchain.raw_swaps | (pool_address in ['0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640', '0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640']) | 42 | 153 |
| onchain.raw_swaps | (pool_address in ['0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640', '0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640']) | 42 | 153 |
| onchain.raw_swaps | (pool_address in ['0xe0554a476a092703abdb3ef35c80e0d76d32939f', '0xe0554a476a092703abdb3ef35c80e0d76d32939f']) | 117 | 153 |

### USDC/WETH: 01_cross_pool_gap.sql under each join algorithm

| join_algorithm | runs | median_ms | median_memory_bytes | read_rows | same_answer_as_hash |
|---|---|---|---|---|---|
| hash | 3 | 234 | 211,356,810 | 2,576,810 | 1 |
| full_sorting_merge | 3 | 625 | 188,424,974 | 2,576,810 | 1 |

## Cross-pool: wstETH/USDC 0.05% against wstETH/USDC 0.3%

Combined fee: 35 bps. `lo` is wstETH/USDC 0.05%, `hi` is wstETH/USDC 0.3%.

### wstETH/USDC: 01_cross_pool_gap.sql

Read 191,148 rows (4,953,540 bytes) in 16 ms, 6,598,551 bytes of memory.

| moved | swaps | abs_gap_p50_bps | abs_gap_p95_bps | abs_gap_p99_bps | abs_gap_max_bps | mean_signed_gap_bps | beyond_combined_fee |
|---|---|---|---|---|---|---|---|
| hi | 931 | 20.52 | 177.40 | 3,157.66 | 1,082,968.48 | -3,492.83 | 220 |
| lo | 6,026 | 29.04 | 378.56 | 1,082,649.37 | 1,083,042.88 | -34,484.79 | 2,526 |
|  | 6,957 | 27.28 | 340.76 | 1,082,639.79 | 1,083,042.88 | -30,337.38 | 2,746 |

### wstETH/USDC: 02_cross_pool_gap_histogram.sql

Read 191,148 rows (4,953,540 bytes) in 17 ms, 7,393,052 bytes of memory.

| bucket_bps | swaps |
|---|---|
| 0 | 151 |
| 1 | 135 |
| 2 | 133 |
| 3 | 136 |
| 4 | 131 |
| 5 | 153 |
| 6 | 134 |
| 7 | 146 |
| 8 | 123 |
| 9 | 117 |
| 10 | 91 |
| 11 | 122 |
| 12 | 104 |
| 13 | 128 |
| 14 | 114 |
| 15 | 124 |
| 16 | 124 |
| 17 | 135 |
| 18 | 121 |
| 19 | 150 |
| 20 | 4,385 |

### wstETH/USDC: 03_cross_pool_episodes.sql

Read 191,148 rows (6,684,580 bytes) in 41 ms, 9,570,223 bytes of memory.

| episodes | still_open_at_the_end | closed_in_the_same_block | closed_one_block_later | closed_two_or_more_blocks_later | blocks_open_p50 | blocks_open_p90 | blocks_open_p99 | blocks_open_max | opened_by_lo | opened_by_hi | closed_by_lo | closed_by_hi | closed_by_the_other_pool | closed_by_the_same_pool | opened_by_lo_closed_by_hi | opened_by_hi_closed_by_lo | never_left_one_transaction | peak_gap_p50_bps | peak_gap_p99_bps |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 606 | 0 | 106 | 24 | 476 | 38 | 429 | 1,360 | 11,043 | 554 | 52 | 435 | 171 | 181 | 425 | 150 | 31 | 30 | 63.93 | 6,971.46 |

### wstETH/USDC: 04_cross_pool_block_ends.sql

Read 191,148 rows (4,953,540 bytes) in 16 ms, 6,311,944 bytes of memory.

| blocks | blocks_ending_within_the_fee | share_within_the_fee | end_gap_p50_bps | end_gap_p99_bps |
|---|---|---|---|---|
| 5,820 | 3,687 | 0.633505 | 25.67 | 1,082,640.11 |

### wstETH/USDC: what the primary key kept, per scan of 01_cross_pool_gap.sql

| table | condition | kept | total |
|---|---|---|---|
| onchain.raw_swaps | (pool_address in ['0x4622df6fb2d9bee0dcdacf545acdb6a2b2f4f863', '0x4622df6fb2d9bee0dcdacf545acdb6a2b2f4f863']) | 6 | 153 |
| onchain.raw_swaps | (pool_address in ['0x173821f6ad4c5324cd35753a9fd12d92f2eaab29', '0x173821f6ad4c5324cd35753a9fd12d92f2eaab29']) | 6 | 153 |
| onchain.raw_swaps | (pool_address in ['0x173821f6ad4c5324cd35753a9fd12d92f2eaab29', '0x173821f6ad4c5324cd35753a9fd12d92f2eaab29']) | 6 | 153 |
| onchain.raw_swaps | (pool_address in ['0x4622df6fb2d9bee0dcdacf545acdb6a2b2f4f863', '0x4622df6fb2d9bee0dcdacf545acdb6a2b2f4f863']) | 6 | 153 |

### wstETH/USDC: 01_cross_pool_gap.sql under each join algorithm

| join_algorithm | runs | median_ms | median_memory_bytes | read_rows | same_answer_as_hash |
|---|---|---|---|---|---|
| hash | 3 | 14 | 6,344,670 | 191,148 | 1 |
| full_sorting_merge | 3 | 18 | 6,268,489 | 191,148 | 1 |
