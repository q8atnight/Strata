"""Auto-score the synthetic probes of round 2 from their final 'ANSWER:' line. usage: python3 score2.py label [label...]"""
import json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
Q = json.load(open(f"{HERE}/questions-v2.json"))

def norm(s): return re.sub(r"[^a-z0-9=\- ]", " ", s.lower()).split()

def ok(name, ans, truth):
    a = " ".join(norm(ans)); t = " ".join(norm(truth))
    if name.startswith("d01"):
        got = dict(re.findall(r"([a-e])\s*=\s*(thin|medium|thick)", a)); want = dict(re.findall(r"([a-e])=(thin|medium|thick)", t))
        return sum(got.get(k) == v for k, v in want.items()) / len(want)       # partial credit per row
    if name.startswith("d09"):
        return float(re.findall(r"\d+", a)[:2] == re.findall(r"\d+", t)[:2])
    if name.startswith(("s02", "h02")):
        return float(t.replace(" ", "") in a.replace(" ", "") or "-".join(reversed(t.split("-"))) in a.replace(" ", ""))
    return float(all(w in a.split() for w in t.split()))

labels = sys.argv[1:]
rows = {}
for lab in labels:
    R = json.load(open(f"{HERE}/results-{lab}.json"))
    for n, spec in Q.items():
        if n.startswith("r"): continue
        r = R.get(f"{n}::facts", {}); txt = r.get("answer") or ""
        m = re.findall(r"ANSWER:\s*(.+)", txt)
        rows.setdefault(n, {})[lab] = (round(ok(n, m[-1], spec["truth"][0]), 2) if m else 0.0, m[-1].strip() if m else "(no ANSWER line)")
print("probe".ljust(30), "truth".ljust(36), *[l.ljust(26) for l in labels])
tot = {l: [0, 0, 0, 0] for l in labels}   # light got, light n, dark got, dark n
for n, d in rows.items():
    print(n[:29].ljust(30), Q[n]["truth"][0][:35].ljust(36), *[f"{d[l][0]:<4} {d[l][1][:20]}".ljust(26) for l in labels])
    for l in labels:
        i = 2 if n[0] in "de" else 0; tot[l][i] += d[l][0]; tot[l][i + 1] += 1
print()
for l in labels: print(f"{l}: light {tot[l][0]:g}/{tot[l][1]}  dark {tot[l][2]:g}/{tot[l][3]}")
json.dump({l: {n: rows[n][l] for n in rows} for l in labels}, open(f"{HERE}/score2-synth.json", "w"), indent=1)
