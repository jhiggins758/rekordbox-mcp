"""Demucs vocal-stem extraction for a genre family (resumable JSONL).

Separates the vocal stem on 3 windows per track and records vocal energy + activity
fraction, later classified by vocal_calibrate.py. Slow (~15-20s/track on CPU) but
resumable — re-runs only process new tracks.

    uv run --with demucs --with librosa --with soundfile --with numpy \\
        python toolkit/vocal_extract.py [--family primary|secondary]   (default primary)

Output: workspace/vocal_features_<family>.jsonl
"""
import os, sys, json, time, asyncio, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
import numpy as np, librosa, torch
from demucs.pretrained import get_model
from demucs.apply import apply_model
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))
from djtk_config import load_config, open_db, workspace, genre_match, tag_id
from pyrekordbox.db6 import tables

CFG = load_config()
FAMILY = "secondary" if "--family" in sys.argv and "secondary" in sys.argv else "primary"
OUT = str(workspace(CFG, f"vocal_features_{FAMILY}.jsonl"))
ROOTS = [str(Path(r).expanduser()) for r in (CFG.get("music_roots") or [])]
EXTS = (".mp3",".wav",".flac",".m4a",".aif",".aiff")

print("loading htdemucs...", flush=True)
model = get_model("htdemucs"); model.eval()
SR = model.samplerate; VI = list(model.sources).index("vocals")
torch.set_num_threads(max(1, (os.cpu_count() or 4)))

def vocal_feats(path, length):
    L = length or 200
    ve=[]; vf=[]
    for frac in (0.25, 0.50, 0.72):                    # 3 windows -> whole-track density
        off = L*frac
        if off + 15 > L: continue
        try:
            y, sr = librosa.load(path, sr=SR, offset=off, duration=14.0, mono=False)
        except Exception:
            continue
        if y.size < sr: continue
        if y.ndim == 1: y = np.stack([y, y])
        wav = torch.tensor(y, dtype=torch.float32)[None]
        with torch.no_grad():
            stems = apply_model(model, wav, device="cpu", shifts=0, split=True, overlap=0.1)[0]
        vocal = stems[VI].mean(0).numpy(); mix = wav[0].mean(0).numpy()
        ve.append(float((vocal**2).sum()/((mix**2).sum()+1e-9)))
        hop = SR//2
        vr = librosa.feature.rms(y=vocal, frame_length=SR, hop_length=hop)[0]
        mr = librosa.feature.rms(y=mix, frame_length=SR, hop_length=hop)[0]
        vf.append(float(((vr/(mr+1e-9))>0.15).mean()))
    if not ve: return None
    return float(np.mean(ve)), float(np.mean(vf))

async def main():
    d = await open_db(CFG)
    active = [c for c in d.db.get_content() if getattr(c,"rb_local_deleted",0)==0]
    vtag = tag_id(CFG, "vocal")
    voc_tagged = set()
    if vtag:
        for s in d.db.query(tables.DjmdSongMyTag):
            if getattr(s,"rb_local_deleted",0)==0 and str(s.MyTagID)==vtag:
                voc_tagged.add(str(s.ContentID))
    dnb = [c for c in active
           if genre_match(CFG, FAMILY, getattr(getattr(c,'Genre',None),'Name','') or '', (c.BPM or 0)/100.0)]

    fidx={}
    for root in ROOTS:
        if os.path.exists(root):
            for dp,_,files in os.walk(root):
                for f in files:
                    if f.lower().endswith(EXTS): fidx.setdefault(f.lower(), os.path.join(dp,f))
    def resolve(c):
        fp=c.FolderPath or ""; return fp if os.path.exists(fp) else fidx.get(os.path.basename(fp.replace("\\","/")).lower())

    done=set()
    if os.path.exists(OUT):
        for line in open(OUT,encoding="utf-8"):
            try: done.add(json.loads(line)["id"])
            except Exception: pass
    print(f"{FAMILY} tracks: {len(dnb)} | already done: {len(done)} | Vocal-tagged: {len(voc_tagged)}", flush=True)

    fh=open(OUT,"a",encoding="utf-8"); ok=skip=fail=0; t0=time.time()
    for c in dnb:
        if str(c.ID) in done: continue
        path=resolve(c)
        if not path or not os.path.exists(path): skip+=1; continue
        try:
            r=vocal_feats(path, c.Length)
            if not r: skip+=1; continue
            fh.write(json.dumps({"id":str(c.ID),"title":c.Title or "",
                                 "artist":getattr(getattr(c,'Artist',None),'Name','') or "",
                                 "voc_energy":round(r[0],4),"voc_frac":round(r[1],3),
                                 "tagged_vocal":str(c.ID) in voc_tagged},ensure_ascii=False)+"\n")
            fh.flush(); ok+=1
        except Exception: fail+=1
        if ok and ok%25==0:
            el=time.time()-t0; rate=el/ok
            print(f"  {ok} done ({skip} skip, {fail} fail) | {rate:.1f}s/trk | ETA {rate*(len(dnb)-len(done)-ok)/3600:.1f}h", flush=True)
    fh.close()
    print(f"\nDONE: extracted {ok}, skipped {skip}, failed {fail}", flush=True)
    await d.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
