"""Classify tracks none/light/mainly-vocal. The user's Vocal tag is GROUND TRUTH. READ-ONLY.

    uv run --with numpy python toolkit/vocal_calibrate.py [--family primary|secondary]
"""
import sys, json
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from djtk_config import load_config, workspace

CFG = load_config()
FAMILY = "secondary" if "--family" in sys.argv and "secondary" in sys.argv else "primary"
FEATS = str(workspace(CFG, f"vocal_features_{FAMILY}.jsonl"))
OUT = str(workspace(CFG, f"track_vocal_{FAMILY}.json"))

rows = [json.loads(l) for l in open(FEATS, encoding="utf-8") if l.strip()]
print(f"tracks with vocal features: {len(rows)}")
E = np.array([r["voc_energy"] for r in rows])
F = np.array([r["voc_frac"] for r in rows])
tagged = np.array([r["tagged_vocal"] for r in rows])
print(f"tagged Vocal: {tagged.sum()}")

def pct(a, p): return float(np.percentile(a, p)) if len(a) else 0.0
# MEASURED in development: Demucs voc_frac does NOT separate vocal from instrumental on
# bass-heavy electronic music (synth bleed into the vocal stem; ~26% of known-vocal tracks
# read instrumental). So audio is NOT trusted to grade the user's own tracks.
# GROUND TRUTH = the user's Vocal MyTag. Audio only SUGGESTS tags for untagged tracks.
# NOTE: `tagged_vocal` is stamped at extract time and goes STALE as tags change — refresh
# it from the live DB (find_vocal_credits.py does this) before trusting this classification.
print("\nvoc_energy — TAGGED pct:", [round(pct(E[tagged], p),3) for p in (25,50,75)],
      "| UNtagged pct:", [round(pct(E[~tagged], p),3) for p in (50,75,90,95)])
print("voc_frac   — TAGGED pct:", [round(pct(F[tagged], p),3) for p in (25,50,75)],
      "| UNtagged pct:", [round(pct(F[~tagged], p),3) for p in (50,75,90)])

# Suggestion bar for UNTAGGED tracks only: energy well above the tagged-median so we surface
# a short, high-precision review list rather than hundreds of Demucs false positives.
SUGGEST_E = round(max(pct(E[tagged], 60), 0.10), 3)
SUGGEST_F = 0.60
print(f"\nMODEL: tagged Vocal -> level 2 (user ground truth). untagged -> level 0.")
print(f"  tag SUGGESTIONS for untagged: voc_energy > {SUGGEST_E} AND voc_frac > {SUGGEST_F}")

def level(r):
    if r["tagged_vocal"]:
        return 2                                     # user tag = vocal-heavy, authoritative
    if r["voc_energy"] > SUGGEST_E and r["voc_frac"] > SUGGEST_F:
        return 1                                     # untagged but strong signal -> light / review
    return 0

for r in rows: r["level"] = level(r)
from collections import Counter
print("classification:", {0:"instrumental",1:"light/untagged-candidate",2:"vocal (tagged)"},
      dict(Counter(r["level"] for r in rows)))

# tag candidates: untagged tracks whose audio is strongly vocal — for user review, NOT auto-applied
new = [r for r in rows if r["level"] == 1]
new.sort(key=lambda r: -(r["voc_energy"]))
print(f"\n=== {len(new)} untagged tracks look vocal — candidates to review & tag Vocal ===")
for r in new[:20]:
    print(f"  en={r['voc_energy']:.3f} frac={r['voc_frac']:.2f}  {r['artist']} - {r['title'][:40]}")

# MANUAL OVERRIDES win over the audio model — the user's ear is the ground truth.
# config preferences.vocal_overrides maps track_id -> forced level (0/1/2), and survives
# every recalibration; the audio never overwrites a hand-corrected label.
out = {r["id"]: {"voc_energy": r["voc_energy"], "voc_frac": r["voc_frac"], "level": r["level"]} for r in rows}
try:
    ov = (CFG.get("preferences") or {}).get("vocal_overrides", {})
    applied = 0
    for tid, spec in ov.items():
        lvl = spec.get("level") if isinstance(spec, dict) else spec
        if lvl is None:
            continue
        rec = out.setdefault(tid, {"voc_energy": None, "voc_frac": None})
        if rec.get("level") != lvl:
            applied += 1
        rec["level"] = lvl
        rec["override"] = True
    print(f"\napplied {applied} manual vocal overrides from config ({len(ov)} defined)")
except FileNotFoundError:
    pass

json.dump(out, open(OUT, "w", encoding="utf-8"))
print(f"per-track vocal levels written: {OUT} (0=instrumental,1=light,2=mainly)")
