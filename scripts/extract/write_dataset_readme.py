#!/usr/bin/env python3
"""Source2Voice · 阶段 1.4：为数据集生成 README.md（统计 + 使用说明）。

从 manifest.json 和 CSV 清单读取真实数据，自动统计条数/时长/文本覆盖率，
生成可直接发布到 HuggingFace 数据集仓库的说明文档。

用法
----
    python write_dataset_readme.py --hero ../../configs/hero_dark_willow.json
    # 指定 CSV（可选，默认从 metadata 里探测）
    python write_dataset_readme.py --csv <path/to/dataset.csv>
"""
import argparse
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import s2v_config  # noqa: E402

LANG_CN = {"english": "英文", "schinese": "简体中文", "zh": "中文", "en": "英文"}
GROUP_CN = {
    "vo": "游戏内语音（英雄台词）",
    "announcer": "播音包",
    "announcer_killing_spree": "连杀播音包",
}


def load_rows(meta_dir: str, csv_path: str | None) -> list:
    """加载 CSV 清单（自动探测常见文件名，容忍 UTF-8 BOM 与 GBK）。"""
    candidates = [csv_path] if csv_path else [
        os.path.join(meta_dir, "dataset.csv"),
        os.path.join(meta_dir, "darkwillow_dataset.csv"),
        os.path.join(meta_dir, "darkwillow_dataset_new.csv"),
    ]
    for p in candidates:
        if not p or not os.path.exists(p):
            continue
        for enc in ("utf-8-sig", "utf-8", "gbk"):
            try:
                with open(p, encoding=enc, newline="") as f:
                    return list(csv.DictReader(f))
            except (UnicodeDecodeError, csv.Error):
                continue
    return []


