"""Calibrate confidence tiers for the drop ranker.

Uses the out-of-fold predictions (cue_cv_top3.json): the score margin between
the #1 and #2 candidates is binned, and each bin's empirical beat-perfect rate
becomes the tier's honest accuracy estimate. Saved to cue_confidence.json for
--propose / cue_batch.py to report per-track confidence.

    uv run --with numpy python cue_confidence.py
"""

import json
import numpy as np

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).parent))
from djtk_config import load_config as _lc, workspace as _ws
_CFG = _lc()
TOP3 = json.load(open(str(_ws(_CFG, "cue_cv_top3.json"))))
OUT = str(_ws(_CFG, "cue_confidence.json"))

rows = []
for tid, r in TOP3.items():
    if len(r["scores"]) < 2:
        continue
    margin = r["scores"][0] - r["scores"][1]
    rows.append((margin, r["pred"] == r["true_beat"], abs(r["pred"] - r["true_beat"]) <= 32))

rows.sort(key=lambda x: -x[0])
margins = np.array([r[0] for r in rows])
exact = np.array([r[1] for r in rows])
phrase = np.array([r[2] for r in rows])
n = len(rows)
print(f"out-of-fold predictions: {n}")

# terciles by margin
edges = [np.quantile(margins, q) for q in (2 / 3, 1 / 3)]
tiers = []
for name, mask in (
    ("high", margins >= edges[0]),
    ("medium", (margins < edges[0]) & (margins >= edges[1])),
    ("low", margins < edges[1]),
):
    tiers.append(
        {
            "tier": name,
            "min_margin": float(margins[mask].min()) if name != "low" else None,
            "n": int(mask.sum()),
            "exact_rate": round(float(exact[mask].mean()), 3),
            "phrase_rate": round(float(phrase[mask].mean()), 3),
        }
    )
    print(
        f"  {name:6s} (margin >= {tiers[-1]['min_margin'] if tiers[-1]['min_margin'] is not None else '-inf'}): "
        f"n={mask.sum():3d}  beat-perfect {100*exact[mask].mean():.1f}%  in-phrase {100*phrase[mask].mean():.1f}%"
    )

json.dump({"tiers": tiers, "tercile_edges": [float(e) for e in edges]}, open(OUT, "w"), indent=1)
print(f"\nwrote {OUT}")
