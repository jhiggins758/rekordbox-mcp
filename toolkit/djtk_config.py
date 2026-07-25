"""Shared configuration for the DJ toolkit.

Every toolkit script reads one JSON config instead of hardcoding paths, MyTag IDs,
or genre assumptions. Resolution order:

    1. $DJTK_CONFIG            (explicit path to a config file)
    2. ./config.json           (current working directory)
    3. ~/.dj-toolkit/config.json

Run the `dj-onboard` skill (see skills/dj-onboard/) to generate a config
interactively — it maps your MyTags, mines your cue system from your own cued
tracks, and records your preferences. Or copy `config.example.json` and fill it
in by hand.

All generated artifacts (audio features, calibrations, trained models, reports)
are written under `workspace` so nothing pollutes the repo or your library.
"""

import json
import os
from pathlib import Path

EXAMPLE = Path(__file__).parent / "config.example.json"


def config_path() -> Path:
    env = os.environ.get("DJTK_CONFIG")
    if env:
        return Path(env).expanduser()
    cwd = Path.cwd() / "config.json"
    if cwd.exists():
        return cwd
    return Path.home() / ".dj-toolkit" / "config.json"


def load_config() -> dict:
    p = config_path()
    if not p.exists():
        raise SystemExit(
            f"No toolkit config found at {p}.\n"
            f"Run the dj-onboard skill to create one, or copy\n"
            f"  {EXAMPLE}\n"
            f"to {p} and fill it in."
        )
    cfg = json.loads(p.read_text(encoding="utf-8"))
    cfg["_path"] = str(p)
    return cfg


def workspace(cfg: dict, *parts: str) -> Path:
    """Path inside the artifact workspace (created on first use)."""
    ws = Path(cfg.get("workspace") or "~/.dj-toolkit").expanduser()
    ws.mkdir(parents=True, exist_ok=True)
    out = ws.joinpath(*parts)
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


def save_config(cfg: dict) -> None:
    p = Path(cfg.get("_path") or config_path())
    clean = {k: v for k, v in cfg.items() if not k.startswith("_")}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(clean, indent=1, ensure_ascii=False), encoding="utf-8")


def genre_match(cfg: dict, family: str, genre_name: str, bpm: float) -> bool:
    """Does a track's genre string + BPM fall in the configured genre family?"""
    fam = (cfg.get("genres") or {}).get(family)
    if not fam:
        return False
    gl = (genre_name or "").lower()
    if not any(m.lower() in gl for m in fam.get("match", [])):
        return False
    lo, hi = fam.get("bpm", [0, 999])
    return lo <= bpm <= hi


def tag_id(cfg: dict, role: str):
    """MyTag ID configured for a role ('vocal', 'energy_low', ...). None if unmapped."""
    v = (cfg.get("tags") or {}).get(role)
    return str(v) if v else None


async def open_db(cfg: dict):
    """Connected RekordboxDatabase honoring an explicit database_dir when set."""
    from rekordbox_mcp.database import RekordboxDatabase

    d = RekordboxDatabase()
    await d.connect(cfg.get("database_dir") or None)
    return d
