#!/usr/bin/env python3
"""Foresight offline study (2026-10-07): replay a Strata --dump-routing log (Q4 layer split, serve path) through a
simulated expert cache that mimics the live engine (static profile fill + adapt every 4 windows, usage>=2,
gain>1.5, <=96 swaps, x0.7 decay, swaps land after a copy delay), then score prefetch predictors that feed a
small VRAM staging area under a bus budget.

Record = int32 layer, int32 k(=10), 10 int32 ids, 10 float weights (88 B). Stage A = layers 0-23 (CUDA0),
stage B = 24-47; the two stages' records interleave in time, so each stage stream is cut into windows on its own
(a window = a run of non-decreasing layer indices; stage A also logs cancelled pipelined windows - real loads).

Usage: python3 sim.py data/full.bin data/expert-profile.bin [skip_records]"""
import sys, time, struct, json, os
import numpy as np

NL, NE, K = 48, 512, 10
SPLIT = 24
SLOTS = {0: int(os.environ.get("S0", 6587)), 1: int(os.environ.get("S1", 6192))}   # per-stage slots: set to YOUR engine's (see /metrics)          # live engine: expert_slots_primary 6587, total 12779
import os
UMIN, GAIN, DECAY = float(os.environ.get('UMIN', 2)), float(os.environ.get('GAIN', 1.5)), float(os.environ.get('DECAY', .7))
ADAPT_EVERY, ADAPT_SWAPS, COPY_DELAY = int(os.environ.get("AE", 4)), int(os.environ.get("AS", 48)), 2   # 96 swaps shared by the two stages -> 48 each (approx)

def load(path, skip):
    dt = np.dtype([("l", "<i4"), ("k", "<i4"), ("ids", "<i4", (K,)), ("w", "<f4", (K,))])
    a = np.fromfile(path, dtype=dt)[skip:]
    assert (a["k"] == K).all()
    return a["l"].astype(np.int16), a["ids"].astype(np.int16)

def windows_of(lay, ids, stage):
    lo = stage * SPLIT
    m = (lay >= lo) & (lay < lo + SPLIT)
    L = (lay[m] - lo).astype(np.int64); I = ids[m].astype(np.int64)
    starts = np.flatnonzero(np.r_[True, np.diff(L) < 0])
    ends = np.r_[starts[1:], len(L)]
    flat = (L[:, None] * NE + I).astype(np.int32)    # (rows, 10) flat index into (24*512)
    return flat, starts, ends

def read_profile(path):
    b = open(path, "rb").read()
    assert b[:4] == b"STRP"
    ver, nl, ne, want, n = struct.unpack_from("<5I", b, 4)
    pairs = np.frombuffer(b, dtype="<u2", count=2 * n, offset=24).reshape(n, 2).astype(np.int64)
    freq = np.frombuffer(b, dtype="<f4", count=nl * ne, offset=24 + 4 * n) if len(b) >= 24 + 4 * n + 4 * nl * ne else None
    return pairs, freq

def initial_residency(stage, pairs, freq, carve=0):
    lo = stage * SPLIT
    res = np.zeros(SPLIT * NE, bool)
    sel = pairs[(pairs[:, 0] >= lo) & (pairs[:, 0] < lo + SPLIT)]
    take = sel[: SLOTS[stage]]
    res[(take[:, 0] - lo) * NE + take[:, 1]] = True
    left = SLOTS[stage] - int(res.sum())
    if left > 0:                                   # fill the rest by frequency (or spread) like the engine's tail fill
        if freq is not None:
            f = freq.reshape(NL, NE)[lo:lo + SPLIT].ravel().copy()
        else:
            f = np.zeros(SPLIT * NE)
        f[res] = -1
        res[np.argsort(-f, kind="stable")[:left]] = True
    if carve and freq is not None:                 # staging slots come out of the cache: drop the coldest residents
        f = freq.reshape(NL, NE)[lo:lo + SPLIT].ravel()
        idx = np.flatnonzero(res)
        res[idx[np.argsort(f[idx])[:carve]]] = False
    return res

