"""Train the drop ranker on per-beat features from cue_extract.py.

Candidates are every BAR (4 beats) in the search window — the old detector only
tested 8-bar boundaries and 11% of real drops weren't even in its candidate set
(tracks with pickups / odd intro lengths shift the phrase grid). Each candidate
gets ~50 features describing build -> break -> impact, and a gradient-boosted
ranker picks the drop. Ground truth = the DJ's own anchor cues.

Evaluation is 5-fold cross-validation grouped by track, so every reported
number is from tracks the model never saw. Reports:
    exact       predicted beat == true beat after local refinement
    near        within 1 bar
    in-phrase   within 8 bars
    top-3       truth among 3 best candidates (Demucs re-check budget)

    uv run --with scikit-learn --with numpy python cue_train.py
"""

import json
import pickle

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import GroupKFold

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).parent))
from djtk_config import load_config as _lc, workspace as _ws
_CFG = _lc()
DATA_PATH = str(_ws(_CFG, "cue_beat_features.jsonl"))
MODEL_PATH = str(_ws(_CFG, "cue_ranker.pkl"))

STEP = 4          # candidate every bar
TOL = 2           # |pred - true| <= TOL counts as a hit for the classifier label
SEARCH_LO, SEARCH_HI = 0.06, 0.52


def load_tracks():
    tracks = []
    for line in open(DATA_PATH, encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        arrs = {}
        for k in ("bb", "sb", "hi", "cen", "on"):
            a = np.array([np.nan if v is None else v for v in r[k]], dtype=float)
            arrs[k] = a
        r["arrs"] = arrs
        tracks.append(r)
    return tracks


def znorm(a):
    m, s = np.nanmean(a), np.nanstd(a)
    return (a - m) / (s + 1e-9)


def wm(a, lo, hi):
    """nan-safe mean of a[lo:hi], 0.0 (i.e. 'track average') when empty."""
    lo, hi = max(0, lo), max(0, hi)
    seg = a[lo:hi]
    if seg.size == 0 or np.all(np.isnan(seg)):
        return 0.0
    return float(np.nanmean(seg))


FEATURE_NAMES = []  # filled on first call, for importance reporting


def candidate_features(z, b, n_beats, bpm, artist_prior):
    names = []
    f = []
    for key in ("bb", "sb", "hi", "on"):
        a = z[key]
        for lo, hi in ((-32, -16), (-16, -8), (-8, -4), (-4, 0), (0, 4), (4, 8), (8, 16), (16, 32)):
            f.append(wm(a, b + lo, b + hi))
            names.append(f"{key}[{lo}:{hi}]")
    for key in ("bb", "sb"):
        a = z[key]
        for h in (8, 16, 32):
            f.append(wm(a, b, b + h) - wm(a, b - h, b))
            names.append(f"{key}_delta{h}")
    # riser: high band climbing into the candidate
    hi_a = z["hi"]
    seg = hi_a[max(0, b - 16) : b]
    if seg.size >= 8 and not np.all(np.isnan(seg)):
        x = np.arange(seg.size, dtype=float)
        m = ~np.isnan(seg)
        slope = float(np.polyfit(x[m], seg[m], 1)[0]) if m.sum() >= 4 else 0.0
    else:
        slope = 0.0
    f.append(slope)
    names.append("hi_slope16")
    f.append(wm(z["cen"], b - 8, b) - wm(z["cen"], b - 24, b - 16))
    names.append("cen_rise")
    # drum fill in the last bar
    f.append(wm(z["on"], b - 4, b) - wm(z["on"], b - 12, b - 4))
    names.append("fill")
    # break depth: how far the preceding minimum sits below the arrival
    pre = z["bb"][max(0, b - 32) : b]
    pre_min = float(np.nanmin(pre)) if pre.size and not np.all(np.isnan(pre)) else 0.0
    f.append(wm(z["bb"], b, b + 8) - pre_min)
    names.append("dip")
    # break signature: a real drop follows bars where the bass is GONE, and is
    # usually not the first bass in the track (the intro groove came earlier) —
    # this is exactly what separates the drop from the intro landing
    sb_a = z["sb"]
    pre_seg = sb_a[max(0, b - 24) : max(0, b - 4)]
    if pre_seg.size and not np.all(np.isnan(pre_seg)):
        f.append(float(np.nanmean(pre_seg < -0.5)))
    else:
        f.append(0.0)
    names.append("bass_absent_before")
    early = sb_a[: max(0, b - 32)]
    f.append(float(np.nanmax(early)) if early.size and not np.all(np.isnan(early)) else -2.0)
    names.append("earlier_bass_max")
    # position / grid phase
    rel = b / n_beats
    f += [rel, (b % 32) / 32.0, (b % 16) / 16.0, min(b % 32, 32 - b % 32) / 16.0, bpm / 174.0]
    names += ["rel", "mod32", "mod16", "dist_phrase", "bpm"]
    # artist prior: where this artist tends to put the drop
    f += [artist_prior, rel - artist_prior]
    names += ["artist_prior", "rel_minus_prior"]

    global FEATURE_NAMES
    if not FEATURE_NAMES:
        FEATURE_NAMES = names
    return f


EXTRA_NAMES = [
    "phase_dist", "phase_strength",           # global phrase-phase estimate
    "parse_dist", "parse_hit", "parse_first", # whole-track Viterbi structure parse
    "step_here", "step_rank", "step_gap",     # listwise: this arrival vs the track's others
    "sb32_rank", "sb32_gap", "dip_rank",
]


def track_candidates(rec, artist_prior):
    arrs = rec["arrs"]
    n_beats = rec["n_beats"]
    valid = ~np.isnan(arrs["bb"])
    if valid.sum() < 96:
        return None
    last = int(np.max(np.where(valid)[0]))
    z = {k: znorm(a) for k, a in arrs.items()}
    lo = max(16, int(n_beats * SEARCH_LO))
    hi = min(last - 8, int(n_beats * SEARCH_HI))
    if hi <= lo:
        return None
    beats = list(range(lo - lo % STEP + STEP, hi, STEP))
    X = np.array(
        [candidate_features(z, b, n_beats, rec["bpm"], artist_prior) for b in beats],
        dtype=float,
    )

    # global signals computed once per track
    steps = sub_steps(z["sb"])
    phi, strength, r4 = phrase_phase(steps)
    rec["_r4"] = r4  # used by refine()
    trans = viterbi_parse(0.5 * np.nan_to_num(z["bb"]) + 0.5 * np.nan_to_num(z["sb"]))

    i_sb32 = FEATURE_NAMES.index("sb_delta32")
    i_dip = FEATURE_NAMES.index("dip")
    sb32 = X[:, i_sb32]
    dip = X[:, i_dip]
    cand_steps = np.array([steps[b] if b < len(steps) else 0.0 for b in beats])

    def rank_of(v):
        # 0 = biggest in this track's candidate list
        return np.argsort(np.argsort(-v)) / max(1, len(v) - 1)

    extra = np.zeros((len(beats), len(EXTRA_NAMES)))
    sb32_rank, step_rank, dip_rank = rank_of(sb32), rank_of(cand_steps), rank_of(dip)
    for j, b in enumerate(beats):
        d = abs((b - phi) % 32)
        extra[j, 0] = min(d, 32 - d) / 16.0
        extra[j, 1] = min(strength, 8.0)
        pd = min((abs(b - t) for t in trans), default=64)
        extra[j, 2] = min(pd, 64) / 32.0
        extra[j, 3] = 1.0 if pd <= 2 else 0.0
        extra[j, 4] = 1.0 if trans and abs(b - trans[0]) <= 2 else 0.0
        extra[j, 5] = cand_steps[j]
        extra[j, 6] = step_rank[j]
        extra[j, 7] = cand_steps[j] - cand_steps.max()
        extra[j, 8] = sb32_rank[j]
        extra[j, 9] = sb32[j] - sb32.max()
        extra[j, 10] = dip_rank[j]

    return beats, np.hstack([X, extra])


try:
    import lightgbm as lgb
except ImportError:
    lgb = None


def fit_model(X, y, group_sizes):
    """LambdaMART ranker when lightgbm is available (optimizes the ordering of
    candidates within each track, which is the actual task); weighted binary
    classifier otherwise."""
    if lgb is not None:
        rk = lgb.LGBMRanker(
            objective="lambdarank",
            n_estimators=400,
            learning_rate=0.06,
            num_leaves=63,
            label_gain=[0, 1],
            verbose=-1,
            random_state=7,
        )
        rk.fit(X, y, group=group_sizes)
        return rk
    w = np.where(y == 1, (y == 0).sum() / max(1, (y == 1).sum()), 1.0)
    clf = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.08, random_state=7)
    clf.fit(X, y, sample_weight=w)
    return clf


