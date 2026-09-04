# Solver baselines

`solver_baseline.py` measures both solvers from a cold result cache against two
fixed, real-data cases:

- M4A1: dense/deep optimizer stress case; the Stock combo slot exercises a
  bounded but branching Combo Calculator path.
- PPSh-41: shallow, low-branching fast-path contrast case.

Sync `tarkov.db` first, then run from `backend/` with the normal development
environment variables set:

```bash
python benchmarks/solver_baseline.py --runs 3
```

The JSON output records compatibility-graph shape, candidate/frontier/model
sizes, truncation state, solver termination, and min/median/max wall time. The
case guards fail loudly if later game-data updates make either weapon stop
representing its intended end of the range, including M4A1 multi-parent/depth
density and the PPSh-41 shallow, single-parent fast path.
