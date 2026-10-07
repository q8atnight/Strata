#!/usr/bin/env python3
"""Score gate-ahead (Fate-style) prediction on the hidden-state dump (outputs of stream_eval.py).

(1) token-level recall: of the 10 experts layer L+k really used, how many are in W_{L+k}.x_L's top-M.
(2) miss coverage in time: the engine-mimic cache of sim.py replays the dump's routing; for every window and target
    layer t, the candidates are the best-ranked NOT-resident experts predicted from earlier layers of the SAME window
    (lead k = 1..3 layers, union over the window's tokens, rank = best rank over tokens); a budget per target layer
    reflects how many ~3 MB blobs one x8 link moves in k layers (~0.32 ms per layer, ~0.23 ms per blob).
    Covered misses are counted as saved for that window only (pure prefetch, nothing kept).
Usage: python3 eval_gate.py"""
import os, sys, json, struct
import numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from sim import initial_residency, read_profile, SPLIT, NE, ADAPT_EVERY, ADAPT_SWAPS, COPY_DELAY, UMIN, GAIN, DECAY

meta = np.fromfile("data/ev_meta.bin", dtype=np.dtype([("l", "<i4"), ("t", "<i4"), ("r", "<i8")]))
ids = np.fromfile("data/ev_ids.bin", dtype="<i2").reshape(-1, 10).astype(np.int32)
pred = np.memmap("data/ev_pred.bin", dtype="<i2", mode="r").reshape(-1, 3, 48)
pairs, freq = read_profile("data/expert-profile.bin")
print(f"records {len(meta):,} rows {len(ids):,}", flush=True)

def stage_windows(st):
    lo = st * SPLIT
    m = np.flatnonzero((meta["l"] >= lo) & (meta["l"] < lo + SPLIT))
    L = meta["l"][m]
    cut = np.flatnonzero(np.r_[True, np.diff(L) < 0])
    wins = []
    for a, b in zip(cut, np.r_[cut[1:], len(m)]):
        byl = {}
        for j in m[a:b]:
            r0, T = meta["r"][j], meta["t"][j]
            byl.setdefault(int(meta["l"][j]) - lo, []).append(np.arange(r0, r0 + T))
        wins.append({l: np.concatenate(v) for l, v in byl.items()})
    return wins

# (1) token-level recall@M
rec = {k: {M: [0, 0] for M in (10, 16, 24, 32, 48)} for k in (1, 2, 3)}
SCHEMES = {  # name: {lead k: how many candidates from that lead}; per target layer
    "k1 m1": {1: 1}, "k1 m2": {1: 2}, "k2 m2": {2: 2}, "k2 m3": {2: 3}, "k3 m4": {3: 4},
    "k1..3 m2+1+1": {3: 2, 2: 1, 1: 1}, "k1..3 m3+2+1": {3: 3, 2: 2, 1: 1}, "k1..3 m4+2+2": {3: 4, 2: 2, 1: 2},
}
out = {"recall": {}, "cover": {}}
for st in (0, 1):
    wins = stage_windows(st)
    half = len(wins) // 2
    # cache replay (sim.py rules) with all schemes evaluated side by side on the same cache state
    res = initial_residency(st, pairs, freq)
    usage = np.zeros(SPLIT * NE, np.float32); pending = []
    tot = {s: [0, 0, 0] for s in SCHEMES}  # misses, covered, issued
    base_miss = 0; nwin = 0
    for w, win in enumerate(wins):
        need = {l: np.unique(ids[r]) for l, r in win.items()}
        if w >= half:
            nwin += 1
            sample = (w % 10 == 0)
            for l, r in win.items():
                miss = need[l][~res[l * NE + need[l]]]
                base_miss += len(miss)
                cand = {}
                for k in (1, 2, 3):
                    if l - k not in win or len(win[l - k]) != len(r): continue
                    P = pred[win[l - k], k - 1]                     # (T, 48) ranked per token
                    if sample:
                        A = ids[r]
                        for M in rec[k]:
                            rec[k][M][0] += int((P[:, :M, None] == A[:, None, :]).any(1).sum()); rec[k][M][1] += A.size
                    if not len(miss): continue
                    flat = P.T.ravel()                               # rank-major: best rank over tokens first
                    flat = flat[flat >= 0].astype(np.int32)
                    u, first = np.unique(flat, return_index=True)
                    order = u[np.argsort(first)]
                    cand[k] = order[~res[l * NE + order]][:8]        # best-ranked experts not in VRAM
                if not len(miss): continue
                ms = set(miss.tolist())
                for s_, plan in SCHEMES.items():
                    chosen = set()
                    for k in sorted(plan, reverse=True):              # earliest lead first, later leads add new ones
                        if k in cand:
                            add = [e for e in cand[k].tolist() if e not in chosen][:plan[k]]
                            chosen.update(add)
                    tot[s_][0] += len(miss); tot[s_][1] += len(ms & chosen); tot[s_][2] += len(chosen)
        # engine adapt (same rules as sim.py)
        for l, r in win.items():
            np.add.at(usage, l * NE + ids[r].ravel(), 1)
        if pending and pending[0][0] <= w:
            for _, fi in [p for p in pending if p[0] <= w]: res[fi] = True
            pending = [p for p in pending if p[0] > w]
        if w % ADAPT_EVERY == ADAPT_EVERY - 1 and not pending:
            U = usage.reshape(SPLIT, NE); R = res.reshape(SPLIT, NE); sw = []
            for l in range(SPLIT):
                ci = np.flatnonzero(~R[l] & (U[l] >= UMIN))
                if not len(ci): continue
                c = ci[np.argsort(-U[l][ci])]; v = np.flatnonzero(R[l]); v = v[np.argsort(U[l][v])][:len(c)]
                for x, y in zip(c, v):
                    if U[l][x] < U[l][y] + GAIN: break
                    sw.append((U[l][x] - U[l][y], l * NE + x, l * NE + y))
            sw.sort(reverse=True)
            for g, fin, fout in sw[:ADAPT_SWAPS]:
                res[fout] = False; pending.append((w + COPY_DELAY, fin))
            usage *= DECAY
    out["cover"][st] = {"windows": nwin, "base_miss_per_lw": base_miss / (nwin * SPLIT),
                        **{s: {"miss": v[0], "covered": v[1], "issued": v[2], "cover": v[1] / max(1, v[0]),
                               "issued_per_lw": v[2] / (nwin * SPLIT)} for s, v in tot.items()}}
    print(st, json.dumps(out["cover"][st], indent=0)[:2000], flush=True)
out["recall"] = {k: {M: v[0] / max(1, v[1]) for M, v in d.items()} for k, d in rec.items()}
print("token recall", json.dumps(out["recall"]))
json.dump(out, open("eval_gate.json", "w"), indent=1)
