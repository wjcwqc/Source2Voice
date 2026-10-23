"""Chinese ASR for the Dark Willow dataset (batched, concatenation strategy).

Valve ships no Simplified-Chinese subtitle file for Dark Willow, so Chinese
transcripts are produced with Whisper large-v3 (faster-whisper / CTranslate2).

Why concatenate: Whisper always encodes a fixed 30 s window, so transcribing
2400 one-to-three-second clips one by one wastes ~95 % of the compute. Clips are
therefore concatenated (1 s of silence between them) into ~8 minute chunks and
transcribed with `BatchedInferencePipeline`; the returned segment timestamps are
then mapped back onto the individual clips.

Resumable: per-chunk results are cached in metadata/asr_cache.json.
"""
import argparse
import json
import os
import re
import time
import wave
from difflib import SequenceMatcher
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import s2v_config  # noqa: E402

SR = 32000
GAP_SEC = 1.0


def norm_en(s):
    s = re.sub(r"[^a-z0-9 ]+", " ", s.lower())
    return " ".join(s.split())


def similarity(a, b):
    return SequenceMatcher(None, norm_en(a), norm_en(b)).ratio()


def build_chunks(entries, root, tmp_dir, max_sec=480):
    """Yield (chunk_wav, [(filename, start, end), ...])."""
    os.makedirs(tmp_dir, exist_ok=True)
    chunk, spans, pos = [], [], 0.0
    for e in entries:
        with wave.open(os.path.join(root, e["wav"])) as r:
            dur = r.getnframes() / r.getframerate()
        if spans and pos + dur > max_sec:
            yield chunk, spans
            chunk, spans, pos = [], [], 0.0
        chunk.append(e)
        spans.append((e["filename"], pos, pos + dur))
        pos += dur + GAP_SEC
    if chunk:
        yield chunk, spans


def write_chunk(entries, spans, out_path):
    with wave.open(out_path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        for e, (_, s, t) in zip(entries, spans):
            with wave.open(e["_abs"], "rb") as r:
                w.writeframes(r.readframes(r.getnframes()))
            gap = int(round((t - s) + GAP_SEC)) * SR - int(round((t - s) * SR))
            w.writeframes(b"\x00" * gap * 2)


def assign(spans, segments):
    """Map timed segments onto clip spans by segment midpoint."""
    out = {}
    for start, end, text in segments:
        mid = (start + end) / 2
        best = None
        for name, s, t in spans:
            if s <= mid <= t:
                best = name
                break
            if mid < s:
                d = s - mid
            elif mid > t:
                d = mid - t
            else:
                d = 0
            if d <= GAP_SEC / 2 and (best is None or d < best[1]):
                best = (name, d)
                break
        if isinstance(best, tuple):
            best = best[0]
        if best:
            out.setdefault(best, []).append(text.strip())
    return {k: " ".join(v).strip() for k, v in out.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=s2v_config.DATASET_DIR)
    ap.add_argument("--model", default=s2v_config.WHISPER_MODEL)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--chunk-sec", type=int, default=480)
    ap.add_argument("--threads", type=int, default=16)
    ap.add_argument("--group", default=None)
    ap.add_argument("--tmp", default=s2v_config.ASR_TMP)
    a = ap.parse_args()

    meta = os.path.join(a.root, "metadata")
    manifest = json.load(open(os.path.join(meta, "manifest.json"), encoding="utf-8"))
    for e in manifest:
        e["_abs"] = os.path.join(a.root, e["wav"])

    cache_path = os.path.join(meta, "asr_cache.json")
    cache = json.load(open(cache_path, encoding="utf-8")) if os.path.exists(cache_path) else {}

    targets = [e for e in manifest if e["language"] == "schinese"
               and (not a.group or e["group"] == a.group)]
    targets.sort(key=lambda e: (e["group"], e["filename"]))
    missing = [e for e in targets if e["filename"] not in cache]
    print("zh clips %d | cached %d | todo %d" % (len(targets), len(targets) - len(missing), len(missing)))

    if missing:
        from faster_whisper import BatchedInferencePipeline, WhisperModel
        model = WhisperModel(a.model, device="cpu", compute_type="int8", cpu_threads=a.threads)
        bp = BatchedInferencePipeline(model=model)

        chunks = list(build_chunks(missing, a.root, a.tmp, a.chunk_sec))
        print("chunks: %d" % len(chunks))
        t0 = time.time()
        for ci, (entries, spans) in enumerate(chunks, 1):
            wav = os.path.join(a.tmp, "chunk_%03d.wav" % ci)
            write_chunk(entries, spans, wav)
            segs, _ = bp.transcribe(wav, language="zh", batch_size=a.batch_size,
                                    beam_size=1, vad_filter=True)
            got = assign(spans, [(s.start, s.end, s.text) for s in segs])
            for name, _, _ in spans:
                cache[name] = got.get(name, "")
            os.remove(wav)
            el = time.time() - t0
            done = sum(1 for e in missing if e["filename"] in cache)
            print("  chunk %d/%d  clips %d/%d  %.1f min elapsed"
                  % (ci, len(chunks), done, len(missing), el / 60), flush=True)
            json.dump(cache, open(cache_path, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)

        # slow-path retry for clips the VAD dropped
        empty = [e for e in missing if not cache.get(e["filename"], "").strip()]
        print("clips without text after batch pass: %d" % len(empty))
        for i, e in enumerate(empty, 1):
            segs, _ = model.transcribe(e["_abs"], language="zh", task="transcribe",
                                       beam_size=1, temperature=0.0,
                                       condition_on_previous_text=False, vad_filter=False)
            cache[e["filename"]] = "".join(s.text for s in segs).strip()
            if i % 25 == 0:
                print("   retry %d/%d" % (i, len(empty)), flush=True)
                json.dump(cache, open(cache_path, "w", encoding="utf-8"),
                          ensure_ascii=False, indent=1)
        json.dump(cache, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("done in %.1f min" % ((time.time() - t0) / 60))

    filled = sum(1 for e in targets if cache.get(e["filename"], "").strip())
    print("zh clips with text: %d / %d" % (filled, len(targets)))


if __name__ == "__main__":
    main()