def model_scores(model, X):
    if hasattr(model, "predict_proba"):
        return model.predict_proba(X)[:, 1]
    return model.predict(X)


REFINE_MARGIN = 1.5  # dB the neighbour must win by before we leave the bar line


def sub_steps(sb):
    """8-beat sub-bass step at every beat (positive = bass arriving)."""
    n = len(sb)
    out = np.zeros(n)
    for b in range(8, n - 8):
        out[b] = wm(sb, b, b + 8) - wm(sb, b - 8, b)
    return out


def phrase_phase(steps):
    """Estimate the track's global phrase phase: all structural arrivals in a
    track sit on the same 32-beat grid, so the phase is inferred from all of
    them at once instead of guessed per candidate. Returns (phase 0-31,
    strength ratio, per-beat-in-bar phase 0-3)."""
    prof32 = np.zeros(32)
    prof4 = np.zeros(4)
    for b, s in enumerate(steps):
        if s > 0:
            prof32[b % 32] += s
            prof4[b % 4] += s
    phi = int(np.argmax(prof32))
    strength = float(prof32[phi] / (prof32.mean() + 1e-9))
    return phi, strength, int(np.argmax(prof4))


def viterbi_parse(x):
    """3-state (LOW / MID / HIGH energy) Viterbi parse of the whole track.
    Emissions from combined bass+broadband z-score; switching is penalized
    (heavily off bar lines), which forces a phrase-consistent global story.
    Returns the beats where the parse enters HIGH — structural drop moments."""
    n = len(x)
    x = np.nan_to_num(x, nan=0.0)
    em = np.stack([-x - 0.3, -0.5 * np.abs(x), x - 0.3])  # LOW, MID, HIGH
    SW = 3.0
    dp = em[:, 0].copy()
    bp = np.zeros((3, n), dtype=np.int8)
    for b in range(1, n):
        pen = SW + (2.0 if b % 4 else 0.0)
        for s in range(3):
            costs = dp + np.where(np.arange(3) == s, 0.0, -pen)
            bp[s, b] = int(np.argmax(costs))
            dp_new = costs[bp[s, b]] + em[s, b]
            if s == 0:
                nxt = np.empty(3)
            nxt[s] = dp_new
        dp = nxt.copy()
    states = np.empty(n, dtype=np.int8)
    states[-1] = int(np.argmax(dp))
    for b in range(n - 1, 0, -1):
        states[b - 1] = bp[states[b], b]
    return [b for b in range(1, n) if states[b] == 2 and states[b - 1] != 2]