class Sim:
    """One stage. pf: None or dict(policy params). Returns per-window distinct misses (measured half)."""
    def __init__(self, stage, flat, starts, ends, res0, staging=0, budget=0, gamma=0.5, cooc=None, k_ahead=2,
                 m_ahead=0, mode="recent"):
        self.__dict__.update(locals())

    def run(self, measure_from):
        flat, starts, ends = self.flat, self.starts, self.ends
        S = SPLIT * NE
        res = self.res0.copy()
        usage = np.zeros(S, np.float32)
        heat = np.zeros(S, np.float32)
        staged = np.zeros(S, bool); stage_t = np.zeros(S, np.int64)   # last-use stamp for LRU
        self.ready = np.zeros(S, np.int64); D = int(os.environ.get('DELAY', 1))
        self.D = D
        pending = []                               # (land_window, flat_in)
        out_miss, out_saved, out_need, out_rows, out_issued = 0, 0, 0, 0, 0
        ent_tot, ent_miss = 0, 0
        n_meas = 0
        cooc = self.cooc
        for w in range(len(starts)):
            a, b = starts[w], ends[w]
            rows = flat[a:b]
            cnt = np.bincount(rows.ravel(), minlength=S)
            need = cnt > 0
            # P2 cross-layer: within this window, from layer l's picks predict layer l+k (same window)
            if self.m_ahead and cooc is not None:
                lays = np.unique(rows[:, 0] // NE)
                avail = ~res & ~staged
                for l in lays:
                    t = l + self.k_ahead
                    if t >= SPLIT: continue
                    picks = np.flatnonzero(need[l * NE:(l + 1) * NE])
                    sc = cooc[l][picks].sum(0)          # (512,)
                    sc[~avail[t * NE:(t + 1) * NE]] = -1
                    top = np.argpartition(-sc, self.m_ahead)[: self.m_ahead]
                    top = top[sc[top] > 0]
                    self._stage_in(staged, stage_t, t * NE + top, w)
                    out_issued += len(top) if w >= measure_from else 0
            hit_res = need & res
            usable = staged & (self.ready <= w)
            hit_stg = need & ~res & usable
            miss = need & ~res & ~usable
            if w >= measure_from:
                out_need += int(need.sum()); out_miss += int(miss.sum()); out_saved += int(hit_stg.sum())
                out_rows += b - a; n_meas += 1
                ent_tot += int(cnt.sum()); ent_miss += int(cnt[miss].sum())
            stage_t[hit_stg] = w
            # engine adapt (usage counts routed entries)
            usage += cnt
            if pending and pending[0][0] <= w:
                land = [p for p in pending if p[0] <= w]; pending = [p for p in pending if p[0] > w]
                for _, fi in land: res[fi] = True; staged[fi] = False
            if w % ADAPT_EVERY == ADAPT_EVERY - 1 and not pending:
                self._adapt(res, usage, pending, w, staged)
                usage *= DECAY
            # P1: recent-heat prefetch for the next window
            if self.budget:
                heat *= self.gamma; heat += cnt
                sc = np.where(~res & ~staged & ~need, heat, 0.0) if self.mode == "recent_excl" else np.where(~res & ~staged, heat, 0.0)
                nb = self.budget - (self.m_ahead * SPLIT if self.m_ahead else 0)
                if nb > 0:
                    cand = np.flatnonzero(sc > 0)
                    if len(cand):
                        top = cand[np.argsort(-sc[cand])[:nb]]
                        self._stage_in(staged, stage_t, top, w)
                        out_issued += len(top) if w >= measure_from else 0
        return dict(entry_hit=1 - ent_miss / max(1, ent_tot), windows=n_meas, rows=out_rows, need=out_need, miss=out_miss, saved=out_saved, issued=out_issued)

    def _stage_in(self, staged, stage_t, fis, w):
        if not self.staging or len(fis) == 0: return
        fis = fis[~staged[fis]]
        if os.environ.get("PERLAYER"):             # ring split per layer (slot sizes differ per layer)
            cap = self.staging // SPLIT
            for fi in fis:
                l = fi // NE
                seg = staged[l * NE:(l + 1) * NE]
                if seg.sum() >= cap:
                    cur = np.flatnonzero(seg) + l * NE
                    ev = cur[np.argmin(stage_t[cur])]
                    if stage_t[ev] >= w: continue    # everything in this layer's ring was used this window
                    staged[ev] = False
                staged[fi] = True; stage_t[fi] = w; self.ready[fi] = w + self.D
            return
        free = self.staging - int(staged.sum())
        over = len(fis) - free
        if over > 0:                               # evict LRU staged entries
            cur = np.flatnonzero(staged)
            ev = cur[np.argsort(stage_t[cur])[:over]]
            staged[ev] = False
        staged[fis[: self.staging]] = True; stage_t[fis[: self.staging]] = w

    def _adapt(self, res, usage, pending, w, staged):
        swaps = []
        U = usage.reshape(SPLIT, NE); R = res.reshape(SPLIT, NE)
        for l in range(SPLIT):
            u, r = U[l], R[l]
            ci = np.flatnonzero(~r & (u >= UMIN))
            if not len(ci): continue
            vi = np.flatnonzero(r)
            c = ci[np.argsort(-u[ci])]; v = vi[np.argsort(u[vi])][: len(c)]
            for x, y in zip(c, v):
                if u[x] < u[y] + GAIN: break
                swaps.append((u[x] - u[y], l * NE + x, l * NE + y))
        swaps.sort(reverse=True)
        for g, fin, fout in swaps[:ADAPT_SWAPS]:
            res[fout] = False
            pending.append((w + COPY_DELAY, fin))

def cooc_table(flat, starts, ends, upto, k):
    """P(e' at l+k | e at l) from co-occurrence in the same window, windows [0, upto)."""
    C = np.zeros((SPLIT, NE, NE), np.float32); n = np.zeros((SPLIT, NE), np.float32)
    for w in range(upto):
        rows = flat[starts[w]:ends[w]]
        need = np.zeros(SPLIT * NE, bool); need[rows.ravel()] = True
        N = need.reshape(SPLIT, NE)
        for l in range(SPLIT - k):
            a = np.flatnonzero(N[l]); bb = np.flatnonzero(N[l + k])
            if len(a) and len(bb):
                C[l][np.ix_(a, bb)] += 1
            n[l][a] += 1
    return C / np.maximum(n[:, :, None], 1)

if __name__ == "__main__":
    path, prof = sys.argv[1], sys.argv[2]
    skip = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    t0 = time.time()
    lay, ids = load(path, skip)
    pairs, freq = read_profile(prof)
    print(f"records {len(lay):,}  profile pairs {len(pairs):,}  load {time.time()-t0:.1f}s", flush=True)
    for st in (0, 1):
        flat, s, e = windows_of(lay, ids, st)
        print(f"stage {st}: windows {len(s):,}  rows/window {(e-s).mean()/SPLIT:.2f}", flush=True)
