#!/usr/bin/env python3
"""Stream the Foresight hidden-state dump from the PC and score gate-ahead prediction (Fate-style, zero-shot).

Dump record = int32 layer, int32 n_tok, n_tok*10 int32 ids, n_tok*2560 BF16 (layer's normed MoE input = its router
input).  Router weights: data/router-gate-inp.bin = 48 x (512 x 2560) float32 (GGUF ffn_gate_inp, row = expert).
Batched: records are read in chunks; per layer, all rows go through W_L (self-check) and W_{L+1..L+3} (top-48 kept,
rank order) as one BLAS matmul.  Every SAMPLE_EVERY-th block of BLOCK records is also kept raw (Scout training).
Outputs (data/): ev_meta.bin (int32 layer, int32 ntok, int64 row offset), ev_ids.bin (rows x 10 int16),
ev_pred.bin (rows x 3 x 48 int16), scout-sample.bin (raw records)."""
import subprocess, struct, time
import numpy as np

import sys
SRC = sys.argv[1] if len(sys.argv) > 1 else "dump-live.bin"   # a local path, or host:/path (streamed over ssh)
E, NE, K, KA, TOP = 2560, 512, 10, 3, 48
BLOCK, SAMPLE_EVERY, CHUNK = 30000, 10, 20000

W = np.fromfile("data/router-gate-inp.bin", dtype=np.float32).reshape(48, NE, E)
WT = [np.ascontiguousarray(W[l].T) for l in range(48)]            # (2560, 512)
if ":" in SRC and not SRC.startswith("/"):
    host, path = SRC.split(":", 1)
    f = subprocess.Popen(["ssh", host, f"cat {path}"], stdout=subprocess.PIPE, bufsize=1 << 24).stdout
else:
    f = open(SRC, "rb", buffering=1 << 24)
fm, fi, fp = open("data/ev_meta.bin", "wb"), open("data/ev_ids.bin", "wb"), open("data/ev_pred.bin", "wb")
scout = open("data/scout-sample.bin", "wb")
n = rows = 0; selfok = selftot = 0; t0 = time.time(); nbytes = 0; eof = False

def topk_ranked(lg, m):
    top = np.argpartition(-lg, m, axis=1)[:, :m]
    order = np.argsort(-np.take_along_axis(lg, top, 1), axis=1)
    return np.take_along_axis(top, order, 1)

while not eof:
    Ls, Ts, IDs, Xs = [], [], [], []
    for _ in range(CHUNK):
        h = f.read(8)
        if len(h) < 8: eof = True; break
        L, T = struct.unpack("<ii", h)
        assert 0 <= L < 48 and 1 <= T <= 16, (n, L, T)
        ib = f.read(40 * T); xb = f.read(2 * E * T)
        if len(xb) < 2 * E * T: eof = True; break
        nbytes += 8 + len(ib) + len(xb)
        if (n // BLOCK) % SAMPLE_EVERY == 0:
            scout.write(h); scout.write(ib); scout.write(xb)
        Ls.append(L); Ts.append(T); IDs.append(ib); Xs.append(xb); n += 1
    if not Ls: break
    Ts_a = np.array(Ts); Ls_a = np.array(Ls)
    ids = np.frombuffer(b"".join(IDs), dtype="<i4").reshape(-1, K)
    x = (np.frombuffer(b"".join(Xs), dtype="<u2").astype(np.uint32) << 16).view(np.float32).reshape(-1, E)
    rowL = np.repeat(Ls_a, Ts_a)
    pr = np.full((len(x), KA, TOP), -1, np.int16)
    for l in np.unique(rowL):
        sel = np.flatnonzero(rowL == l); X = x[sel]
        own = np.argpartition(-(X @ WT[l]), K, axis=1)[:, :K]
        selfok += int((own[:, :, None] == ids[sel][:, None, :]).any(2).sum()); selftot += own.size
        for k in range(1, KA + 1):
            if l + k < 48:
                pr[sel, k - 1] = topk_ranked(X @ WT[l + k], TOP)
    offs = rows + np.r_[0, np.cumsum(Ts_a)[:-1]]
    fm.write(np.rec.fromarrays([Ls_a.astype("<i4"), Ts_a.astype("<i4"), offs.astype("<i8")]).tobytes())
    fi.write(ids.astype(np.int16).tobytes()); fp.write(pr.tobytes())
    rows += len(x)
    el = time.time() - t0
    print(f"{n:,} records {nbytes/1e9:.1f} GB {nbytes/1e6/el:.0f} MB/s self-match {selfok/max(1,selftot):.4f}", flush=True)
for h in (fm, fi, fp, scout): h.close()
print(f"done {n:,} records, {rows:,} rows, {nbytes/1e9:.1f} GB, self-match {selfok/selftot:.4f}, {time.time()-t0:.0f}s")
