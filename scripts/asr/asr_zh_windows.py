"""Chinese ASR for the Dark Willow dataset.

Valve ships no Simplified-Chinese subtitle file for Dark Willow, so the Chinese
transcripts are produced with Whisper (faster-whisper / CTranslate2).

Why windows
-----------
Whisper always encodes a fixed 30 s window, so transcribing thousands of 1-3 s
clips one by one wastes ~95 % of the compute. Clips are therefore packed into
~28 s windows separated by short silences, each window is decoded with
`word_timestamps=True`, and every word is mapped back onto the clip whose time
span contains the word midpoint.

Parallel shards
---------------
The window list is built once from the *global* pending set and stored in
`asr_plan.json`; every shard then reads that same plan and takes windows
`i % N == shard`. Building windows independently per shard would silently drop
clips (different pending sets -> different window boundaries).

Usage
-----
  python asr_zh_windows.py --plan                     # build asr_plan.json
  python asr_zh_windows.py --shard 0/3                # one shard
  python asr_zh_windows.py --retry-empty              # slow-path retry, global
"""
import argparse
import json
import os
import time
import wave
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import s2v_config  # noqa: E402

SR = 32000
GAP_SEC = 0.8
WIN_SEC = 28.0
PLAN = "asr_plan.json"


def clip_seconds(path):
    with wave.open(path) as r:
        return r.getnframes() / r.getframerate()


def build_windows(entries, win=WIN_SEC, gap=GAP_SEC):
    groups, cur, acc = [], [], 0.0
    for e in entries:
        d = e["_dur"]
        if cur and acc + d > win:
            groups.append(cur)
            cur, acc = [], 0.0
        cur.append(e)
        acc += d + gap
    if cur:
        groups.append(cur)
    return groups


def render_window(group, out_path, gap=GAP_SEC):
    spans, pos = [], 0
    gap_n = int(round(gap * SR))
    with wave.open(out_path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        for e in group:
            with wave.open(e["_abs"]) as r:
                n = r.getnframes()
                w.writeframes(r.readframes(n))
            spans.append((e["filename"], pos / SR, (pos + n) / SR))
            w.writeframes(b"\x00" * gap_n * 2)
            pos += n + gap_n
    return spans


def assign(spans, segments, gap=GAP_SEC):
    got = {}
    for s in segments:
        for wd in (s.words or []):
            mid = (wd.start + wd.end) / 2
            for name, a, b in spans:
                if a - gap / 2 <= mid <= b + gap / 2:
                    got.setdefault(name, []).append(wd.word.strip())
                    break
    return {k: "".join(v).strip() for k, v in got.items()}


def load_state(args):
    meta = os.path.join(args.root, "metadata")
    manifest = json.load(open(os.path.join(meta, "manifest.json"), encoding="utf-8"))
    for e in manifest:
        e["_abs"] = os.path.join(args.root, e["wav"])
    cache_path = os.path.join(meta, "asr_cache.json")
    cache = json.load(open(cache_path, encoding="utf-8")) if os.path.exists(cache_path) else {}
    targets = [e for e in manifest if e["language"] == "schinese"
               and (not args.group or e["group"] == args.group)]
    targets.sort(key=lambda e: (e["group"], e["filename"]))
    return meta, targets, cache


def do_plan(args):
    meta, targets, cache = load_state(args)
    pending = [e for e in targets if e["filename"] not in cache]
    for e in pending:
        e["_dur"] = clip_seconds(e["_abs"])
    windows = [[e["filename"] for e in g] for g in build_windows(pending)]
    p = os.path.join(meta, PLAN)
    json.dump(windows, open(p, "w", encoding="utf-8"), ensure_ascii=False)
    print("plan: %d clips pending -> %d windows -> %s" % (len(pending), len(windows), p))


def do_shard(args):
    shard_i, shard_n = (int(x) for x in args.shard.split("/"))
    meta, targets, cache = load_state(args)
    by_name = {e["filename"]: e for e in targets}
    plan = json.load(open(os.path.join(meta, PLAN), encoding="utf-8"))
    windows = [w for i, w in enumerate(plan) if i % shard_n == shard_i]
    if args.limit:
        windows = windows[:args.limit]
    print("shard %d/%d: %d windows" % (shard_i, shard_n, len(windows)), flush=True)
    if not windows:
        return

    from faster_whisper import WhisperModel
    model = WhisperModel(args.model, device="cpu", compute_type="int8", cpu_threads=args.threads)
    os.makedirs(args.tmp, exist_ok=True)
    win_path = os.path.join(args.tmp, "w%d.wav" % shard_i)
    cache_name = "asr_cache.part%d.json" % shard_i
    cache_path = os.path.join(meta, cache_name)
    done = json.load(open(cache_path, encoding="utf-8")) if os.path.exists(cache_path) else {}
    seed = {k: cache[k] for k in cache}

    t0 = time.time()
    audio = 0.0
    for wi, names in enumerate(windows, 1):
        group = [by_name[n] for n in names if n in by_name]
        if not group:
            continue
        spans = render_window(group, win_path)
        audio += spans[-1][2]
        segs, _ = model.transcribe(win_path, language="zh", task="transcribe",
                                   beam_size=1, temperature=0.0,
                                   condition_on_previous_text=False,
                                   word_timestamps=True, vad_filter=False)
        got = assign(spans, list(segs))
        for name, _, _ in spans:
            done[name] = got.get(name, "")
        if wi % 5 == 0 or wi == len(windows):
            el = time.time() - t0
            print("  window %d/%d  %.1f min  (%.2fx rt)"
                  % (wi, len(windows), el / 60, audio / el), flush=True)
            json.dump(done, open(cache_path, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
    json.dump(done, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("shard %d done: %d clips" % (shard_i, len(done)), flush=True)


def do_retry_empty(args):
    """Global slow path: transcribe individually the clips that got no words."""
    meta, targets, cache = load_state(args)
    empty = [e for e in targets if not cache.get(e["filename"], "").strip()]
    shard_i, shard_n = (int(x) for x in (args.shard or "0/1").split("/"))
    if shard_n > 1:
        empty = [e for i, e in enumerate(empty) if i % shard_n == shard_i]
    print("clips with empty text: %d (shard %d/%d)" % (len(empty), shard_i, shard_n))
    if not empty:
        return
    from faster_whisper import WhisperModel
    model = WhisperModel(args.model, device="cpu", compute_type="int8", cpu_threads=args.threads)
    path = os.path.join(meta, "asr_retry%d.json" % shard_i)
    out = {}
    for i, e in enumerate(empty, 1):
        segs, _ = model.transcribe(e["_abs"], language="zh", task="transcribe",
                                   beam_size=1, temperature=0.0,
                                   condition_on_previous_text=False, vad_filter=False)
        out[e["filename"]] = "".join(s.text for s in segs).strip()
        if i % 10 == 0 or i == len(empty):
            print("  retry %d/%d" % (i, len(empty)), flush=True)
            json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("retry shard %d done" % shard_i)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=s2v_config.DATASET_DIR)
    ap.add_argument("--model", default=s2v_config.WHISPER_MODEL)
    ap.add_argument("--threads", type=int, default=16)
    ap.add_argument("--group", default=None)
    ap.add_argument("--tmp", default=s2v_config.ASR_TMP)
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--shard", default=None)
    ap.add_argument("--retry-empty", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    if a.plan:
        do_plan(a)
    elif a.retry_empty:
        do_retry_empty(a)
    elif a.shard:
        do_shard(a)
    else:
        ap.error("pass --plan, --shard i/N or --retry-empty")


if __name__ == "__main__":
    main()
