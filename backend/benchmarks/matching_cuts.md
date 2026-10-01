# Matching-cut validation

The item-only slot mutex rows can reject legal attachments that have several
physical destinations. A Glock FD917 suppressor and Baldr Pro light, for example,
can coexist when the light occupies the suppressor's own rail. The old root-slot
row incorrectly required their combined selection to be at most one.

Keep item selection integral, validate each integer solution with physical
matching, and add an upper or lower Hall inequality when matching fails. Only
export connected, parent-first slot assignments. M4A1 retains 450 item binaries
and one continuous ergonomics column, without placement columns. Refinements
share the request deadline; reaching a refinement limit reports a timeout.

Repeated TED-floor recoil solves reuse learned structural rows within their
prepared request. Bind rows to the weapon, column order, physical slots, blockers
and item conflicts. Do not share objectives, stat bounds or TED tangent cuts.

## Frozen M4A1 comparison

Python 3.12.14, NumPy 2.3.5, SciPy 1.18.1 and SQLAlchemy 2.0.52; M855-loaded
magazines of at least 60 rounds, full market availability. Snapshot SHA256:
`2cdd4ebe5adc88c66d4f3b98aa5e8cb08598ed4ca020f4e834a1f08473b51dff`.
One warmup and three alternating, sequential measurements per case, with the
existing 30-second Explore budget. These are Explore requests, not single-solve
latencies. A complete request finishes planned samples, not every Pareto solution.

The baseline below is the **uncached matching model**, not upstream's incorrect
slot model. Correcting the feasible domain has a cost, so these figures do not
claim that every path is faster than the original optimizer.

| Explore case | Uncached matching median | Cached matching median | Native solves |
|---|---:|---:|---:|
| Ergonomics/recoil, 10 steps | 4.35 s | 4.43 s | 20 / 20 |
| Ergonomics/recoil, 40 steps | 11.23 s | 11.33 s | 43 / 43 |
| Ergonomics/recoil, 81 steps | 21.84 s | 21.55 s | 78 / 78 |
| TED/recoil, 10 steps | 10.94 s | 7.42 s | 91 / 51 |
| Ergonomics/price, 10 steps | 2.29 s | 2.33 s | 15 / 15 |
| Recoil/price, 10 steps | 2.97 s | 2.90 s | 16 / 16 |

The TED case took 32.2% less time. Other differences are within the measured
variation. All 18 measured curve pairs retained equal ergonomics, recoil
modifiers, displayed TED and prices.

## Correctness and integration

- On the synchronized fork: 242 backend fixture tests passed, 52 skipped;
  23 selected M4A1 tests passed separately against the read-only game snapshot.
- The frozen matching/cache A/B covered 25 constraint cases: 22 complete and
  three expected infeasible in each variant. All returned builds passed physical
  placement, exported statistics, price and hard-limit checks.
- Exhaustive checks covered 48 six-item DAGs and all 3,072 selection subsets.
  All 460 legal subsets survived 53 learned cuts. Reloading the cuts rechecked
  all 3,072 subsets with the same independent physical-matching results.
- The exact six-part Glock build recovers ergonomics 96.5, weight 1.310 kg and
  vertical/horizontal recoil 234/195. The old capacity row rejects it; the
  matching model accepts it. The visible-filter curve can improve ergonomics
  to 98.5 by adding a rear sight while retaining vertical recoil 234.

The synchronized upstream optimizer and statistics sources match the benchmark
base byte for byte. The candidate's nine changed Python modules likewise match
the frozen tested candidate; the newer catalog backend tests were rerun too.
Black and flake8 pass. No frontend was launched or checked.

## Remaining limits

Matching preserves the existing one-selection-per-item-ID semantics and expects
an acyclic candidate graph. This study covers M4A1 and the Glock regression, not
all weapons or online concurrency percentiles.

The existing global TED tangent approximation is unchanged. Tangents of the
convex allowable-weight curve can exclude valid builds away from their anchor,
so changing the solve path can change the returned nonlinear frontier. Two
overswing-enabled constraint cases differed. One captured valid build had TED
39.22 above its 36.292 floor but violated a tangent at ergonomics 35.0 by about
0.00397 kg. All 330 final-cache-row checks retained the reference valid builds,
isolating this rejection to the stat approximation rather than structural cuts.
Therefore native optimal status is not a global nonlinear optimality proof, and
the measured speedup is not a promise of unchanged results for every TED setup.