def refine(rec, b):
    """Exact-beat refinement. 84% of real drops sit exactly on the bar grid and
    the rest are +-1 beat. The track's own bar phase (from phrase_phase) votes
    alongside the local sub-bass step; a neighbour must beat the bar line by a
    clear margin to win."""
    sb = rec["arrs"]["sb"]

    def step(bb_):
        return wm(sb, bb_, bb_ + 8) - wm(sb, bb_ - 8, bb_)

    r4 = rec.get("_r4")
    base = step(b)
    best, best_v = b, base
    for bb_ in (b - 1, b + 1):
        if 4 <= bb_ < len(sb) - 8:
            v = step(bb_)
            margin = REFINE_MARGIN
            if r4 is not None and bb_ % 4 == r4 and b % 4 != r4:
                margin = 0.0  # neighbour matches the track's own phase — trust it sooner
            if v > best_v and v > base + margin:
                best, best_v = bb_, v
    return best


def artist_priors(tracks, idxs):
    by_artist = {}
    for i in idxs:
        r = tracks[i]
        by_artist.setdefault(r["artist"], []).append(r["c_beat"] / r["n_beats"])
    med = {a: float(np.median(v)) for a, v in by_artist.items()}
    glob = float(np.median([r["c_beat"] / r["n_beats"] for i in idxs for r in [tracks[i]]]))
    return med, glob


