"""Source2Voice · 阶段 3：把清洗后的台词清单分桶成可训练数据集。

设计原则
--------
1. 原始音频和原始清单只读，绝不覆盖；输出到新的 D 盘 data 目录。
2. 响度统一不是把异常样本硬删掉：每条都写入 report.csv，分为 core/style/review 三桶。
3. "过分语气"只做保守标记（感叹/重复/语气词/声学离群），不把表达性样本直接丢掉。
   core 用于先训音色；style 作为后续语气增强候选；review 需人工听审。
4. 输出 Kaldi 格式（wav.scp/text/utt2spk/spk2utt/instruct），
   训练侧用 bucket_to_list.py 转成 GPT-SoVITS .list。

输入格式（GPT-SoVITS 风格 .list，每行）:
    <audio_path>|<speaker>|<lang>|<text>

示例
----
    # 中文（Dota 2）
    python refine_dataset.py \
        --input "$DATASET/metadata/schinese_dark_willow_vo_pure.list" \
        --out "$WORK/clean_dataset" --langs zh

    # 英文（Deadlock）
    python refine_dataset.py \
        --input "$DATASET/metadata/english_paige_vo.list" \
        --out "$WORK/clean_dataset_paige" --speaker paige --langs en
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sys
from collections import Counter, defaultdict

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import s2v_config  # noqa: E402

DEFAULT_INPUT = os.path.join(s2v_config.META_DIR, "schinese_dark_willow_vo_pure.list")
DEFAULT_OUT = os.path.join(s2v_config.WORK, "clean_dataset")

# 只用于标记 review/style，不用于盲目删除。中文台词中这些字也可能是正常内容。
INTERJECTIONS = set("啊哎嘿哈哼喂哦呀呃嗯呵嘶哇喔诶")
# 英文感叹词（按词边界匹配，避免把 "oh" 命中 "another"）
INTERJECTION_WORDS = re.compile(
    r"\b(oh|ah|hey|hi|wow|ugh|hm|mm|eh|ahh|whoa|gosh|damn|yeah|yep|"
    r"oops|ow|argh|hah|ha|heh|hooray|alas|nope|yikes)\b", re.I)
RE_REPEAT = re.compile(r"(.)\1{2,}")
RE_PUNCT_BURST = re.compile(r"[!?！？]{2,}")
RE_WS = re.compile(r"\s+")


def load_rows(paths: list[str], langs: set[str] | None = None,
              default_speaker: str = "speaker") -> list[dict]:
    rows = []
    for path in paths:
        with open(path, encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line = line.rstrip("\n")
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                parts = line.split("|", 3)
                if len(parts) >= 4:
                    wav, speaker, lang, text = parts
                elif len(parts) == 2:
                    wav, text = parts
                    speaker, lang = default_speaker, "zh"
                else:
                    continue
                if langs and lang.strip() not in langs:
                    continue
                text = text.strip()
                if not text or not os.path.exists(wav.strip()):
                    continue
                group = "vo"
                low = wav.replace("\\", "/").lower()
                if "announcer_killing_spree" in low:
                    group = "announcer_killing_spree"
                elif "/announcer/" in low:
                    group = "announcer"
                stem = os.path.splitext(os.path.basename(wav))[0]
                rows.append({
                    "src": os.path.abspath(wav.strip()),
                    "speaker": speaker.strip() or default_speaker,
                    "lang": lang.strip(),
                    "text": text,
                    "group": group,
                    "stem": stem,
                    "source_list": os.path.abspath(path),
                    "source_line": line_no,
                })
    return rows


def trim_silence(x: np.ndarray, sr: int, thresh_db: float = -45.0,
                 pad: float = 0.05) -> np.ndarray:
    if x.size == 0:
        return x
    thr = 10 ** (thresh_db / 20.0)
    win = max(1, int(sr * 0.01))
    n = x.size // win * win
    if n == 0:
        return x
    env = np.abs(x[:n]).reshape(-1, win).max(axis=1)
    loud = np.flatnonzero(env > thr)
    if loud.size == 0:
        return x
    pad_n = int(sr * pad)
    a = max(0, int(loud[0]) * win - pad_n)
    b = min(x.size, (int(loud[-1]) + 1) * win + pad_n)
    return x[a:b]


def normalize(x: np.ndarray, target_db: float, peak_db: float) -> np.ndarray:
    if not x.size:
        return x.astype(np.float32)
    rms = float(np.sqrt(np.mean(x.astype(np.float64) ** 2)) + 1e-12)
    x = x * (10 ** (target_db / 20.0) / rms)
    peak = float(np.max(np.abs(x)) + 1e-12)
    limit = 10 ** (peak_db / 20.0)
    if peak > limit:
        x = x * (limit / peak)
    return x.astype(np.float32)


def read_mono(path: str):
    x, sr = sf.read(path, dtype="float32", always_2d=False)
    if x.ndim > 1:
        x = x.mean(axis=1)
    return np.asarray(x, dtype=np.float32), int(sr)


def robust_bounds(values: np.ndarray):
    med = float(np.median(values))
    mad = float(np.median(np.abs(values - med)))
    if mad > 1e-5:
        return med - 5.0 * 1.4826 * mad, med + 5.0 * 1.4826 * mad
    return float(np.percentile(values, 1)), float(np.percentile(values, 99))


def text_flags(text: str) -> list[str]:
    flags = []
    if RE_PUNCT_BURST.search(text):
        flags.append("punct_burst")
    if RE_REPEAT.search(text):
        flags.append("text_repeat")
    if any(ch in INTERJECTIONS for ch in text[:4]):
        flags.append("leading_interjection")
    if any(ch in INTERJECTIONS for ch in text):
        flags.append("interjection")
    m = INTERJECTION_WORDS.search(text)
    if m:
        flags.append("interjection")
        if m.start() <= 4:
            flags.append("leading_interjection")
    if "!" in text or "！" in text:
        flags.append("exclaim")
    return flags

def make_bucket(flags: list[str], audio_outlier: bool, clipped: bool) -> str:
    # 音频异常优先 review；表达性但声学正常的样本进入 style。
    if audio_outlier or clipped:
        return "review"
    if flags:
        return "style"
    return "core"


def percentile_text(a: np.ndarray, p: float) -> float:
    return float(np.percentile(a, p)) if a.size else 0.0


def write_kaldi_bucket(bucket_dir: str, items: list[dict], speaker: str,
                       instruction: str, clean_output: bool = False) -> None:
    # 默认不删除任何文件；需要重建同一输出目录时显式传 --clean-output。
    # 这样即使误把 out 指到了别处，也不会发生静默批量删除。
    if clean_output and os.path.isdir(bucket_dir):
        shutil.rmtree(bucket_dir)
    os.makedirs(os.path.join(bucket_dir, "wavs"), exist_ok=True)
    utts = []
    for item in items:
        utt = item["utt"]
        dst = os.path.join(bucket_dir, "wavs", utt + ".wav")
        x, src_sr = read_mono(item["src"])
        x = trim_silence(x, src_sr)
        if src_sr != item["target_sr"]:
            g = np.gcd(src_sr, item["target_sr"])
            x = resample_poly(x, item["target_sr"] // g, src_sr // g).astype(np.float32)
        x = normalize(x, item["target_db"], item["peak_db"])
        sf.write(dst, x, item["target_sr"], subtype="PCM_16")
        item["dst"] = dst.replace("\\", "/")
        item["out_seconds"] = round(len(x) / item["target_sr"], 4)
        utts.append(utt)

    def dump(name: str, lines: list[str]):
        with open(os.path.join(bucket_dir, name), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + ("\n" if lines else ""))

    dump("wav.scp", [f"{i['utt']} {i['dst']}" for i in items])
    dump("text", [f"{i['utt']} {i['text']}" for i in items])
    dump("utt2spk", [f"{i['utt']} {speaker}" for i in items])
    dump("spk2utt", [f"{speaker} " + " ".join(utts)] if utts else [])
    dump("instruct", [f"{i['utt']} {instruction}" for i in items])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", nargs="+", default=[DEFAULT_INPUT])
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--target-sr", type=int, default=22050,
                    help="CosyVoice 官方基础配置为 22050 Hz")
    ap.add_argument("--target-db", type=float, default=-20.0)
    ap.add_argument("--peak-db", type=float, default=-1.0)
    ap.add_argument("--min-seconds", type=float, default=0.8)
    ap.add_argument("--max-seconds", type=float, default=11.0)
    ap.add_argument("--speaker", default=None,
                    help="utt2spk 里的说话人标签；默认取清单第一行的 speaker")
    ap.add_argument("--langs", default=None,
                    help="逗号分隔的语言过滤（默认不过滤）")
    ap.add_argument("--instruction", default=None,
                    help="instruct 文本；默认按语言自动生成")
    ap.add_argument("--clean-output", action="store_true",
                    help="显式清理本脚本输出目录中的旧 bucket；默认不删除任何文件")
    a = ap.parse_args()

    langs = set(x.strip() for x in a.langs.split(",")) if a.langs else None
    rows = load_rows(a.input, langs=langs)
    if not rows:
        raise SystemExit("没有找到可用样本（检查 --input / --langs）")

    speaker = a.speaker or rows[0]["speaker"]
    # 指令文本按语种给默认模板，--instruction 可覆盖
    lang_of = rows[0]["lang"]
    default_instruction = ("英文游戏角色台词，语气自然，清晰发音"
                           if lang_of.startswith("en") else
                           "中文游戏角色台词，语气自然，清晰发音")
    instruction = a.instruction or default_instruction

    # 同一清单若重复输入，不按路径重复写入；同文本重复保留并标记，避免悄悄改变语料。
    seen_paths = set()
    uniq = []
    for r in rows:
        if r["src"] not in seen_paths:
            seen_paths.add(r["src"])
            uniq.append(r)
    rows = uniq

    features = []
    for r in rows:
        x, sr = read_mono(r["src"])
        rms = float(np.sqrt(np.mean(x.astype(np.float64) ** 2)) + 1e-12)
        rms_db = 20.0 * np.log10(rms)
        peak = float(np.max(np.abs(x))) if x.size else 0.0
        clip_frac = float(np.mean(np.abs(x) >= 0.999)) if x.size else 0.0
        zcr = float(np.mean((x[:-1] * x[1:]) < 0)) if len(x) > 1 else 0.0
        r.update({"src_sr": sr, "src_seconds": len(x) / sr,
                  "rms_db": rms_db, "peak": peak,
                  "clip_frac": clip_frac, "zcr": zcr})
        features.append(r)

    loud = np.asarray([r["rms_db"] for r in features], dtype=np.float64)
    duration = np.asarray([r["src_seconds"] for r in features], dtype=np.float64)
    # 不同录音包的母带增益可能不同：按 group 做响度离群判定，不能让整个 announcer 包
    # 因为和 vo 的整体增益不同而全部被误判为 review。
    group_bounds = {}
    for group in sorted({r["group"] for r in features}):
        vals = np.asarray([r["rms_db"] for r in features if r["group"] == group], dtype=np.float64)
        group_bounds[group] = robust_bounds(vals)
    lo, hi = robust_bounds(loud)
    out = []
    duplicate_text = Counter(RE_WS.sub("", r["text"]) for r in features)
    for idx, r in enumerate(features):
        flags = text_flags(r["text"])
        if r["group"] != "vo":
            flags.append("source_style")
        group_lo, group_hi = group_bounds[r["group"]]
        audio_outlier = bool(r["rms_db"] < group_lo or r["rms_db"] > group_hi or
                             r["src_seconds"] < a.min_seconds or
                             r["src_seconds"] > a.max_seconds)
        clipped = bool(r["clip_frac"] > 0.0002)
        if duplicate_text[RE_WS.sub("", r["text"])] > 1:
            flags.append("duplicate_text")
        bucket = make_bucket(flags, audio_outlier, clipped)
        # 只有输入名、序号、hash 组成 utt，保证跨 group 不碰撞。
        digest = hashlib.sha1(r["src"].encode("utf-8")).hexdigest()[:8]
        r.update({"flags": ",".join(sorted(set(flags))),
                  "audio_outlier": int(audio_outlier), "clipped": int(clipped),
                  "bucket": bucket, "utt": f"spk_{idx:04d}_{digest}",
                  "target_sr": a.target_sr, "target_db": a.target_db,
                  "peak_db": a.peak_db})
        out.append(r)

    os.makedirs(a.out, exist_ok=True)
    report_path = os.path.join(a.out, "report.csv")
    fields = ["utt", "src", "group", "text", "src_sr", "src_seconds", "rms_db",
              "peak", "clip_frac", "zcr", "flags", "audio_outlier", "clipped", "bucket"]
    with open(report_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in out:
            w.writerow({k: r.get(k, "") for k in fields})

    buckets = defaultdict(list)
    for r in out:
        buckets[r["bucket"]].append(r)
    style_instruction = instruction.replace("语气自然", "保留原始表达性语气")
    review_instruction = instruction.replace("语气自然", "需人工复听确认")
    for bucket, bucket_instruction in (("core", instruction),
                                       ("style", style_instruction),
                                       ("review", review_instruction)):
        write_kaldi_bucket(os.path.join(a.out, bucket), buckets[bucket],
                           speaker, bucket_instruction, clean_output=a.clean_output)

    # 固定验证集：按 utt 的稳定 hash 选 20 条，避免每次运行随机漂移。
    # core/style 分开，style 只用于语气泛化验收，不应混进首轮训练。
    for bucket, n in (("core", 20), ("style", 20)):
        candidates = sorted(buckets[bucket], key=lambda x: x["utt"])
        chosen = candidates[:min(n, len(candidates))]
        with open(os.path.join(a.out, "validation_%s.txt" % bucket), "w", encoding="utf-8") as f:
            for item in chosen:
                f.write("%s\t%s\t%s\n" % (item["utt"], item.get("dst", ""), item["text"]))

    summary = {
        "input": [os.path.abspath(p) for p in a.input],
        "output": os.path.abspath(a.out),
        "target_sample_rate": a.target_sr,
        "target_rms_db": a.target_db,
        "peak_limit_db": a.peak_db,
        "source_clips": len(out),
        "source_hours": round(float(np.sum(duration)) / 3600.0, 3),
        "rms_db": {"p01": percentile_text(loud, 1), "median": percentile_text(loud, 50),
                   "p99": percentile_text(loud, 99), "robust_lo": lo, "robust_hi": hi,
                   "group_bounds": {g: {"lo": b[0], "hi": b[1]}
                                    for g, b in sorted(group_bounds.items())}},
        "buckets": {k: len(v) for k, v in sorted(buckets.items())},
        "flag_counts": dict(Counter(flag for r in out for flag in r["flags"].split(",") if flag)),
        "duplicate_text_rows": sum(1 for r in out if "duplicate_text" in r["flags"]),
        "note": "原始文件只读；core/style/review 均为新输出，review 不应直接用于首轮训练。",
    }
    with open(os.path.join(a.out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    with open(os.path.join(a.out, "README.md"), "w", encoding="utf-8") as f:
        f.write("# %s 精修数据集\n\n" % speaker)
        f.write("本目录由 `scripts/clean/refine_dataset.py` 生成。原始 WAV 和原始清单未被修改。\n\n")
        f.write("- `core/`：保守音色训练集，优先用于首轮训练\n")
        f.write("- `style/`：感叹/语气词/重复文本/播音包等表达性候选，先做验证再混入\n")
        f.write("- `review/`：组内响度/时长/削波离群，需人工复听，不要直接训练\n")
        f.write("- `report.csv`：每条样本的响度、峰值、削波、过零率、标记原因\n")
        f.write("- `summary.json`：统计摘要\n\n")
        f.write("CosyVoice 官方数据准备阶段需要 `wav.scp`、`text`、`utt2spk`、`spk2utt`；\n")
        f.write("每个桶已生成这些文件及 `instruct`。\n")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\n输出：%s" % os.path.abspath(a.out))


if __name__ == "__main__":
    main()