def main():
    ap = argparse.ArgumentParser(description="Source2Voice · 生成数据集 README")
    ap.add_argument("--hero", default=os.path.join(HERE, "..", "..", "configs",
                                                   "hero_dark_willow.json"))
    ap.add_argument("--csv", default=None, help="数据集 CSV 清单")
    ap.add_argument("--out", default=None, help="输出 README 路径")
    a = ap.parse_args()

    with open(os.path.abspath(a.hero), encoding="utf-8") as f:
        hero = json.load(f)

    root = s2v_config.DATASET_DIR
    meta = os.path.join(root, "metadata")
    man_path = os.path.join(meta, "manifest.json")
    manifest = []
    if os.path.exists(man_path):
        with open(man_path, encoding="utf-8") as f:
            manifest = json.load(f)

    rows = load_rows(meta, a.csv)
    hero_key = hero["hero_key"]
    display = hero.get("display_name", hero_key)

    # ------------------------------------------------------------ 统计
    langs = hero.get("languages", ["english", "schinese"])
    groups = list(hero.get("groups", {}).keys())

    def stat(lang, group):
        sel = [m for m in manifest
               if m.get("language") == lang and m.get("group") == group]
        n = len(sel)
        with_text = sum(1 for m in sel if (m.get("text") or "").strip())
        # 时长：从 CSV 读（manifest 里没有）
        secs = 0.0
        if rows:
            sel_rows = [r for r in rows
                        if r.get("language") == lang and r.get("group") == group]
            for r in sel_rows:
                try:
                    secs += float(r.get("duration_sec") or 0)
                except ValueError:
                    pass
        return n, secs, with_text

    lines = []
    A = lines.append
    A("# %s 语音训练集" % display)
    A("")
    A("从本机 Steam 版游戏资源中提取的 %s 全部语音，附带逐条对应文本，"
      "可直接用于 TTS / 声音克隆训练。" % display)
    A("")
    A("## 1. 数据来源")
    A("")
    A("- 游戏安装路径：`%s`" % s2v_config.GAME_DIR)
    for lang in langs:
        pkg = s2v_config.LANG_PACKAGES.get(lang)
        if pkg:
            A("- %s语音包：`%s`" % (LANG_CN.get(lang, lang),
                                    os.path.relpath(pkg, s2v_config.GAME_DIR).replace("\\", "/")))
    A("- 原始音频格式：Source 2 的 `.vsnd_c` 容器"
      "（前 4 字节小端 uint32 = MP3 流起始偏移）")
    A("- 提取范围：")
    for g in groups:
        A("  - `%s` — %s" % (hero["groups"][g], GROUP_CN.get(g, g)))
    A("")
    A("## 2. 目录结构")
    A("")
    A("```")
    A("%s/" % os.path.basename(root.rstrip("/")))
    for lang in langs:
        A("├── %s/%s/    %s（32 kHz / 16 bit / 单声道 WAV）" %
          (lang, hero_key, LANG_CN.get(lang, lang)))
        for g in groups:
            n, _, _ = stat(lang, g)
            A("│   ├── %-28s %d 条" % (g + "/", n))
    A("├── raw_mp3/    原始 MP3（便于溯源 / 换采样率）")
    A("└── metadata/")
    A("    ├── manifest.json      中间清单（token / text / path）")
    A("    ├── *.list             GPT-SoVITS 格式 `wav|speaker|lang|text`")
    A("    ├── asr_cache.json     ASR 结果缓存")
    A("    └── README.md          本文件")
    A("```")
    A("")
    A("## 3. 文本来源")
    A("")
    A("- **有官方字幕的语言**：直接取游戏内置字幕文件，逐条 token 精确匹配。")
    A("- **没有官方字幕的语言**：由 Whisper large-v3 对音频识别生成"
      "（Valve 通常只提供英文字幕）。")
    A("  - 提速策略：短句按 ~28 秒打包成窗口 + 词级时间戳回切"
      "（Whisper 固定编码 30 秒窗口，逐条识别浪费 ~95% 算力）。")
    A("  - 已知问题与修正：边界粘连、专有名词同音错字、Whisper 幻觉、非语言条目。"
      "详见仓库 `references/TROUBLESHOOTING.md`。")
    A("")
    A("## 4. 数据统计")
    A("")
    A("| 语言 | 分组 | 条数 | 时长 | 有文本 |")
    A("|---|---|---:|---:|---:|")
    tot_n = tot_s = tot_t = 0
    for lang in langs:
        for g in groups:
            n, s, t = stat(lang, g)
            tot_n += n
            tot_s += s
            tot_t += t
            mins = "%.1f 分钟" % (s / 60) if s else "-"
            A("| %s | %s | %d | %s | %d |" %
              (LANG_CN.get(lang, lang), GROUP_CN.get(g, g), n, mins, t))
    A("| **合计** | | **%d** | **%.1f 分钟** | **%d** |" %
      (tot_n, tot_s / 60, tot_t))
    A("")
    A("## 5. 训练用法")
    A("")
    A("GPT-SoVITS / CosyVoice / VITS 等流程可直接使用 `.list` 文件"
      "（格式 `wav路径|说话人|语言|文本`）：")
    A("")
    A("```")
    for lang in langs:
        A("metadata/%s_%s_vo.list" % (lang, hero_key))
    A("```")
    A("")
    A("OmniVoice 微调请用 `scripts/train/prep_omnivoice_data.py` 转成 JSONL。")
    A("")
    A("## 6. 已知限制")
    A("")
    A("1. ASR 生成的中文文本不保证 100% 准确，已修正常见问题但仍建议抽查。")
    A("2. 部分台词带背景音乐/音效，做纯语音训练时建议先筛选。")
    A("3. 播音包与英雄语音的录音条件不同（增益/滤波不同），"
      "建议先只用英雄语音组训练音色，播音包作为补充。")
    A("")
    A("## 许可与版权")
    A("")
    A("语音资源版权归 Valve Corporation 所有。请遵守 Dota 2 最终用户许可协议（EULA），"
      "不要将音频用于商业分发。")
    A("")

    text = "\n".join(lines) + "\n"
    out = a.out or os.path.join(root, "README.md")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    with open(os.path.join(meta, "README.md"), "w", encoding="utf-8") as f:
        f.write(text)
    print("README -> %s (+ %s), %d lines" % (out, os.path.join(meta, "README.md"), len(lines)))


if __name__ == "__main__":
    main()