def old_heuristic_baseline(tracks):
    """The previous hand-tuned detector, re-run from the cached arrays, so old
    and new are scored on identical tracks and metrics."""
    hits0 = hits2 = n = 0
    for r in tracks:
        arrs = r["arrs"]
        n_beats = r["n_beats"]
        valid = ~np.isnan(arrs["bb"])
        if valid.sum() < 96:
            continue
        zb, zs = znorm(arrs["bb"]), znorm(arrs["sb"])
        last = int(np.max(np.where(valid)[0]))
        best, best_s = None, -1e9
        for b in range(32, min(last - 32, int(n_beats * 0.50))):
            if b % 32:
                continue
            lift = (wm(zb, b, b + 32) - wm(zb, b - 32, b)) + 1.5 * (wm(zs, b, b + 32) - wm(zs, b - 32, b))
            sub_level = wm(zs, b, b + 32)
            prior = -0.5 * ((b / n_beats - 0.22) / 0.07) ** 2
            s = 0.5 * lift + 2.0 * sub_level + 8.0 * prior
            if s > best_s:
                best, best_s = b, s
        if best is None:
            continue
        n += 1
        hits0 += best == r["c_beat"]
        hits2 += abs(best - r["c_beat"]) <= 2
    return hits0 / n, hits2 / n, n


