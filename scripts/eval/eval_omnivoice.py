#!/usr/bin/env python3
"""Source2Voice · 阶段 6a：评估微调后的 OmniVoice checkpoint。

对每个 checkpoint 目录（<ckpt_root>/ckpt-*）：
  - CER：用 whisper 转写生成音频，与目标文本做字符级编辑距离（归一化后）。
  - 说话人相似度：用 campplus 提取嵌入，与该英雄**留出**真人片段算余弦相似度。

输出跨 checkpoint 与生成模式（ref = 带参考音频，noref = 纯文本）的对比表。

关键指标解读
------------
CER 越低越好；相似度要看**真人片段之间的互相相似度基线**——
生成相似度超过基线才说明音色真的学会了（基线因英雄/录音条件而异，
本项目邪影芳灵实测基线 0.644）。

用法
----
    python eval_omnivoice.py \
        --ckpt_root  <work>/out/omnivoice_paige \
        --real_dir   <dataset>/english/paige/vo \
        --real_glob  "*.wav" \
        --texts      <work>/eval_texts_paige.json \
        --lang en

--texts 是 JSON：{"t01": "第一句台词", ...}
--real_dir + --real_glob 用于挑留出的真人片段（**不能出现在训练清单里**）。

ASR 后端
--------
本脚本支持两种转写后端，按 `--asr_backend auto` 自动探测（优先 whisper，
没有则用 faster_whisper）：

  - `whisper`        : OpenAI whisper (`import whisper`)，包名 `openai-whisper`
  - `faster_whisper` : faster-whisper (`from faster_whisper import WhisperModel`)

两者都装不上时会给出明确的安装提示，而不是抛 ModuleNotFoundError。
Windows 上 openai-whisper 依赖较重（含 numba/triton 链），faster-whisper
通常更省事。
"""
import argparse
import glob as globmod
import json
import os
import re
import sys

import numpy as np
import soundfile as sf
import torch
import torchaudio
import torchaudio.compliance.kaldi as kaldi

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import s2v_config  # noqa: E402

BASE = s2v_config.CAMPPLUS

PUNCT = re.compile(r"""[\s,.!?;:'",\u3002\uff01\uff1f\uff1b\uff1a"\u2018\u2019\uff08\uff09()\u3010\u3011\[\]\u3001~\u2014\u2026\u00b7]""")
ZH_NUM = str.maketrans("０１２３４５６７８９", "0123456789")


def make_norm(lang: str):
    """返回文本归一化函数。

    中文：zhconv 繁转简 + 全角数字 + 去标点。
    英文：**不做繁转简**（zhconv 是中文专用），只做数字归一 + 去标点 + 小写。
    """
    is_zh = lang.startswith("zh")

    def norm(t: str) -> str:
        t = t or ""
        if is_zh:
            try:
                from zhconv import convert
                t = convert(t, "zh-hans")
            except ImportError:
                pass
            t = t.translate(ZH_NUM)
        t = t.lower()
        t = PUNCT.sub("", t)
        return t

    return norm


def cer(hyp: str, ref: str) -> float:
    if not ref:
        return 0.0 if not hyp else 1.0
    d = np.zeros((len(ref) + 1, len(hyp) + 1), dtype=np.int32)
    d[:, 0] = np.arange(len(ref) + 1)
    d[0, :] = np.arange(len(hyp) + 1)
    for i in range(1, len(ref) + 1):
        for j in range(1, len(hyp) + 1):
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            d[i, j] = min(d[i - 1, j] + 1, d[i, j - 1] + 1, d[i - 1, j - 1] + cost)
    return float(d[len(ref), len(hyp)]) / len(ref)


def spk_embed(path, session):
    wav, sr = sf.read(path, dtype="float32", always_2d=True)
    wav = wav.mean(axis=1)
    t = torch.from_numpy(wav).unsqueeze(0)
    if sr != 16000:
        t = torchaudio.functional.resample(t, sr, 16000)
    feat = kaldi.fbank(t, num_mel_bins=80, dither=0, sample_frequency=16000)
    feat = feat - feat.mean(dim=0, keepdim=True)
    emb = session.run(None, {session.get_inputs()[0].name: feat.unsqueeze(0).numpy()})[0].flatten()
    return emb / (np.linalg.norm(emb) + 1e-8)


def cos(a, b):
    return float(np.dot(a, b))


