"""Calibrate a character model from audio features against the user's own melodic/heavy tags.

Calibrates WITHIN the primary genre family — the melodic/heavy axis is genre-relative;
whole-library normalization washes it out against inherently-subby genres.

⚠️ Honest caveat, measured in development: the composite score captures brightness and
sub-weight but does NOT reliably match what a DJ *means* by "heavy" (that's often mid-bass
growl, unmeasured here). Treat scores as a soft signal; the user's own tags and stated
artist preferences always outrank it.

    uv run --with scikit-learn --with numpy python toolkit/calibrate.py
"""
import sys, json
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from djtk_config import load_config, workspace, genre_match

CFG = load_config()
FEATS = str(workspace(CFG, "audio_features.jsonl"))
OUT = str(workspace(CFG, "track_character.json"))
COLS = ["sub","lowmid","mid","hi","centroid","rolloff","bandwidth","flatness","zcr","rms","crest"]

allrows = [json.loads(l) for l in open(FEATS, encoding="utf-8") if l.strip()]
rows = [r for r in allrows if genre_match(CFG, "primary", r.get("genre") or "", r.get("bpm") or 0)]
print(f"tracks with features: {len(allrows)} total, {len(rows)} in primary family (calibrating within it)")
X = np.array([[r["f"][c] for c in COLS] for r in rows], float)
mu, sd = X.mean(0), X.std(0) + 1e-9
Xz = (X - mu) / sd

# training labels: pure-melodic (0) vs pure-heavy (1) by tags
y, idx = [], []
for i, r in enumerate(rows):
    if r["mel"] and not r["hvy"]: y.append(0); idx.append(i)
    elif r["hvy"] and not r["mel"]: y.append(1); idx.append(i)
y = np.array(y); Xtr = Xz[idx]
print(f"training set: {len(y)} tagged tracks ({(y==0).sum()} melodic, {(y==1).sum()} heavy)")

try:
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import cross_val_score
    clf = LogisticRegression(max_iter=2000, class_weight="balanced")
    acc = cross_val_score(clf, Xtr, y, cv=5).mean()
    clf.fit(Xtr, y)
    coef = clf.coef_[0]
    print(f"\n5-fold CV accuracy (melodic vs heavy from audio): {acc:.1%}")
    print("feature weights (+ => heavier):")
    for c, w in sorted(zip(COLS, coef), key=lambda t: -abs(t[1])):
        print(f"  {w:+6.2f}  {c}")
    heavy_prob = clf.predict_proba(Xz)[:, 1]
except Exception as e:
    print("sklearn unavailable, using z-score harshness fallback:", e)
    heavy_prob = None

# interpretable axes (from the 10-track probe): harshness (bright/aggressive) & darkness (subby)
ci = {c: k for k, c in enumerate(COLS)}
harsh = Xz[:, ci["centroid"]] + Xz[:, ci["hi"]] + Xz[:, ci["zcr"]] + Xz[:, ci["rolloff"]]
harsh = (harsh - harsh.mean()) / (harsh.std() + 1e-9)
dark = Xz[:, ci["sub"]] - Xz[:, ci["centroid"]]
dark = (dark - dark.mean()) / (dark.std() + 1e-9)

for i, r in enumerate(rows):
    r["harshness"] = round(float(harsh[i]), 2)
    r["darkness"] = round(float(dark[i]), 2)
    if heavy_prob is not None: r["heavy_prob"] = round(float(heavy_prob[i]), 3)

# MISLABELED detector: tagged melodic but audio says harsh/heavy — worth a listen/re-tag
print("\n=== MISLABELED SUSPECTS (tagged melodic, audio says harsh) — top 15 ===")
susp = [r for r in rows if r["mel"] and not r["hvy"]]
susp.sort(key=lambda r: -(r.get("heavy_prob", 0.5) + r["harshness"]*0.2))
for r in susp[:15]:
    hp = r.get("heavy_prob", "")
    print(f"  harsh={r['harshness']:+.2f} heavy_prob={hp}  {r['artist']} - {r['title'][:34]}")

for r in rows:
    r["heaviness"] = round(max(r["harshness"], r["darkness"]), 2)  # combined: bright-heavy OR dark-heavy
json.dump({r["id"]: {"harshness": r["harshness"], "darkness": r["darkness"],
                     "heaviness": r["heaviness"], "heavy_prob": r.get("heavy_prob")} for r in rows},
          open(OUT, "w", encoding="utf-8"))
print(f"\nper-track character scores written: {OUT}  ({len(rows)} tracks)")
