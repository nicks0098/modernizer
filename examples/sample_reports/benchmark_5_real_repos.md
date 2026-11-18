# Benchmark results

5 of 5 projects ended with a passing build (tests counted only if they were run).

| repo | language | files | changed | auto_rewrites | needs_review | compile_before | compile_after | tests_before | tests_after | repair_rounds | seconds | error |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| douban-client | python | 42 | 18 | 18 | 0 | fail | pass | skipped | skipped | 0 | 1.42 |  |
| milk | python | 108 | 44 | 44 | 0 | fail | pass | skipped | skipped | 0 | 3.71 |  |
| Nscan | python | 30 | 18 | 22 | 4 | fail | pass | skipped | skipped | 0 | 1.3 |  |
| salmon | python | 43 | 9 | 9 | 2 | fail | pass | skipped | skipped | 0 | 0.79 |  |
| taskmaster | python | 20 | 9 | 9 | 7 | fail | pass | skipped | skipped | 0 | 0.46 |  |
