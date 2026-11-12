# Pumpfun Top-5 Forecast — v2

Forecast of the 5 largest pump.fun coins by market cap at each of 7 answer
reads (competition `pumpfun-top5-forecast-01`, make.fun). Deterministic,
Python 3 stdlib only. Reads `/input` (or `$MAKEFUN_INPUT_DIR`), writes
`/output/forecast.json` (or `$MAKEFUN_OUTPUT_DIR`).

## What changed vs v3

v3 (`~/workspace/makefun/builds/pumpfun-top5/main.py`) scored **-39.1** on the
dev/practice leaderboard (order -23.74, size -15.31, agreement 56, rank ~265
of ~370). It was only backtested on a single 10-minute horizon. Its
per-read log score degraded catastrophically with horizon: ~-15 at h=0,
~-25 at h=10, ~-36 at h=20, ~-55 at h=30, ~-70 at h=40. Two causes:

1. **It had no newborn model.** A newborn coin (born after the cut) wins
   50% of top-5 places at 10 minutes, 67% at 20, 80% at 30-40 minutes in
   the kit history (U(h) ~= h/(h+10)). v3's newborns were drawn from the
   young-coin population at the cut (median ~1.45 dex, the dead level), so
   they almost never won and its unnamed mass stayed 0.09-0.30 while the
   truth was 0.5-0.8.
2. **Its survival model was backwards.** It decayed pool coins and let
   young curve coins linger. In the data, a coin already at ~3.0 dex and
   not falling fast keeps growing (Claude: 3.04 -> 3.28 dex over 40 min),
   while a young coin below ~3.0 dex collapses to ~1.45 dex within 10-30
   minutes (GhgwUe3M 2.12 -> 1.45, 87H1NAWE 1.98 -> 1.45, 6LDCNqzJ
   1.97 -> 1.45) and does NOT rally. Survival is decided by level and
   trajectory, not venue alone.

## The v2 model

Per-coin Monte Carlo (8,000 scenarios, fixed seed 20261112), then the
grader's exact order/size distributions are built from the simulated
ranks and caps.

* **Three incumbent regimes, decided by level and trajectory.** A coin
  already at ~3.0 dex and not falling faster than -0.15 dex per 10 minutes
  is a WINNER: death hazard 0.06 per 10 minutes, cap grows toward a
  rally ceiling of 3.75 dex with a 1-hour time constant (a straight
  +0.45 dex/h extrapolation would put incumbents at 4.0+ dex and let them
  swallow every place; the ceiling keeps them honest). A YOUNG coin (age
  under 15 min, or seen at <= 2 marks) below ~3.0 dex is a death trap:
  hazard 0.95 (curve) / 0.85 (pool) per 10 minutes, and a survivor just
  decays slowly toward the dead level (the rallies belong to the future
  cohorts, not to young incumbents). An established non-winner decays
  slowly (hazard 0.25 curve / 0.12 pool). Dead coins (died in the
  simulation, or a coin whose last mark is missing) collapse to ~1.45 dex.
* **Ghost newborns.** The chart is completed by coins that have not been
  born yet: `2 + one per 10-minute cohort since the cut`, capped at 8,
  each with a cap ~N(3.25, 0.18) dex (the tight distribution of newborn
  winner caps in the kit: place 1 ~3.45, place 5 ~3.1 dex, median ~3.25).
  They are unnamed, so their mass is the model's unnamed share.
* **Smoothing.** Every place keeps a 0.02 floor for each named coin and a
  0.05 size prior (SD 0.40 dex); the per-place probabilities are capped so
  the total named mass is <= 1 (per the grader's rule that a row naming a
  mint the history never named is dropped).

## Evaluation (local, same scorer as the grader)

Multi-read evaluator replicating the grader exactly (mean over reads of
order + size log score), built from the kit's history at several cut marks
(`~/workspace/makefun/builds/pumpfun-top5-work/v2/eval.py`). The true dev
reads (21:00-22:00 UTC) are not in the kit, so these splits are the
analogue; the dev has a richer 1-hour history but reads out to ~70 min,
so the split scores bracket it.

| Split | v3 | v2 | change |
|---|---|---|---|
| D1 cut 20:20, reads 20:20-20:50 | -44.40 | -32.67 | +11.73 |
| D2 cut 20:30, reads 20:30-20:50 | -26.41 | -22.90 | +3.51 |
| D3 cut 20:10, reads 20:10-20:50 | -53.42 | -34.70 | +18.72 |
| S1 cut 20:40 -> 20:50 (10 min) | -23.73 | -18.96 | +4.77 |
| S2 cut 20:30 -> 20:40 (10 min) | -24.71 | -22.55 | +2.16 |
| L1 cut 20:20 -> 20:50 (30 min) | -54.54 | -32.21 | +22.33 |
| L2 cut 20:10 -> 20:50 (40 min) | -69.93 | -31.00 | +38.93 |
| L3 cut 20:10 -> 20:40 (30 min) | -68.68 | -30.73 | +37.95 |

Estimated dev/practice log score: **about -31 to -33**, vs v3's -39.1 and
the leaderboard leader's -32.1 (top 5: -32.1 to -33.2). The estimate is
uncertain because the dev reads run to ~70 minutes and the kit history only
covers 50 minutes of usable marks; the per-read score plateaus near -31 to
-33 at 30-40 minutes in the splits, so the dev mean should land in that
range.

## I/O contract

Input: `task.json` (`reads`, `places`, `chart_size`, `size.edges`, `marks`)
and `history.ndjson` in the input directory. Output: `forecast.json` with
exactly the keys `probabilities`, `sizes`, `top5`. Each place's
probabilities sum to <= 1; at most 100 rows per place; the size bins use the
task's edges. Output is byte-identical across repeated runs (fixed seed,
no wall-clock or randomness from the environment). Runtime ~7 s per
instance on this machine (limit 300 s).

## Verification

* **Determinism:** two runs on the kit's input are byte-identical
  (`forecast.json`, 17,327 bytes); runtime ~7 s per instance (limit 300 s).
* **`makefun check` (kit CLI, 2026-11-12 12:42 WIB): 11 passed, 0 failed,**
  5 skipped, 5 checked at submission. All transcript-gate checks pass
  (thinking_reproduces 52.2% vs 30% required, thinking_turns 103 vs 5,
  thinking_revised: main.py takes its final content from 11 write/edit
  messages vs 2). The 5 "at submission" items (repo public, repo owner,
  repo created after the opening, commit pushed, no duplicate snapshot)
  are the parent's step: create the GitHub repo with `makefun init`
  (drand anchor) and submit before 21:00 WIB.
* **Transcript bundle:** `pumpfun-top5-v2-transcripts.tar.gz`, 536,398
  bytes, sha256
  `efe0a246c9eab22fb213f751ecb79c9c5fcabea89aaf1071413aee6b18fe4dfb`
  (3 sessions: the parent agent, this v2 build session, and one more
  subagent). Rebuild it after the repo is created if the parent prefers a
  bundle anchored to the real repository; the sessions are discoverable by
  the kit CLI from this build directory.
* **Official dev score:** not measurable locally — `makefun grade-local`
  refuses program/v1 kits ("its scorer and reference data are not
  published in the kit, so it is graded on the server only"). The numbers
  above are the local split estimates. The server will grade the submitted
  entry on the real 21:00-22:00 UTC answers.

## Files

* `main.py` — the forecast program.
* `README.md` — this file.
* `LICENSE` — MIT.
* `.makefun/owner.json` — entry owner wallet.
