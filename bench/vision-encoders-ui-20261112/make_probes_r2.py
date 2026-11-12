"""Draws the 18 synthetic probes of this benchmark (1280x800, 1 px = 1 px): 9 light (s*, h*) and 9 dark (d*, e*).
Questions and reference answers: questions-v2.json."""
from PIL import Image, ImageDraw, ImageFont
import os
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images"); os.makedirs(OUT, exist_ok=True)
F = "/System/Library/Fonts/Supplemental/Arial.ttf"   # any TTF works; positions are what matter
def font(s): return ImageFont.truetype(F, s)
W, H = 1280, 800; BG = "#121212"; CARD = "#1c1c1c"; TXT = "#e0e0e0"; DIM = "#9a9a9a"
_truth = {}
def canvas(bg="white"):
    im = Image.new("RGB", (W, H), bg); return im, ImageDraw.Draw(im)
def dcanvas():
    return canvas(BG)

# s02: button row, one gap different
im, d = canvas()
x = 100; gaps = [16, 16, 16, 32, 16]; labels = ["Save", "Edit", "Copy", "Move", "Share", "Delete"]
for i, lab in enumerate(labels):
    d.rounded_rectangle([x, 350, x + 140, 398], radius=6, outline="#888", width=1, fill="#f4f4f4")
    d.text((x + 70, 374), lab, font=font(20), fill="black", anchor="mm")
    if i < len(gaps): x += 140 + gaps[i]
im.save(f"{OUT}/s02-button-gaps.png")
_truth["s02"] = {"buttons": 6, "odd_gap": "between Move and Share (32 px vs 16 px)"}

# s04: dialog off-centre horizontally (left margin 300, right 340)
im, d = canvas("#555555")
d.rectangle([300, 200, W - 340, 600], fill="white")
d.text((330, 230), "Delete rental #204?", font=font(26), fill="black")
d.text((330, 290), "This cannot be undone.", font=font(18), fill="#444")
d.rectangle([W - 340 - 30 - 120, 520, W - 340 - 30, 568], fill="#d33")
d.text((W - 340 - 30 - 60, 544), "Delete", font=font(18), fill="white", anchor="mm")
d.rectangle([W - 340 - 30 - 120 - 16 - 120, 520, W - 340 - 30 - 120 - 16, 568], outline="#888", fill="white")
d.text((W - 340 - 30 - 120 - 16 - 60, 544), "Cancel", font=font(18), fill="black", anchor="mm")
im.save(f"{OUT}/s04-dialog-centering.png")
_truth["s04"] = {"centered": False, "larger_margin": "right (340 px vs 300 px)"}

# s07: tabs with a 2 px underline under the active one (not the bold one)
im, d = canvas()
tabs = ["Overview", "Charges", "Documents", "Notes"]
x = 150
for t in tabs:
    d.text((x, 300), t, font=font(22), fill="black")
    if t == "Documents": d.rectangle([x, 334, x + 110, 335], fill="#1a5fd0")
    x += 200
im.save(f"{OUT}/s07-tab-underline.png")
_truth["s07"] = {"underlined_tab": "Documents (2 px blue line)"}

# s08: dividers, one dashed
im, d = canvas()
for i in range(4):
    y = 180 + i * 140
    d.text((100, y - 60), f"Section {i+1}", font=font(22), fill="black")
    if i == 2:
        for xx in range(100, 1180, 8): d.line([xx, y, xx + 3, y], fill="#aaa")
    else:
        d.line([100, y, 1180, y], fill="#aaa")
im.save(f"{OUT}/s08-dashed-divider.png")
_truth["s08"] = {"dashed": "the divider under Section 3"}

