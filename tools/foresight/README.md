# Foresight — measuring predictive expert prefetch

Can experts be brought into VRAM **before** a verify window asks for them, instead of the CPU computing the misses?
This folder holds the tools behind the numbers in the upstream discussion (2× RTX 3090, UD-Q4_K_XL, layer split).
Everything here is measurement. Nothing changes the engine unless you set the switches below, and with them unset the
build gave answers identical to its base (6/6 on the deterministic gate).

## Engine switches (this branch, all off by default)

| switch | what it does |
|---|---|
| `STRATA_FORESIGHT_DUMP=path` | every serve-path pool call appends one record: `int32 layer, int32 n_tok, n_tok×10 int32 ids, n_tok×n_embd BF16` = the layer's normed MoE input (the router's own input). ~0.36 MB per written token. `STRATA_FORESIGHT_DUMP_GB` caps the size (default 40). |
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
