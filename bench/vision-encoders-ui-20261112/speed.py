"""Speed probe, run right after an engine start (fresh picture cache): each picture once, 1 output token, no thinking.
Wall time per request; engine log 'prompt N tokens ... read in X ms' gives the language-model share; the rest = upload +
picture reader + overhead.  usage: STRATA_KEY=... python3 speed.py <label>"""
import base64, json, os, subprocess, sys, time, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
URL = os.environ.get("STRATA_URL", "http://127.0.0.1:8080") + "/v1/chat/completions"
KEY = os.environ["STRATA_KEY"]; label = sys.argv[1]
PICS = ["r01-cars-chart-alerts.png", "r03-minimal-example.png", "r05-telltale-example.png", "r06-terminal-mobile.png",
        "s02-button-gaps.png", "big5k.png"]
LOG = os.environ["STRATA_LOG"]          # the server log file (config "log" key)
rows = []
for p in PICS:
    path = os.path.join(HERE, "images", p)
    b64 = base64.b64encode(open(path, "rb").read()).decode()
    body = {"model": "x", "max_tokens": 1, "temperature": 0, "chat_template_kwargs": {"enable_thinking": False},
            "messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}},
                                                      {"type": "text", "text": f"Speed probe {p}. Reply OK."}]}]}
    req = urllib.request.Request(URL, json.dumps(body).encode(), {"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"})
    t = time.time(); r = json.load(urllib.request.urlopen(req, timeout=900)); wall = time.time() - t
    line = subprocess.run(["sh", "-c", f"grep 'strata serve: prompt ' {LOG} | tail -1"], capture_output=True, text=True).stdout.strip()
    read_ms = int(line.split(" read in ")[1].split(" ms")[0]) if " read in " in line else None
    rows.append({"pic": p, "prompt_tokens": r["usage"]["prompt_tokens"], "wall_s": round(wall, 2),
                 "llm_read_s": read_ms and round(read_ms / 1000, 2), "picture_s": read_ms and round(wall - read_ms / 1000, 2)})
    print(rows[-1], flush=True)
json.dump(rows, open(os.path.join(HERE, f"speed-{label}.json"), "w"), indent=1)
