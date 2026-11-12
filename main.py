# pumpfun-top5-forecast-01 entry v2: forecast the 5 largest pump.fun coins
# by market cap at each answer read.
#
# What the data (the kit's 5 usable marks, 20:10-20:50 on 2026-11-11) shows,
# and what v3 got wrong:
#   * Winners in the cut's top-100 are ALWAYS in the cut's TOP 5, and always
#     pool coins. Deep history coins never win a top-5 place. Young curve
#     coins in the cut's top 5 almost always collapse to ~1.45 dex (the dead
#     level) within 10-30 minutes; pool coins persist and GROW about
#     +0.3-0.6 dex/hour while young.  v3 decayed pool coins and let curve
#     coins linger, exactly backwards.
#   * The share of top-5 places won by coins born AFTER the cut grows with
#     the horizon: 50% at 10 min, 67% at 20, 80% at 30-40.  A newborn that
#     wins a place has a cap near 3.1-3.6 dex (median ~3.25), about one strong
#     newborn per 10-minute cohort.  v3 drew newborn caps from the young-coin
#     population at the cut (median ~1.45 dex), so its newborns almost never
#     won and its unnamed mass stayed near 0.1-0.3 while the truth was 0.5-0.8.
#     The score for a newborn winner is ln(unnamed_mass / ~95), so the
#     unnamed mass IS the long-horizon score.
#   * Per read the forecast is the mean over the reads, so each read is
#     modelled at its own horizon (the Monte Carlo runs per read).
#
# Model (standard library only, fully deterministic):
#   * Incumbents (history coins) fall in three regimes, decided by level
#     and trajectory, not by venue alone: a coin already at ~3.0 dex and
#     not falling fast is a WINNER (low death hazard, keeps growing
#     ~+0.45 dex/h); a YOUNG coin (age < 15 min or seen at <= 2 marks)
#     below ~3.0 dex almost always collapses to ~1.45 dex within 10-30
#     minutes and does NOT rally -- the rallies belong to the future
#     cohorts, i.e. the ghost newborns; an established non-winner decays
#     slowly.  v3 decayed pool coins and let young curve coins linger,
#     exactly backwards.
#   * Newborns: strong ghost newborns, 2 + one per 10-minute cohort since
#     the cut (capped at 8, none at the cut itself), each cap ~
#     Normal(3.25, 0.18) dex.  They compete in the same Monte Carlo, so the
#     newborn win share, the place displacement and the size distribution
#     all emerge from one simulation.  Newborns are not named, so a newborn
#     win scores the place's unnamed mass, exactly as the grader scores it.
#   * A read's place probabilities are the Monte Carlo frequencies,
#     Laplace-smoothed 2% over the named coins; sizes are the Monte Carlo
#     per-place cap histogram mixed with a 5% broad normal prior so no bin is
#     ever empty.  The single forecast is the mean over the reads of the
#     per-read distributions.
#
# Determinism: one fixed seed (20261112), candidates iterated in sorted mint
# order, no set iteration, no wall clock, no network, no randomness outside
# the seeded generator.  Two runs on the same history write byte-identical
# output.

import json
import math
import os
import random
import sys
from datetime import datetime, timezone

SEED = 20261112
SCENARIOS = 8000
SMOOTH_PLACE = 0.02       # Laplace share spread over the named coins
SMOOTH_SIZE_PRIOR = 0.05  # weight of the broad normal mixed into sizes
SIZE_PRIOR_SD = 0.40      # sd (dex) of the broad normal mixed into sizes
MAX_CANDIDATES = 60
MAX_ROWS_PER_PLACE = 100
DEAD_CAP = 1.45           # log10 SOL cap of a dead curve coin
DEAD_SD = 0.08

POOL_VOL_HOURLY_CAP = 0.35
CURVE_DECAY = 0.08        # dex per hour an established non-winner falls
GROWTH_CEIL = 3.75        # dex: the level a rallying winner saturates at.
                          # The top caps in the kit reach 3.56 dex and are
                          # still rising ~+0.06 dex per 10 minutes; a
                          # straight +0.45 dex/h extrapolation would put the
                          # incumbents at 4.0+ dex an hour out and let them
                          # swallow every place, so the growth saturates
                          # toward this ceiling with a 1-hour time constant.
