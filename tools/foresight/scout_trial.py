#!/usr/bin/env python3
"""Scout feasibility (MLX, Mac): a tiny per-layer predictor of layer L+1's experts from layer L's router input.

logits = W_{L+1} x (frozen zero-shot gate-ahead) + B(A x) + b   (A: 2560->R, B: R->512; ~R*3k params per layer)
Data: data/scout-sample.bin (10 % of the dump in contiguous blocks), windows cut per stage as in eval_gate.py,
pairs (x_L rows, ids_{L+1} rows) of the same window.  Split by time: first 80 % train, last 20 % test.
Metrics on test: token recall@M of all 10 experts, and recall of the experts NOT in the static profile cache (the
ones that become misses) when only the best m not-cached experts are fetched (m = 1, 2, 4)."""
import struct, sys, time
import numpy as np
import mlx.core as mx, mlx.nn as nn, mlx.optimizers as optim
sys.path.insert(0, "."); from sim import initial_residency, read_profile, SPLIT

E, NE, K = 2560, 512, 10
LAYERS = [int(a) for a in (sys.argv[1].split(",") if len(sys.argv) > 1 else "3,10,18,27,35,42".split(","))]
import os
R, EPOCHS = int(os.environ.get("R", 64)), int(os.environ.get("EP", 6))
LR = float(os.environ.get("LR", 1e-3))
W = np.fromfile("data/router-gate-inp.bin", dtype=np.float32).reshape(48, NE, E)
pairs, freq = read_profile("data/expert-profile.bin")
cached = np.concatenate([initial_residency(0, pairs, freq), initial_residency(1, pairs, freq)]).reshape(48, NE)

# parse the sample into windows per stage: {stage: [ {layer: (x rows, id rows)} ]}
f = open("data/scout-sample.bin", "rb"); recs = []
while True:
    h = f.read(8)
    if len(h) < 8: break
    L, T = struct.unpack("<ii", h)
    ids = np.frombuffer(f.read(40 * T), "<i4").reshape(T, K)
    xb = f.read(2 * E * T)
    recs.append((L, T, ids, xb))
print("records", len(recs), flush=True)
data = {L: ([], []) for L in LAYERS}
for st in (0, 1):
    lo = st * SPLIT; cur = {}; prev = -1
    def flush():
        for L in LAYERS:
            if L in cur and L + 1 in cur:
                (xa, ia), (xb_, ib) = cur[L], cur[L + 1]
                xs = b"".join(xa); A = np.concatenate(ia); B = np.concatenate(ib)
                if len(A) == len(B):
                    data[L][0].append(xs); data[L][1].append(B)
    for L, T, ids, xb in recs:
        if not (lo <= L < lo + SPLIT): continue
        if L < prev: flush(); cur = {}
        prev = L
        if L in LAYERS or L - 1 in LAYERS:
            c = cur.setdefault(L, ([], [])); c[0].append(xb); c[1].append(ids)
    flush()

def bf(xs): return (np.frombuffer(xs, "<u2").astype(np.uint32) << 16).view(np.float32).reshape(-1, E)

class Scout(nn.Module):
    def __init__(self, W0):
        super().__init__()
        self.W0 = mx.array(W0.T)          # frozen gate-ahead (2560, 512)
        self.A = nn.Linear(E, R, bias=False); self.B = nn.Linear(R, NE, bias=False)
        self.B.weight = mx.zeros_like(self.B.weight)   # start exactly at the zero-shot predictor
    def __call__(self, x): return x @ mx.stop_gradient(self.W0) + self.B(self.A(x))

def metrics(scores, Y, L1):
    out = {}
    top = np.argsort(-scores, 1)
    for M in (10, 16, 24):
        out[f"r@{M}"] = float((top[:, :M, None] == Y[:, None, :]).any(1).mean())
    nc = ~cached[L1]                                     # experts outside the profile cache
    s2 = np.where(nc[None, :], scores, -np.inf); top2 = np.argsort(-s2, 1)
    tgt = [set(y[nc[y]]) for y in Y]
    n_t = sum(len(t) for t in tgt)
    for m in (1, 2, 4):
        hit = sum(len(t & set(top2[i, :m])) for i, t in enumerate(tgt))
        out[f"miss@{m}"] = hit / max(1, n_t)
    out["miss_targets_per_tok"] = n_t / len(Y)
    return out

res = {}
for L in LAYERS:
    X = bf(b"".join(data[L][0])); Y = np.concatenate(data[L][1]).astype(np.int64)
    n = len(X); cut = int(n * 0.8)
    Xtr, Ytr, Xte, Yte = X[:cut], Y[:cut], X[cut:], Y[cut:]
    T = np.zeros((len(Ytr), NE), np.float32); np.put_along_axis(T, Ytr, 1.0, 1)
    model = Scout(W[L + 1]); opt = optim.AdamW(learning_rate=LR, weight_decay=float(os.environ.get("WD", 0.01)))
    def loss_fn(m, x, t):
        if os.environ.get("LOSS", "ce") == "bce": return nn.losses.binary_cross_entropy(m(x), t, with_logits=True, reduction="mean")
        lp = m(x) - mx.logsumexp(m(x), axis=1, keepdims=True)      # listwise: the router's own softmax
        return -(lp * t).sum(1).mean() / K
    lg = nn.value_and_grad(model, loss_fn)
    t0 = time.time(); xt, tt = mx.array(Xtr), mx.array(T)
    for ep in range(EPOCHS):
        perm = np.random.permutation(len(Xtr))
        for i in range(0, len(perm), 512):
            b = mx.array(perm[i:i + 512]); l, g = lg(model, xt[b], tt[b]); opt.update(model, g); mx.eval(model.parameters(), opt.state)
    zs = Xte @ W[L + 1].T
    sc = np.array(model(mx.array(Xte)))
    res[L] = {"n_train": cut, "n_test": n - cut, "zero_shot": metrics(zs, Yte, L + 1), "scout": metrics(sc, Yte, L + 1),
              "params": E * R + R * NE + NE, "train_s": round(time.time() - t0, 1)}
    print(L, res[L], flush=True)
import json; json.dump(res, open(os.environ.get("OUT", "scout_trial.json"), "w"), indent=1)
