"""Send every probe image to the live Strata engine and save the answers.
usage: STRATA_KEY=... python3 run.py <label>     (label = q8 or f16)"""
import base64, json, os, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
URL = os.environ.get("STRATA_URL", "http://127.0.0.1:8080") + "/v1/chat/completions"
MODEL = os.environ.get("STRATA_MODEL", "qwen3.8-flash-next-iq3_s-dual")
KEY = os.environ["STRATA_KEY"]
label = sys.argv[1]
only = sys.argv[2:]  # optional subset of image names
Q = json.load(open(os.path.join(HERE, os.environ.get("QFILE", "questions.json"))))
DO_CRIT = os.environ.get("CRIT", "1") == "1"
CRIT = ("You are a meticulous UI reviewer. List the concrete layout and visual problems you can see in this screenshot "
        "(alignment, spacing, symmetry, clipping, overlapping, inconsistent sizes or fonts, thin lines/borders). "
        "Be specific about which element. Max 8 bullet points, no generic advice.")

def ask(img, text):
    b64 = base64.b64encode(open(os.path.join(HERE, "images", img), "rb").read()).decode()
    body = {"model": MODEL, "temperature": 0, "max_tokens": 12000,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": text}]}]}
    req = urllib.request.Request(URL, json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"})
    t = time.time()
    r = json.load(urllib.request.urlopen(req, timeout=900))
    m = r["choices"][0]["message"]
    reasoning = m.get("reasoning_content") or m.get("reasoning") or ""
    return {"answer": m.get("content"), "reasoning_chars": len(reasoning), "reasoning": reasoning,
            "finish": r["choices"][0].get("finish_reason"), "usage": r.get("usage"), "secs": round(time.time() - t, 1)}

out_path = os.path.join(HERE, f"results-{label}.json")
res = json.load(open(out_path)) if os.path.exists(out_path) else {}
for img, spec in Q.items():
    if only and img not in only: continue
    qs = spec["q"]
    text = (qs[0] if len(qs) == 1 else
            "Answer each question briefly, numbered:\n" + "\n".join(f"{i+1}. {q}" for i, q in enumerate(qs)))
    jobs = [("facts", text)] + ([("critique", CRIT)] if img.startswith("r") and DO_CRIT else [])
    for kind, prompt in jobs:
        key = f"{img}::{kind}"
        if key in res and res[key].get("answer"): continue
        try:
            res[key] = ask(img, prompt) | {"prompt": prompt}
        except Exception as e:
            res[key] = {"error": repr(e)}
        print(key, res[key].get("secs"), res[key].get("finish"), (res[key].get("answer") or res[key].get("error") or "")[:100].replace("\n", " "), flush=True)
        json.dump(res, open(out_path, "w"), indent=1, ensure_ascii=False)
print("done")
