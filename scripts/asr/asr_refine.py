"""Re-transcribe selected Chinese clips one by one (no window packing).

Window packing is fast but Whisper's word timestamps can leak the first word of
the next clip into the current one. Clips whose text looks truncated (English
line finished, Chinese line not) are re-decoded in isolation, which removes the
leak entirely. A replacement is only accepted when it is plausible.
"""
import argparse
import csv
import json
import os
import re
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import s2v_config  # noqa: E402

END = "。！？…!?~"
ROOT = s2v_config.DATASET_DIR


def looks_finished(text):
    return bool(text) and text[-1] in END


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=ROOT)
    ap.add_argument("--model", default=s2v_config.WHISPER_MODEL)
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--shard", default="0/1")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    meta = os.path.join(a.root, "metadata")
    rows = list(csv.DictReader(open(os.path.join(meta, "darkwillow_dataset.csv"),
                                    encoding="utf-8-sig")))
    targets = [r for r in rows
               if r["language"] == "schinese" and r["text"].strip()
               and r["text_en_reference"].strip()
               and r["text_en_reference"].strip()[-1] in ".!?"
               and not looks_finished(r["text"].strip())]
    si, sn = (int(x) for x in a.shard.split("/"))
    targets = [r for i, r in enumerate(targets) if i % sn == si]
    if a.limit:
        targets = targets[:a.limit]
    print("flagged clips in this shard: %d" % len(targets))
    if a.dry_run:
        for r in targets[:15]:
            print("  %-28s ZH=%s | EN=%s" % (r["filename"], r["text"], r["text_en_reference"]))
        return

    from faster_whisper import WhisperModel
    model = WhisperModel(a.model, device="cpu", compute_type="int8", cpu_threads=a.threads)
    out_path = os.path.join(meta, "asr_iso%d.json" % si)
    out = json.load(open(out_path, encoding="utf-8")) if os.path.exists(out_path) else {}

    t0 = time.time()
    changed = 0
    for i, r in enumerate(targets, 1):
        fn = r["filename"]
        if fn in out:
            continue
        wav = os.path.join(a.root, r["wav"].replace("/", os.sep))
        segs, _ = model.transcribe(wav, language="zh", task="transcribe", beam_size=1,
                                   temperature=0.0, condition_on_previous_text=False,
                                   vad_filter=False)
        new = "".join(s.text for s in segs).strip()
        old = r["text"].strip()
        # accept only plausible replacements
        if not new:
            new = old
        elif len(new) > len(old) * 1.6 or len(new) < max(1, len(old) * 0.4):
            new = old
        out[fn] = {"old": old, "new": new}
        if new != old:
            changed += 1
        if i % 20 == 0 or i == len(targets):
            print("  %d/%d  changed=%d  %.1f min" % (i, len(targets), changed, (time.time() - t0) / 60),
                  flush=True)
            json.dump(out, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(out, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("shard %d done: %d processed, %d changed" % (si, len(out), changed))


if __name__ == "__main__":
    main()