SIGMA0 = 0.05             # base sd (dex) at the cut
SIGMA_CAP = 0.45          # cap on total sd (dex) at any horizon

NEWBORN_MU = 3.25         # log10 SOL cap of a strong newborn
NEWBORN_SD = 0.18


def parse_time(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def floor6(x):
    """Round down to 6 decimals (never -0), like the house starter."""
    r = math.floor(x * 1_000_000) / 1_000_000
    return 0.0 if r == 0 else r


def normal_cdf(x, mu, sd):
    if sd <= 0:
        return 1.0 if x >= mu else 0.0
    return 0.5 * (1.0 + math.erf((x - mu) / (sd * math.sqrt(2.0))))


def bin_of(value, edges):
    lo, hi = 0, len(edges)
    while lo < hi:
        mid = (lo + hi) // 2
        if edges[mid] <= value:
            lo = mid + 1
        else:
            hi = mid
    return lo


def main():
    in_dir = os.environ.get("MAKEFUN_INPUT_DIR", "/input")
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")

    with open(os.path.join(in_dir, "task.json"), "r", encoding="utf-8") as f:
        task = json.load(f)
    places = int(task["places"])
    edges = [float(e) for e in task["size"]["edges"]]
    out_name = task.get("output", "forecast.json")
    n_bins = len(edges) + 1

    marks = []
    with open(os.path.join(in_dir, "history.ndjson"), "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            m = json.loads(line)
            if m.get("ok") is True and isinstance(m.get("rows"), list):
                marks.append(m)
    if not marks:
        raise ValueError("the history holds no ok mark")

    mark_times = [parse_time(m["at"]) for m in marks]
    cut_time = mark_times[-1]
    read_times = [parse_time(r) for r in task.get("reads", []) or []]
    if not read_times:
        read_times = [datetime.fromtimestamp(cut_time.timestamp() + 3600.0 * h, tz=timezone.utc)
                      for h in range(1, 8)]
    horizons = [(rt - cut_time).total_seconds() / 3600.0 for rt in read_times]
    horizons = [h if h > 0 else 0.0 for h in horizons]

    # ---- per-coin series from the marks -----------------------------------
    # mint -> {times (hours since first mark), logcaps, venue, complete, created}
    series = {}
    for mi, m in enumerate(marks):
        t_h = (mark_times[mi] - mark_times[0]).total_seconds() / 3600.0
        for row in m["rows"]:
            mint = row["mint"]
            cap_lamports = int(row["market_cap_lamports"])
            if cap_lamports <= 0:
                continue
            x = math.log10(cap_lamports) - 9.0  # log10 of the cap in SOL
            e = series.get(mint)
            if e is None:
                e = {"t": [], "x": [], "venue": row.get("venue", "curve"),
                     "complete": bool(row.get("complete", False)),
                     "created": row.get("created_at")}
                series[mint] = e
            e["t"].append(t_h)
            e["x"].append(x)
            e["venue"] = row.get("venue", e["venue"])
            e["complete"] = bool(row.get("complete", e["complete"]))

    last_rows = marks[-1]["rows"]
    last_by_mint = {}
    for row in last_rows:
        cap_lamports = int(row["market_cap_lamports"])
        if cap_lamports > 0:
            last_by_mint[row["mint"]] = math.log10(cap_lamports) - 9.0

    # ---- candidate selection -------------------------------------------------
    # Winners are always in the cut's top 5 (pool) or newborns, so the
    # relevant incumbents are the cut's largest coins.  Keep the top 60 by
    # relevance (current cap + momentum) plus the last mark's top 20.
    def momentum(e):
        if len(e["x"]) < 2:
            return 0.0
        return e["x"][-1] - e["x"][0]

    scored = []
    for mint, e in series.items():
        x = e["x"][-1]
        scored.append((x + 0.35 * momentum(e), mint))
    scored.sort(key=lambda kv: (-kv[0], kv[1]))
    cand_mints = [mint for _, mint in scored[:MAX_CANDIDATES]]
    top20 = sorted(last_by_mint.items(), key=lambda kv: (-kv[1], kv[0]))[:20]
    for mint, _ in top20:
        if mint not in cand_mints:
            cand_mints.append(mint)
    cand_mints.sort()

    # ---- per-coin model parameters -------------------------------------------
    # The kit's marks show survival is decided by level and trajectory, not
    # by venue alone: a coin already at ~3.0 dex (and not falling fast) is a
    # WINNER that persists and keeps growing (Claude, AJqKjfP4, 7fNYfFkD,
    # BuaseKYxF); a YOUNG coin (age < 15 min or seen at <= 2 marks) below
    # ~3.0 dex almost always collapses to ~1.45 dex within 10-30 minutes
    # (ApjmiTid, 6mpMPt5G, 632ZCbqv, 6Q4iiHgc all did, pool or curve alike)
    # and does NOT rally -- the rallies belong to the future cohorts, i.e.
    # the ghost newborns, not to the young incumbents.  An established
    # non-winner decays slowly.  A dead coin sits at ~1.45 dex, the level
    # the collapsed coins reach.
    coins = []
    for mint in cand_mints:
        e = series[mint]
        xs = e["x"]
        ts = e["t"]
        x = xs[-1]
        venue = e["venue"]
        if e["created"]:
            age_min = (cut_time - parse_time(e["created"])).total_seconds() / 60.0
        else:
            age_min = 999.0
        # OLS slope of log-cap on time (dex per hour), and per 10 minutes
        n = len(xs)
        if n >= 2:
            mt = sum(ts) / n
            mx = sum(xs) / n
            num = sum((t - mt) * (xv - mx) for t, xv in zip(ts, xs))
            den = sum((t - mt) ** 2 for t in ts)
            slope_h = num / den if den > 0 else 0.0
        else:
            slope_h = 0.0
        slope_10 = slope_h / 6.0
        diffs = [xs[i + 1] - xs[i] for i in range(len(xs) - 1)]
        if diffs:
            mean_d = sum(diffs) / len(diffs)
            var = sum((d - mean_d) ** 2 for d in diffs) / len(diffs)
            vol10 = math.sqrt(var)
        else:
            vol10 = 0.12
        vol_hourly = min(POOL_VOL_HOURLY_CAP, max(0.10, vol10 * math.sqrt(6.0)))
        # Level is the primary signal: a coin already at ~3.0 dex is a
        # winner unless it is falling fast (BuaseKYxF dipped -0.14 dex in
        # 10 minutes and still held a top-5 place; ApjmiTid at 2.92 dex
        # collapsed).  A coin below 3.0 dex that is young or barely seen
        # is unproven and usually dies.
        is_winner = (x >= 3.0 and slope_10 > -0.15) or (n >= 3 and slope_10 > 0.008)
        if is_winner:
            hazard = 0.06
            coins.append({"mint": mint, "regime": "winner", "x": x,
                          "hazard": hazard, "vol_hourly": vol_hourly})
        elif age_min < 15.0 or n <= 2:
            hazard = 0.95 if venue == "curve" else 0.85
            if e["complete"]:
                hazard *= 0.8
            coins.append({"mint": mint, "regime": "young", "x": x,
                          "hazard": hazard, "vol_hourly": vol_hourly})
        else:
            hazard = 0.25 if venue == "curve" else 0.12
            coins.append({"mint": mint, "regime": "other", "x": x,
                          "hazard": hazard, "vol_hourly": vol_hourly})

    # ---- Monte Carlo over the reads ------------------------------------------
    rng = random.Random(SEED)
    n_cand = len(coins)
    n_reads = len(horizons)
    place_counts = []
    size_counts = []
    for ri, h in enumerate(horizons):
        h_min = h * 60.0
        # Strong newborns: one per 10-minute cohort since the cut, plus the
        # cohorts just before it (a coin born up to ~20 minutes before the
        # read is still young and strong), capped at 8.  A read at the cut
        # has none.  The newborn win share this produces (about 0.5 at
        # 10 min, 0.67 at 20, 0.8 at 30-40) matches the history; the old
        # "one newborn per cohort since the cut" gave only ~0.1-0.3.
        n_newborn = 0 if h_min < 5 else min(8, 2 + int(h_min // 10))
        pc = [dict() for _ in range(places)]
        sc = [[0] * n_bins for _ in range(places)]
        # per-coin forecast at this horizon
        mus = []
        sds = []
        dead_p = []
        for c in coins:
            steps = h * 6.0  # 10-minute steps
            p_dead = 1.0 - (1.0 - c["hazard"]) ** steps if steps > 0 else 0.0
            if c["regime"] == "winner":
                # saturating growth toward the rally ceiling (see
                # GROWTH_CEIL): fast while far below it, flat once there.
                mu = GROWTH_CEIL - (GROWTH_CEIL - c["x"]) * math.exp(-h / 1.0)
                sd = math.sqrt(SIGMA0 * SIGMA0 + (c["vol_hourly"] ** 2) * h)
            else:  # young or other: no rally, slow decay if it survives
                mu = c["x"] - CURVE_DECAY * h
                sd = math.sqrt(SIGMA0 * SIGMA0 + (c["vol_hourly"] ** 2) * h)
            mus.append(mu)
            sds.append(min(SIGMA_CAP, sd))
            dead_p.append(p_dead)
        for _s in range(SCENARIOS):
            caps = []
            for i in range(n_cand):
                if dead_p[i] > 0.0 and rng.random() < dead_p[i]:
                    caps.append((rng.gauss(DEAD_CAP, DEAD_SD), i))
                else:
                    caps.append((rng.gauss(mus[i], sds[i]), i))
            # newborn contenders (unnamed): strong newborns of the cohorts
            # since the cut
            for _n in range(n_newborn):
                caps.append((rng.gauss(NEWBORN_MU, NEWBORN_SD), -1))
            caps.sort(key=lambda kv: -kv[0])
            for placed in range(places):
                cap_val, i = caps[placed]
                if i >= 0:
                    pc[placed][coins[i]["mint"]] = pc[placed].get(coins[i]["mint"], 0) + 1
                b = bin_of(cap_val, edges)
                sc[placed][b] += 1
        place_counts.append(pc)
        size_counts.append(sc)

    # ---- average over reads, build the forecast ------------------------------
    probabilities = []
    sizes = []
    top5 = []
    for k in range(places):
        freq = {}
        for r in range(n_reads):
            for mint, cnt in place_counts[r][k].items():
                freq[mint] = freq.get(mint, 0.0) + cnt / (SCENARIOS * n_reads)
        order = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))
        named = [mint for mint, _ in order[:MAX_ROWS_PER_PLACE]]
        n_named = len(named)
        for mint in named:
            p = (1.0 - SMOOTH_PLACE) * freq.get(mint, 0.0) + SMOOTH_PLACE / n_named if n_named else 0.0
            p = floor6(p)
            if p > 0:
                probabilities.append({"mint": mint, "place": k + 1, "p": p})
        for mint, _ in order:
            if mint not in top5:
                top5.append(mint)
                break
        # sizes: mean MC histogram, mixed with a broad normal prior.
        tot = [0.0] * n_bins
        for r in range(n_reads):
            for b in range(n_bins):
                tot[b] += size_counts[r][k][b] / (SCENARIOS * n_reads)
        num = 0.0
        den = 0.0
        for b in range(n_bins):
            lo = -10.0 if b == 0 else edges[b - 1]
            hi = 10.0 if b == n_bins - 1 else edges[b]
            centre = (lo + hi) / 2.0
            num += tot[b] * centre
            den += tot[b]
        mu_size = num / den if den > 0 else 0.0
        for b in range(n_bins):
            lo = -float("inf") if b == 0 else edges[b - 1]
            hi = float("inf") if b == n_bins - 1 else edges[b]
            prior = normal_cdf(hi, mu_size, SIZE_PRIOR_SD) - normal_cdf(lo, mu_size, SIZE_PRIOR_SD)
            p = (1.0 - SMOOTH_SIZE_PRIOR) * tot[b] + SMOOTH_SIZE_PRIOR * prior
            p = floor6(p)
            if p > 0:
                sizes.append({"place": k + 1, "bin": b, "p": p})
    if len(top5) < places:
        for mint in cand_mints:
            if mint not in top5:
                top5.append(mint)
            if len(top5) == places:
                break

    probabilities.sort(key=lambda r: (r["place"], -r["p"], r["mint"]))
    sizes.sort(key=lambda r: (r["place"], r["bin"]))
    doc = {"probabilities": probabilities, "top5": top5[:places], "sizes": sizes}
    text = json.dumps(doc, sort_keys=True) + "\n"
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, out_name), "w", encoding="utf-8") as f:
        f.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
