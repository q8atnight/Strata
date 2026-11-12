# UI screenshots on Qwen3.8-Flash-Next (Strata): picture-token cap and mmproj F16 / Q8_0 / Q6_K / Q4_0

Write-up: see the linked Strata issue (body = `post2/ISSUE-body.md`). Five arms: F16 @6144, F16 @2048, Q8_0, Q6_K, Q4_0 (@6144).
- `images/` — the 25 test pictures (7 real screenshots with fictional demo data, 18 synthetic), `big5k.png` (largest-picture speed probe), `overview-r2.png`
- `questions-v2.json` — questions + reference answers · `results-r2-<arm>.json` — raw answers incl. reasoning · `speed-r2-<arm>.json`
- `scores-v2-real.json` (hand grading) · `score2-synth.json` (auto grading of the `ANSWER:` lines, `score2.py`)
- `make_probes_r2.py` draws the 18 synthetic probes · `run.py`, `speed.py` (env `STRATA_URL`, `STRATA_KEY`, `STRATA_LOG`) · `probe.sh` reader-alone VRAM/speed
- `post2/ANSWERS-r2.md` — every answer of every arm side by side
