# Evidence

Created by `topology/topo.py` during scripted runs. Expected contents after the
VM run:

| File | Produced by |
|---|---|
| `dumpflows_basic_before.txt`, `dumpflows_basic_after.txt` | `--test basic` |
| `dumpflows_basic_autoblock.txt` | `--test basic` malformed flood |
| `basic_flood.txt` | `--test basic` flood helper summary |
| `dumpflows_multi_before.txt`, `dumpflows_multi_after.txt` | `--test multi` |
| `multi_baseline.txt`, `multi_block_files.txt`, `multi_block_client.txt` | `--test multi` |
| `dumpflows_hard_before.txt`, `dumpflows_hard_after.txt` | `--hard` |
| `hard_bypass.txt`, `hard_flood.txt`, `hard_policy_change.txt` | `--hard` |
| `dumpflows_hard_flood.txt` | `--hard` automatic block |
| `hard_stats_before_crash.txt` | `--hard` proxy crash |
| `proxy_basic.log`, `proxy_multi.log`, `proxy_hard.log` | structured proxy logs copied after each scenario |

Keep the files; the report should cite the timestamps and flow rules inside
them. Do not edit them after the run.