def main():
    tracks = load_tracks()
    print(f"tracks loaded: {len(tracks)}")

    b0, b2, bn = old_heuristic_baseline(tracks)
    print(f"OLD heuristic baseline (same tracks): err==0 {100*b0:.1f}%  |err|<=2 {100*b2:.1f}%  (n={bn})\n")

    groups = np.arange(len(tracks))
    gkf = GroupKFold(n_splits=5)
    stats = {"exact": 0, "exact2": 0, "near": 0, "phrase": 0, "top3": 0, "n": 0}
    misses = []
    cv_top3 = {}  # out-of-fold top-3 per track, for the Demucs verification stage

    for fold, (tr_idx, te_idx) in enumerate(gkf.split(groups, groups=groups)):
        prior_med, prior_glob = artist_priors(tracks, tr_idx)

        def build(idxs, use_prior_map):
            X, y, tids = [], [], []
            for i in idxs:
                r = tracks[i]
                ap = use_prior_map.get(r["artist"], prior_glob)
                tc = track_candidates(r, ap)
                if tc is None:
                    continue
                beats, feats = tc
                labels = [1 if abs(b - r["c_beat"]) <= TOL else 0 for b in beats]
                if not any(labels):
                    # truth not on a bar candidate (odd grid) — snap label to nearest
                    nearest = int(np.argmin([abs(b - r["c_beat"]) for b in beats]))
                    labels[nearest] = 1
                X.append(feats)
                y.append(np.array(labels))
                tids.append(i)
            return X, y, tids

        Xtr, ytr, _ = build(tr_idx, prior_med)
        Xte, yte, te_ids = build(te_idx, prior_med)
        Xtr_f = np.vstack(Xtr)
        ytr_f = np.concatenate(ytr)
        clf = fit_model(Xtr_f, ytr_f, [x.shape[0] for x in Xtr])

        for feats, labels, i in zip(Xte, yte, te_ids):
            r = tracks[i]
            proba = model_scores(clf, feats)
            order = np.argsort(-proba)
            tc = track_candidates(r, prior_med.get(r["artist"], prior_glob))
            beats = tc[0]
            pred_bar = beats[order[0]]
            pred = refine(r, pred_bar)
            err = pred - r["c_beat"]
            cv_top3[r["id"]] = {
                "title": r["title"],
                "true_beat": r["c_beat"],
                "pred": int(pred),
                "top3": [int(beats[o]) for o in order[:3]],
                "scores": [float(proba[o]) for o in order[:3]],
            }
            stats["n"] += 1
            stats["exact"] += err == 0
            stats["exact2"] += abs(err) <= 2
            stats["near"] += abs(err) <= 4
            stats["phrase"] += abs(err) <= 32
            stats["top3"] += any(abs(beats[o] - r["c_beat"]) <= TOL for o in order[:3])
            if abs(err) > 4:
                misses.append((err, r["title"], r["artist"]))
        print(f"  fold {fold+1}: cumulative err==0 {100*stats['exact']/stats['n']:.1f}% (n={stats['n']})", flush=True)

    n = stats["n"]
    print(f"\n{'='*60}\n5-FOLD CV (grouped by track), n={n} tracks\n{'='*60}")
    print(f"  beat-perfect (err==0)  : {100*stats['exact']/n:5.1f}%   [old: {100*b0:.1f}%]")
    print(f"  within half-bar (<=2)  : {100*stats['exact2']/n:5.1f}%   [old: {100*b2:.1f}%]")
    print(f"  within 1 bar           : {100*stats['near']/n:5.1f}%")
    print(f"  within 1 phrase        : {100*stats['phrase']/n:5.1f}%")
    print(f"  truth in top-3         : {100*stats['top3']/n:5.1f}%")
    print(f"\n  misses > 1 bar: {len(misses)}")
    for err, title, artist in misses[:12]:
        print(f"    {err:+5d} beats  {title[:42]:42s} {artist[:20]}")

    json.dump(cv_top3, open(str(_ws(_CFG, "cue_cv_top3.json")), "w"))
    print(f"  wrote cue_cv_top3.json ({len(cv_top3)} out-of-fold predictions)")

    # final model on everything, plus priors for inference
    prior_med, prior_glob = artist_priors(tracks, range(len(tracks)))
    X, y = [], []
    for r in tracks:
        tc = track_candidates(r, prior_med.get(r["artist"], prior_glob))
        if tc is None:
            continue
        beats, feats = tc
        labels = [1 if abs(b - r["c_beat"]) <= TOL else 0 for b in beats]
        if not any(labels):
            labels[int(np.argmin([abs(b - r["c_beat"]) for b in beats]))] = 1
        X.append(feats)
        y.append(np.array(labels))
    Xf, yf = np.vstack(X), np.concatenate(y)
    clf = fit_model(Xf, yf, [x.shape[0] for x in X])

    with open(MODEL_PATH, "wb") as fh:
        pickle.dump(
            {
                "model": clf,
                "artist_prior": prior_med,
                "global_prior": prior_glob,
                "feature_names": FEATURE_NAMES + EXTRA_NAMES,
                "step": STEP,
                "search": (SEARCH_LO, SEARCH_HI),
                "cv_exact": stats["exact"] / n,
                "cv_phrase": stats["phrase"] / n,
                "n_tracks": n,
            },
            fh,
        )
    print(f"\nwrote {MODEL_PATH} (trained on all {len(X)} tracks)")


if __name__ == "__main__":
    main()
