# -*- coding: utf-8 -*-
"""Source2Voice · 阶段 1：从 Source 2 游戏的 VPK 包提取英雄语音 + 官方台词。

管线
----
1. 读语言包 VPK 目录索引（英文 game/dota，简体中文 game/dota_schinese）。
2. 抽出该英雄目录下所有 `.vsnd_c`：
     sounds/vo/<hero>/                             英雄游戏内语音
     sounds/vo/announcer_dlc_<hero>/               播音包
     sounds/vo/announcer_dlc_<hero>_killing_spree/ 连杀播音包
3. `.vsnd_c` 是 Source 2 声音容器，**前 4 字节小端 uint32 = MP3 流起始偏移**，
   剥离容器头即得 MP3。
4. ffmpeg 解码 MP3 -> 32 kHz / 16 bit / 单声道 WAV。
5. 用官方字幕 token 把音频与台词对齐，输出 metadata/manifest.json。

用法
----
    python pipeline.py --hero ../configs/hero_dark_willow.json --out <dataset_root>

所有路径可用环境变量覆盖，见 scripts/s2v_config.py。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import s2v_config as C  # noqa: E402
from vpk import Vpk  # noqa: E402

TOKEN_RE = re.compile(r'^\s*"([^"]+)"\s+"((?:[^"\\]|\\.)*)"\s*$')


# ---------------------------------------------------------------- 字幕
def parse_subtitles(data: bytes) -> dict:
    """解析 Valve 字幕 .txt（KV 风格：每行 "token" "text"）。"""
    out = {}
    for line in data.decode("utf-8-sig", "replace").splitlines():
        m = TOKEN_RE.match(line.rstrip("\r"))
        if not m:
            continue
        tok, txt = m.group(1), m.group(2)
        if tok in ("lang", "Language", "Tokens"):
            continue
        out[tok] = txt.replace('\\"', '"').replace("\\n", " ").strip()
    return out


def load_subtitles(vpk: Vpk, subtitle_files: list[str]) -> dict:
    """把该英雄所有字幕文件合并成一张 token -> text 表。"""
    table = {}
    for e in vpk.entries:
        if e.path in subtitle_files:
            table.update(parse_subtitles(vpk.data(e)))
    return table


def resolve_token(group: str, stem: str, table: dict, hero_cfg: dict) -> str | None:
    """把音频文件名（stem）映射到字幕 token。

    命名规则随英雄而变，因此 token_rules 用模板列表描述候选：
        {stem}            完整文件名主干，如 helmet_sylph_spawn_01
        {rest_<资产前缀>} 去掉该资产前缀后的主干，如 spawn_01
    按顺序取第一个在字幕表里命中的候选。
    """
    rules = hero_cfg.get("token_rules", {}).get(group, [])
    if not rules:
        return None

    fields = {"stem": stem}
    for asset in hero_cfg.get("asset_prefixes", []):
        key = "rest_" + asset.rstrip("_")
        fields[key] = stem[len(asset):] if stem.startswith(asset) else stem

    for rule in rules:
        try:
            cand = rule.format(**fields)
        except KeyError:
            continue
        if cand in table:
            return cand
    return None


# ---------------------------------------------------------------- vsnd_c
def vsnd_to_mp3(blob: bytes) -> bytes:
    """剥离 Source 2 .vsnd_c 容器头，返回裸 MP3。

    容器结构：uint32 mp3_offset | KV3 blocks (RED2/DATA/CTRL) ...
    mp3_offset 处必须是 0xFF（MP3 帧同步字）。
    """
    off = struct.unpack("<I", blob[:4])[0]
    if off >= len(blob) or blob[off] != 0xFF:
        raise ValueError("no MP3 sync at offset %d" % off)
    return blob[off:]


# ---------------------------------------------------------------- 转码
def convert_all(ffmpeg: str, todo: list, wav_dir: str, sr: int, channels: int,
                fmt: str, batch: int = 60) -> None:
    """批量 ffmpeg 转码（一次调用处理多个输入），跳过已完成文件。"""
    pending = [(s, p) for s, p in todo
               if not os.path.exists(os.path.join(wav_dir, s + ".wav"))]
    if not pending:
        return
    done = 0
    for i in range(0, len(pending), batch):
        chunk = pending[i:i + batch]
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
        for _, mp3 in chunk:
            cmd += ["-i", os.path.abspath(mp3)]
        for j, (stem, _) in enumerate(chunk):
            dst = os.path.abspath(os.path.join(wav_dir, stem + ".wav"))
            cmd += ["-map", "%d:a" % j, "-ar", str(sr), "-ac", str(channels),
                    "-acodec", fmt, dst]
        subprocess.run(cmd, check=True)
        done += len(chunk)
        print("      converted %d/%d" % (done, len(pending)), flush=True)


# ---------------------------------------------------------------- 主流程
def run(hero_cfg: dict, ffmpeg: str, out_root: str, langs: dict,
        do_wav: bool = True) -> list:
    manifest = []
    for lang, vpk_path in langs.items():
        C.require(os.path.exists(vpk_path),
                  "VPK 不存在: %s（检查 S2V_GAME_DIR 是否指向正确的 Steam 安装目录）" % vpk_path)
        vpk = Vpk(vpk_path)
        table = load_subtitles(vpk, hero_cfg["subtitle_files"])
        print("[%s] subtitle tokens: %d" % (lang, len(table)))
        if not table:
            print("[%s] 警告: 没读到字幕 token，该语言将没有台词" % lang)

        for group, prefix in hero_cfg["groups"].items():
            entries = sorted(
                (e for e in vpk.entries if e.path.startswith(prefix)),
                key=lambda e: e.path,
            )
            if not entries:
                continue
            mp3_dir = os.path.join(out_root, "raw_mp3", lang, hero_cfg["hero_key"], group)
            wav_dir = os.path.join(out_root, lang, hero_cfg["hero_key"], group)
            os.makedirs(mp3_dir, exist_ok=True)
            if do_wav:
                os.makedirs(wav_dir, exist_ok=True)

            todo = []
            for e in entries:
                stem = os.path.splitext(os.path.basename(e.path))[0]
                mp3_path = os.path.join(mp3_dir, stem + ".mp3")
                if not os.path.exists(mp3_path):
                    with open(mp3_path, "wb") as f:
                        f.write(vsnd_to_mp3(vpk.data(e)))
                todo.append((stem, mp3_path))

            if do_wav:
                convert_all(ffmpeg, todo, wav_dir,
                            hero_cfg.get("target_sr", 32000),
                            hero_cfg.get("target_channels", 1),
                            hero_cfg.get("target_sample_fmt", "pcm_s16le"))

            hit = 0
            for stem, mp3_path in todo:
                token = resolve_token(group, stem, table, hero_cfg)
                text = table.get(token, "") if token else ""
                if text:
                    hit += 1
                wav_path = os.path.join(wav_dir, stem + ".wav")
                manifest.append({
                    "language": lang,
                    "group": group,
                    "filename": stem,
                    "token": token or "",
                    "text": text,
                    "mp3": os.path.relpath(mp3_path, out_root).replace("\\", "/"),
                    "wav": os.path.relpath(wav_path, out_root).replace("\\", "/")
                    if do_wav else "",
                })
            print("  [%s/%s] %d clips, %d matched subtitle" % (lang, group, len(todo), hit))
    return manifest


def main():
    ap = argparse.ArgumentParser(description="Source2Voice · 阶段1 语音提取")
    ap.add_argument("--hero", default=os.path.join(HERE, "..", "..", "configs",
                                                    "hero_dark_willow.json"),
                    help="英雄档案 JSON")
    ap.add_argument("--out", default=C.DATASET_DIR, help="数据集输出根目录")
    ap.add_argument("--langs", default=None,
                    help="逗号分隔，默认取英雄档案里的 languages")
    ap.add_argument("--ffmpeg", default=C.FFMPEG)
    ap.add_argument("--no-wav", action="store_true", help="只出 MP3，不转 WAV")
    a = ap.parse_args()

    with open(os.path.abspath(a.hero), encoding="utf-8") as f:
        hero_cfg = json.load(f)

    C.require(a.ffmpeg and os.path.exists(a.ffmpeg),
              "找不到 ffmpeg。设置 S2V_FFMPEG 环境变量指向可执行文件路径。")

    wanted = (a.langs.split(",") if a.langs else hero_cfg.get("languages", []))
    langs = {k: C.LANG_PACKAGES[k] for k in wanted if k in C.LANG_PACKAGES}
    C.require(bool(langs), "没有可用的语言包，检查 configs/*.json 的 languages 字段")

    os.makedirs(os.path.join(a.out, "metadata"), exist_ok=True)
    manifest = run(hero_cfg, a.ffmpeg, a.out, langs, do_wav=not a.no_wav)

    mpath = os.path.join(a.out, "metadata", "manifest.json")
    with open(mpath, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    print("manifest entries: %d -> %s" % (len(manifest), mpath))


if __name__ == "__main__":
    main()
