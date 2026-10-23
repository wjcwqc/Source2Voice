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
"""
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

CKPT_ROOT = os.path.join(s2v_config.OUT_DIR, "omnivoice_dark_willow")
BASE = s2v_config.CAMPPLUS

# real Dark Willow clips (dev set, held out from training) = timbre ground truth
# 换英雄时改成该英雄的留出片段；这些文件不能出现在训练清单里。
_DW = os.path.join(s2v_config.DATASET_DIR, "schinese", "dark_willow", "vo")
REAL_CLIPS = [
    os.path.join(_DW, n) for n in (
        "sylph_ability3_05.wav",
        "sylph_ally_13.wav",
        "sylph_ally_204.wav",
        "sylph_ally_228.wav",
        "sylph_battlebegins_02.wav",
        "sylph_death_09.wav",
    )
]

TEXTS = {
    "t01": "我想你在哪儿,你就在哪儿。",
    "t02": "天,我爱死钱了!",
    "t03": "跟我计划的不太一样",
    "t04": "相信自然的力量,它总会找到出路。",
}

PUNCT = re.compile(r"""[\s,.!?;:'",\u3002\uff01\uff1f\uff1b\uff1a"\u2018\u2019\uff08\uff09()\u3010\u3011\[\]\u3001~\u2014\u2026\u00b7]""")
ZH_NUM = str.maketrans("０１２３４５６７８９", "0123456789")


def norm(t: str) -> str:
    from zhconv import convert
    t = convert(t, "zh-hans")  # whisper may output traditional Chinese
    t = t.translate(ZH_NUM).lower()
    t = PUNCT.sub("", t)
    return t


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


def main():
    import onnxruntime
    import whisper

    so = onnxruntime.SessionOptions()
    so.intra_op_num_threads = 4
    session = onnxruntime.InferenceSession(BASE, sess_options=so, providers=["CPUExecutionProvider"])
    print("loading whisper medium ...")
    model = whisper.load_model("medium")

    real_embs = [spk_embed(p, session) for p in REAL_CLIPS]
    # sanity: same-speaker ceiling across real clips
    sims = [cos(real_embs[i], real_embs[j])
            for i in range(len(real_embs)) for j in range(i + 1, len(real_embs))]
    print(f"[real DW clips] mean pairwise spk-sim = {np.mean(sims):.4f} (n={len(sims)})")

    rows = []
    for ckpt in sorted(os.listdir(CKPT_ROOT)):
        d = os.path.join(CKPT_ROOT, ckpt)
        if not os.path.isdir(d):
            continue
        for mode in ["ref", "noref"]:
            cers, sims = [], []
            for tid, text in TEXTS.items():
                wav_path = os.path.join(d, f"{tid}_{mode}.wav")
                if not os.path.exists(wav_path):
                    continue
                audio = load_audio_16k(wav_path)
                res = model.transcribe(audio, language="zh")
                hyp = norm(res["text"])
                c = cer(hyp, norm(text))
                cers.append(c)
                emb = spk_embed(wav_path, session)
                s = np.mean([cos(emb, r) for r in real_embs])
                sims.append(s)
                print(f"{ckpt}/{mode} {tid}: cer={c:.3f} sim={s:.4f} hyp='{res['text'][:30]}'")
            if cers:
                rows.append((ckpt, mode, float(np.mean(cers)), float(np.mean(sims))))

    print("\n===== SUMMARY (mean over 4 held-out lines) =====")
    print(f"{'ckpt':<14} {'mode':<6} {'CER':>7} {'spk-sim':>8}")
    for ckpt, mode, c, s in rows:
        print(f"{ckpt:<14} {mode:<6} {c:>7.3f} {s:>8.4f}")


if __name__ == "__main__":
    main()