def load_audio_16k(path):
    """Load any wav as 16kHz mono float32 numpy (whisper expects this)."""
    wav, sr = sf.read(path, dtype="float32", always_2d=True)
    wav = wav.mean(axis=1)
    t = torch.from_numpy(wav).unsqueeze(0)
    if sr != 16000:
        t = torchaudio.functional.resample(t, sr, 16000)
    return t.squeeze(0).numpy()


class OpenAIWhisperASR:
    """OpenAI whisper 后端（包名 openai-whisper）。"""

    name = "whisper"

    def __init__(self, spec: str, lang: str):
        import whisper

        self.model = whisper.load_model(spec)
        self.lang = lang

    def transcribe(self, audio16k):
        res = self.model.transcribe(audio16k, language=self.lang)
        return res["text"]


class FasterWhisperASR:
    """faster-whisper 后端（CTranslate2，Windows 上更轻）。"""

    name = "faster_whisper"

    def __init__(self, spec: str, lang: str):
        from faster_whisper import WhisperModel

        # faster-whisper 的模型名与 openai whisper 基本一致（medium/small/...）
        self.model = WhisperModel(spec, device="cpu", compute_type="int8")
        # faster-whisper 用 "zh"/"en" 之外的完整语言名，这里统一成短码
        self.lang = lang

    def transcribe(self, audio16k):
        segments, _info = self.model.transcribe(audio16k, language=self.lang)
        return "".join(s.text for s in segments)


def load_asr(backend: str, spec: str, lang: str):
    """按 backend 选择 ASR 后端；auto = 先试 whisper，再试 faster_whisper。"""
    order = ["whisper", "faster_whisper"] if backend == "auto" else [backend]
    errors = []
    for b in order:
        try:
            if b == "whisper":
                return OpenAIWhisperASR(spec, lang)
            if b == "faster_whisper":
                return FasterWhisperASR(spec, lang)
            raise ValueError("未知 ASR 后端: %s" % b)
        except ImportError as e:
            errors.append("%s: %s" % (b, e))
    raise SystemExit(
        "ERROR: 没有可用的 ASR 后端。\n  尝试过:\n    "
        + "\n    ".join(errors)
        + "\n  安装任一即可：\n"
        "    pip install openai-whisper -i https://mirrors.aliyun.com/pypi/simple/\n"
        "    pip install faster-whisper  -i https://mirrors.aliyun.com/pypi/simple/"
    )


