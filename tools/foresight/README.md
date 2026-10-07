# Foresight — measuring predictive expert prefetch

Can experts be brought into VRAM **before** a verify window asks for them, instead of the CPU computing the misses?
This folder holds the tools behind the numbers in the upstream discussion (2× RTX 3090, UD-Q4_K_XL, layer split).
Nothing changes the engine unless you set the switches below, and with them unset the build gave answers identical to
its base (6/6 on the deterministic gate).

**Status (2026-10-07): built, correct, and NOT faster on our box.** The swap space (below) removes 21-39 % of the CPU
misses, exactly as the trace simulation predicted, but decode comes out −1…−5 %. See [Results](#results) for why, and
what a version that wins would need.

## Engine switches (this branch, all off by default)

| switch | what it does |
|---|---|
| `STRATA_FORESIGHT_DUMP=path` | every serve-path pool call appends one record: `int32 layer, int32 n_tok, n_tok×10 int32 ids, n_tok×n_embd BF16` = the layer's normed MoE input (the router's own input). ~0.36 MB per written token. `STRATA_FORESIGHT_DUMP_GB` caps the size (default 40). |
| `STRATA_FS_SLOTS=N` | **the swap space**: N VRAM slots per layer on each card, apart from the expert cache, refilled on their own copy stream with experts that just missed. When the pool would give an expert to the CPU and a landed slot holds it, the expert becomes a plain GPU group pointing at the slot (no kernel changes; the host decides and the GPU follows the plan). A slot is reused only after `STRATA_FS_DEPTH` (default 4) more windows have finished since a plan last pointed at it. `STRATA_FS_BUDGET` = copies per card per window (default 32), `STRATA_FS_ADMIT` = misses within 4 windows before an expert is copied (default 1), `STRATA_FS_VERIFY=1` = test mode that reads every landed slot back and compares it byte for byte. Needs VRAM headroom: raise `--vram-reserve-mib` by about slots × 24 layers × the blob size (~1.3 GB per card at 16 slots on UD-Q4_K_XL). Off beside `STRATA_VERIFY_DEVICE_PLAN`. |
| `STRATA_FORESIGHT_RING=N` | the recency ring on the **existing adapt path**: N slots per layer follow recently-missed experts (`_BUDGET` copies per card and round, `_GAMMA` decay). Needs the adaptive tier, best with `--adapt-every 1`. **Measured: no gain** (the adapt path lands copies ~4 windows late). Kept as a reference, not a feature. |

`--dump-routing path` (upstream) gives the routing-only trace that `sim.py` replays.

## Tools (Python 3 + numpy; `scout_trial.py` also needs MLX)

1. `extract_routers.py <model-00001-of-N.gguf>` → `data/router-gate-inp.bin` (pure Python, no numpy needed).
2. `sim.py` — replays a `--dump-routing` trace through a mimic of the engine cache (static profile fill + adapt
   rules). Set `S0`/`S1` to your per-stage slot counts. On our trace it matched the engine's hit rate (~94 %), and it
   also showed no change from `--adapt-every` / `--adapt-swaps`, as the live engine does. It scores the recency ring
   (`PERLAYER=1`, `DELAY=` windows until a copy lands).
3. `stream_eval.py <dump | host:/path>` — streams a `STRATA_FORESIGHT_DUMP` file (60 GB in ~15 min) and stores, per
   token-row, the top-48 experts that layers L+1..L+3's routers pick from layer L's input (router-ahead, zero-shot),
   plus a 10 % raw sample.
4. `eval_gate.py` — token recall of router-ahead, and how many cache misses it covers in time under a per-layer
   bus budget.
5. `scout_trial.py` — a small trained residual predictor (MLX). On our data it did not transfer across sessions.

## What would help

- The same measurements on other setups: a single 24 GB card, a 32 GB card, AMD, other quants. That means the price of
  a miss (shrink `--vram-reserve-mib` with `STRATA_DECODE_TIMING=1`), the hit rate, and `eval_gate.py` coverage.
- Ideas for the hard part: a low-latency prefetch path where the host plan (`host_res`) and the GPU plan (`d_res`) see
  residency changes identically within a window.

## Results

Measured on one box: 2× RTX 3090 (x8 Gen4 each), Ryzen 9 3950X, UD-Q4_K_XL, v0.1.40.1, `--layer-split 24
--pipeline-windows 2 --pcie-frac 0.2 --spec-min-p 0.7`. Four prompts (two short ones, ~50K context, 1,500-token code)
× 3 reps, one restart per setting, `STRATA_DECODE_TIMING=1`.

**Correctness:** switches off = 6/6 identical answers on the deterministic gate. Swap space on with
`STRATA_FS_VERIFY=1`: 19,633 slot read-backs, 0 mismatches. Answers change wording (an expert computed on the GPU
instead of the CPU rounds differently) and stay coherent.

| setting | geo-mean t/s | CPU misses per layer-window | ms per window |
|---|---|---|---|
| off (two passes) | 98.6 / 98.0 | 0.842 / 0.841 | 15.41 / 15.31 |
| 16 slots (two passes) | 96.4 / 95.0 | 0.643 / 0.664 | 15.95 / 16.07 |
| 8 / 24 / 32 slots | 95.3 / 93.7 / 94.1 | 0.660 / 0.670 / 0.615 | 15.89 / 15.88 / 15.75 |
| 16 slots, budget 16 / 64 | 96.7 / 95.3 | 0.755 / **0.515** | 16.10 / 15.64 |
| 16 slots, admit after 2 misses | 97.8 | 0.861 | 15.94 |

Misses fall as predicted, but no setting beats off. The window breakdown shows why:

1. **At under one miss per layer-window, the cost is per layer, not per expert.** A layer that sends even one expert to
   the CPU waits for the CPU round trip. Removing some of a layer's misses but not all saves little: CPU-expert time
   per window fell only 2.90 → 2.27-2.78 ms. Our earlier "price per miss" (+2.78 ms per extra miss per layer-window,
   which gave the "+34 % headroom" in the issue) came from shrinking the cache to 1-3.5 misses per layer-window, and it
   does not extrapolate down to the live operating point.
2. **The copies slow the GPU side.** The refill stream (about 160K copies of ~3 MB per sweep step) shares the x8 links
   with the per-layer CPU↔GPU handshake and KV streaming. GPU-side time per window rose 10.3 → 10.6-10.8 ms. The slots
   also cost the expert cache 7-13 % of its slots.

**What a version that wins would likely need:** clearing *every* miss of a layer (so its CPU round trip disappears),
and copies scheduled into bus-idle time (e.g. the other card's link while one card computes its half of a layer
split) instead of competing with the handshake. Boxes with more misses per layer (smaller VRAM, single 24 GB cards)
sit where the per-miss price did hold in our cache-shrink test, so the picture may be better there. That is untested.
