#!/usr/bin/env python3
"""Write the 48 router matrices (blk.N.ffn_gate_inp.weight, F32 512x2560) of a Qwen3.8-Flash-Next GGUF to
data/router-gate-inp.bin.  Pure Python (no numpy, no gguf package): python3 extract_routers.py <shard-1-of-N.gguf>"""
import glob, os, struct, sys
TS = {0: 4, 1: 2, 30: 2}   # F32, F16, BF16 element sizes
SZ = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}
first = sys.argv[1]
shards = sorted(glob.glob(first.replace("00001-of", "0000*-of"))) or [first]
found = {}
for fn in shards:
    f = open(fn, "rb"); rd = f.read
    assert rd(4) == b"GGUF"; struct.unpack("<I", rd(4)); nt, nkv = struct.unpack("<QQ", rd(16))
    def rstr(): n, = struct.unpack("<Q", rd(8)); return rd(n).decode("utf-8", "replace")
    def rval(t):
        if t == 8: return rstr()
        if t == 9:
            at, n = struct.unpack("<IQ", rd(12)); return [rval(at) for _ in range(n)]
        return rd(SZ[t])
    align = 32
    for _ in range(nkv):
        k = rstr(); t, = struct.unpack("<I", rd(4)); v = rval(t)
        if k == "general.alignment": align = struct.unpack("<I", v)[0]
    infos = []
    for _ in range(nt):
        name = rstr(); nd, = struct.unpack("<I", rd(4)); dims = struct.unpack(f"<{nd}Q", rd(8 * nd))
        typ, off = struct.unpack("<IQ", rd(12)); infos.append((name, dims, typ, off))
    base = (f.tell() + align - 1) // align * align
    for name, dims, typ, off in infos:
        if name.startswith("blk.") and name.endswith(".ffn_gate_inp.weight"):
            assert typ == 0, f"{name}: type {typ}, this script expects F32 routers"
            n = 1
            for d in dims: n *= d
            f.seek(base + off); found[int(name.split(".")[1])] = f.read(n * TS[typ])
os.makedirs("data", exist_ok=True)
with open("data/router-gate-inp.bin", "wb") as out:
    for l in range(len(found)): out.write(found[l])
print(f"{len(found)} routers -> data/router-gate-inp.bin")