def collect_real_clips(real_dir: str, real_glob: str, limit: int, real_list: str | None = None):
    """挑留出的真人片段作为音色 ground truth。

    两种来源：
      - `real_list`：一个文本文件，每行一条 wav 绝对路径（可为空行/# 注释）。
        **要复现历史报告数值时必须用它**——基线取决于选了哪几条片段，
        glob 采样会挑到完全不同的片段，基线/spk-sim 都不可比。
      - `real_dir` + `real_glob`：glob 后按步长均匀采样（limit=0 表示全取）。
    """
    if real_list:
        paths = []
        with open(real_list, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                paths.append(line)
        missing = [p for p in paths if not os.path.exists(p)]
        if missing:
            print("WARN: 列表中 %d 个文件不存在（跳过）: %s" % (len(missing), missing[:3]))
            paths = [p for p in paths if os.path.exists(p)]
        return paths

    paths = sorted(globmod.glob(os.path.join(real_dir, real_glob)))
    if not paths:
        return []
    if limit and len(paths) > limit:
        # 均匀取样，保证覆盖到不同场景
        step = len(paths) / float(limit)
        paths = [paths[int(i * step)] for i in range(limit)]
    return paths


def main():
    ap = argparse.ArgumentParser(description="Source2Voice · 阶段6a 量化评估")
    ap.add_argument("--ckpt_root", default=os.path.join(s2v_config.OUT_DIR, "omnivoice_paige"),
                    help="含 checkpoint-* 子目录的目录")
    ap.add_argument("--real_dir", default=None, help="留出真人片段所在目录（配合 --real_glob 用）")
    ap.add_argument("--real_glob", default="*.wav", help="留出片段的 glob")
    ap.add_argument("--real_limit", type=int, default=8, help="最多用多少条真人片段算基线（real_list 存在时忽略）")
    ap.add_argument("--real_list", default=None,
                    help="真人片段清单文件（每行一条 wav 路径）。用于精确复现历史基线；给了它就忽略 --real_dir/--real_glob")
    ap.add_argument("--texts", required=True, help="评估文本 JSON：{tid: text}")
    ap.add_argument("--lang", default="en", help="en / zh（决定 whisper 转写语言与归一化方式）")
    ap.add_argument("--whisper", default="medium", help="whisper 模型规格")
    ap.add_argument("--asr_backend", default="auto", choices=["auto", "whisper", "faster_whisper"],
                    help="转写后端；auto=优先 whisper，失败回落 faster_whisper")
    ap.add_argument("--json_out", default=None,
                    help="把评估结果写成 JSON（含 baseline / 各 ckpt 的 CER 与 spk-sim），供报告生成使用")
    a = ap.parse_args()

    import onnxruntime

    norm = make_norm(a.lang)

    with open(a.texts, encoding="utf-8") as f:
        TEXTS = json.load(f)
    if not TEXTS:
        print("ERROR: 评估文本为空: %s" % a.texts, file=sys.stderr)
        raise SystemExit(2)

    REAL_CLIPS = collect_real_clips(a.real_dir or "", a.real_glob, a.real_limit, a.real_list)
    if not REAL_CLIPS:
        print("ERROR: 没找到真人片段（--real_list=%s --real_dir=%s glob=%s）"
              % (a.real_list, a.real_dir, a.real_glob), file=sys.stderr)
        raise SystemExit(2)

    so = onnxruntime.SessionOptions()
    so.intra_op_num_threads = 4
    session = onnxruntime.InferenceSession(BASE, sess_options=so, providers=["CPUExecutionProvider"])
    asr = load_asr(a.asr_backend, a.whisper, a.lang)
    print("ASR backend: %s (%s)" % (asr.name, a.whisper))

    real_embs = [spk_embed(p, session) for p in REAL_CLIPS]
    # sanity: same-speaker ceiling across real clips
    sims = [cos(real_embs[i], real_embs[j])
            for i in range(len(real_embs)) for j in range(i + 1, len(real_embs))]
    baseline = float(np.mean(sims))
    print("[real clips] n=%d  mean pairwise spk-sim = %.4f  (真人基线)"
          % (len(REAL_CLIPS), baseline))

    rows = []
    for ckpt in sorted(os.listdir(a.ckpt_root)):
        d = os.path.join(a.ckpt_root, ckpt)
        if not os.path.isdir(d):
            continue
        for mode in ["ref", "noref"]:
            cers, sims = [], []
            for tid, text in TEXTS.items():
                wav_path = os.path.join(d, f"{tid}_{mode}.wav")
                if not os.path.exists(wav_path):
                    continue
                audio = load_audio_16k(wav_path)
                hyp_text = asr.transcribe(audio)
                hyp = norm(hyp_text)
                c = cer(hyp, norm(text))
                cers.append(c)
                emb = spk_embed(wav_path, session)
                s = np.mean([cos(emb, r) for r in real_embs])
                sims.append(s)
                print(f"{ckpt}/{mode} {tid}: cer={c:.3f} sim={s:.4f} hyp='{hyp_text[:40]}'")
            if cers:
                rows.append((ckpt, mode, float(np.mean(cers)), float(np.mean(sims))))

    print("\n===== SUMMARY (mean over %d held-out lines) =====" % len(TEXTS))
    print(f"{'ckpt':<14} {'mode':<6} {'CER':>7} {'spk-sim':>8}  {'vs baseline':>12}")
    for ckpt, mode, c, s in rows:
        flag = "PASS" if s > baseline else "below"
        print(f"{ckpt:<14} {mode:<6} {c:>7.3f} {s:>8.4f}  {flag:>12}")
    if rows:
        best = max(rows, key=lambda r: r[3])
        print(f"\n最佳 spk-sim: {best[0]} / {best[1]} = {best[3]:.4f} (真人基线 {baseline:.4f})")

    if a.json_out:
        payload = {
            "lang": a.lang,
            "asr_backend": asr.name,
            "whisper": a.whisper,
            "n_texts": len(TEXTS),
            "baseline": baseline,
            "n_real_clips": len(REAL_CLIPS),
            "rows": [{"ckpt": ck, "mode": m, "cer": c, "spk_sim": s,
                      "vs_baseline": s - baseline} for ck, m, c, s in rows],
        }
        if rows:
            best = max(rows, key=lambda r: r[3])
            payload["best"] = {"ckpt": best[0], "mode": best[1],
                               "spk_sim": best[3], "cer": best[2]}
        os.makedirs(os.path.dirname(os.path.abspath(a.json_out)), exist_ok=True)
        with open(a.json_out, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print("\n[json] 结果已写入 %s" % a.json_out)


if __name__ == "__main__":
    main()