# s10: icon row, one icon smaller
im, d = canvas()
sizes = [32, 32, 32, 26, 32, 32]
for i, s in enumerate(sizes):
    cx = 200 + i * 160; cy = 400
    d.ellipse([cx - s // 2, cy - s // 2, cx + s // 2, cy + s // 2], outline="#222", width=2)
im.save(f"{OUT}/s10-icon-size.png")
_truth["s10"] = {"smaller_circle": "4th from left (26 px vs 32 px)"}

# h02: 7 buttons, one gap 20 instead of 12
im, d = canvas(); x = 70
labels = ["New", "Open", "Save", "Print", "Export", "Share", "Close"]; gaps = [12, 12, 12, 12, 20, 12]
for i, lab in enumerate(labels):
    d.rounded_rectangle([x, 370, x + 150, 418], radius=6, outline="#888", width=1, fill="#f4f4f4")
    d.text((x + 75, 394), lab, font=font(20), fill="black", anchor="mm")
    if i < len(gaps): x += 150 + gaps[i]
im.save(f"{OUT}/h02-button-gaps-small.png")

# h03: dialog 12 px off centre (left 334, right 346)
im, d = canvas("#555555")
d.rectangle([334, 220, W - 346, 580], fill="white")
d.text((364, 250), "Archive car BB68322?", font=font(26), fill="black")
im.save(f"{OUT}/h03-dialog-12px.png")

# h05: 6 circles, 5th is 30 px vs 34 px
im, d = canvas()
for i in range(6):
    s = 30 if i == 4 else 34; cx = 200 + i * 160; cy = 400
    d.ellipse([cx - s // 2, cy - s // 2, cx + s // 2, cy + s // 2], outline="#222", width=2)
im.save(f"{OUT}/h05-circle-small-diff.png")

# h07: 4 boxes with 1 px borders; one border slightly different colour (blue-grey vs grey)
im, d = canvas()
for i in range(4):
    x0 = 120 + i * 270; col = "#8a9bb8" if i == 1 else "#9a9a9a"
    d.rectangle([x0, 300, x0 + 220, 480], outline=col)
    d.text((x0 + 20, 320), f"Box {chr(65+i)}", font=font(22), fill="black")
im.save(f"{OUT}/h07-border-colour.png")

# d01: dividers 1/2/1/3/1 px, #3a3a3a on near-black
im, d = dcanvas(); d.text((60, 30), "Settings", font=font(28), fill=TXT)
for i, w in enumerate([1, 2, 1, 3, 1]):
    y = 140 + i * 120; d.text((60, y - 50), f"Row {chr(65+i)}", font=font(20), fill=DIM)
    d.rectangle([60, y, 1220, y + w - 1], fill="#3a3a3a")
im.save(f"{OUT}/d01-dark-hairlines.png")

# d03: 5 dark cards, card 2 shifted 4 px LEFT
im, d = dcanvas()
for i in range(5):
    o = -4 if i == 1 else 0; y = 60 + i * 140
    d.rectangle([200 + o, y, 1080 + o, y + 110], fill=CARD, outline="#333333")
    d.text((230 + o, y + 40), f"Card {i+1}: Booking #{300+i}", font=font(22), fill=TXT)
im.save(f"{OUT}/d03-dark-card-shift.png")

# d05: 6 boxes, Insurance missing its RIGHT side
im, d = dcanvas()
for i, n in enumerate(["Mileage", "Service", "Insurance", "Registration", "VAT", "Salik"]):
    r, c = divmod(i, 3); x0 = 120 + c * 360; y0 = 150 + r * 260; x1, y1 = x0 + 320, y0 + 200
    d.line([x0, y0, x1, y0], fill="#4a4a4a"); d.line([x0, y0, x0, y1], fill="#4a4a4a"); d.line([x0, y1, x1, y1], fill="#4a4a4a")
    if n != "Insurance": d.line([x1, y0, x1, y1], fill="#4a4a4a")
    d.text((x0 + 20, y0 + 20), n, font=font(22), fill=TXT)
im.save(f"{OUT}/d05-dark-missing-border.png")

# d06: key/value rows, Phone value 3 px HIGHER
im, d = dcanvas()
for i, (k, v) in enumerate([("Customer", "Nadia Haddad"), ("Phone", "+971 50 000 1234"), ("Contract", "01.09.2026"), ("Deposit", "AED 2,000"), ("Status", "On rent")]):
    y = 120 + i * 110; dy = -3 if k == "Phone" else 0
    d.text((150, y), k, font=font(24), fill=DIM); d.text((600, y + dy), v, font=font(24), fill=TXT)
    d.line([150, y + 60, 1100, y + 60], fill="#2a2a2a")
im.save(f"{OUT}/d06-dark-baseline.png")

# d09: grid 8 vertical x 6 horizontal (incl. frame), #2c2c2c
im, d = dcanvas()
for i in range(8): x = 150 + i * 140; d.line([x, 120, x, 620], fill="#2c2c2c")
for j in range(6): y = 120 + j * 100; d.line([150, y, 1130, y], fill="#2c2c2c")
im.save(f"{OUT}/d09-dark-gridlines.png")

# e01: 6 dark cards, card 4 shifted 3 px right
im, d = dcanvas()
for i in range(6):
    o = 3 if i == 3 else 0; y = 40 + i * 125
    d.rectangle([200 + o, y, 1080 + o, y + 100], fill=CARD, outline="#333333")
    d.text((230 + o, y + 36), f"Card {i+1}: Rental #{410+i}", font=font(22), fill=TXT)
im.save(f"{OUT}/e01-dark-card-shift-3px.png")

# e04: very faint dividers #1f1f1f on #121212, Item 2 has none
im, d = dcanvas()
for i in range(5):
    y = 130 + i * 120; d.text((120, y), f"Item {i+1}", font=font(22), fill=TXT)
    if i != 1: d.line([120, y + 60, 1160, y + 60], fill="#1f1f1f")
im.save(f"{OUT}/e04-dark-faint-dividers.png")

# e06: 10 thin vertical lines #333 on near-black
im, d = dcanvas()
for i in range(10): x = 160 + i * 105; d.line([x, 200, x, 600], fill="#333333")
im.save(f"{OUT}/e06-dark-count-10-lines.png")

# e08: two text columns, LEFT column 3 px lower
im, d = dcanvas()
for i in range(6):
    d.text((120, 153 + i * 70), f"Left line {i+1}", font=font(22), fill=TXT)
    d.text((700, 150 + i * 70), f"Right line {i+1}", font=font(22), fill=TXT)
im.save(f"{OUT}/e08-dark-columns-3px.png")

print("18 probes drawn")
