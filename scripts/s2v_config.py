# -*- coding: utf-8 -*-
"""Source2Voice 全局配置。

所有路径都可以通过环境变量覆盖，AI/脚本在换机器时只需设置这几个变量，
不必改动任何脚本源码。

环境变量
--------
S2V_ROOT            工作根目录（默认 D:/dwvits）
S2V_GAME_DIR        Steam 游戏根目录（默认 D:/SteamLibrary/steamapps/common/dota 2 beta）
S2V_GAME            游戏标识（dota2 / deadlock / cs2，见 GAME_REGISTRY，默认 dota2）
S2V_DATASET_DIR     数据集输出目录（默认 $S2V_ROOT/../DarkWillow_VoiceDataset）
S2V_WORK            训练工作目录（默认 $S2V_ROOT/work）
S2V_REPO            OmniVoice 源码目录（默认 $S2V_ROOT/src/OmniVoice）
S2V_MODEL           OmniVoice 基座模型目录（默认 $S2V_ROOT/models/omnivoice）
S2V_PYTHON          训练用 Python 解释器（默认 $S2V_ROOT/envs/omnivoice/Scripts/python.exe）
S2V_FFMPEG          ffmpeg 可执行文件（默认读 PATH，其次 Windows 常见路径）
S2V_HERO            英雄内部代号前缀（如 dark_willow）
S2V_HERO_ASSET      资源目录前缀（如 helmet_sylph）
S2V_WHISPER_MODEL   faster-whisper large-v3 本地模型目录（默认 $S2V_ROOT/models/faster-whisper-large-v3）
S2V_ASR_TMP         ASR 拼接临时目录（默认 $S2V_ROOT/work/asr_tmp）
S2V_CAMPPLUS        campplus 说话人验证模型 onnx（默认 $S2V_ROOT/models/campplus.onnx）
"""
from __future__ import annotations

import os
import shutil
import sys

# ---------------------------------------------------------------- 根目录
ROOT = os.environ.get("S2V_ROOT", "D:/dwvits")

# ---------------------------------------------------------------- 游戏资源
GAME_DIR = os.environ.get(
    "S2V_GAME_DIR", "D:/SteamLibrary/steamapps/common/dota 2 beta"
)
GAME_ROOT = os.path.join(GAME_DIR, "game")

# ---------------------------------------------------------------- 游戏注册表
# 每个 Source 2 游戏一套：资源根目录名 + 语言包子目录名 + 台词本地化目录。
# 换游戏只需在这里加一条（或用环境变量 S2V_GAME 覆盖），英雄档案里再指定英雄。
#
#   game_root      <GAME_DIR>/game 下的子目录（存放 pak01_dir.vpk）
#   lang_roots     语言包子目录名 -> 语言键；中文用 schinese
#   vo_loc_dir     台词本地化目录（相对 <GAME_DIR>/game/<game_root>），
#                  Deadlock 的台词不在 VPK 里，而是解压在磁盘上
GAME_REGISTRY = {
    "dota2": {
        "game_root": "dota",
        "lang_roots": {"english": "dota", "schinese": "dota_schinese"},
        "vo_loc_dir": None,
    },
    "deadlock": {
        "game_root": "citadel",
        "lang_roots": {"english": "citadel"},
        "vo_loc_dir": "resource/localization/citadel_generated_vo",
    },
    "cs2": {
        "game_root": "csgo",
        "lang_roots": {"english": "csgo", "schinese": "csgo_schinese"},
        "vo_loc_dir": None,
    },
}

GAME = os.environ.get("S2V_GAME", "dota2")

_GAME_SPEC = GAME_REGISTRY.get(GAME, GAME_REGISTRY["dota2"])

# 语言包 -> VPK 目录索引文件。不同语言的资源分装在不同的 VPK 包里。
# 英雄档案可用 "vpk_overrides" 单独指定某语言的 VPK 路径。
LANG_PACKAGES = {}
for _lang, _root in _GAME_SPEC["lang_roots"].items():
    LANG_PACKAGES[_lang] = os.path.join(GAME_ROOT, _root, "pak01_dir.vpk")


def resolve_vpk(hero_cfg: dict, lang: str) -> str:
    """解析某语言实际使用的 VPK 目录索引路径。

    优先级：英雄档案 ``vpk_overrides[lang]`` > 全局 LANG_PACKAGES。
    """
    override = hero_cfg.get("vpk_overrides", {}).get(lang)
    if override:
        return override
    return LANG_PACKAGES.get(lang, "")

# ---------------------------------------------------------------- 数据集
DATASET_DIR = os.environ.get("S2V_DATASET_DIR", "D:/DarkWillow_VoiceDataset")
META_DIR = os.path.join(DATASET_DIR, "metadata")

# ---------------------------------------------------------------- 训练侧
WORK = os.environ.get("S2V_WORK", os.path.join(ROOT, "work"))
REPO = os.environ.get("S2V_REPO", os.path.join(ROOT, "src", "OmniVoice"))
MODEL = os.environ.get("S2V_MODEL", os.path.join(ROOT, "models", "omnivoice"))
PYTHON = os.environ.get(
    "S2V_PYTHON", os.path.join(ROOT, "envs", "omnivoice", "Scripts", "python.exe")
)

# ---------------------------------------------------------------- ASR / 评估
WHISPER_MODEL = os.environ.get(
    "S2V_WHISPER_MODEL", os.path.join(ROOT, "models", "faster-whisper-large-v3")
)
ASR_TMP = os.environ.get("S2V_ASR_TMP", os.path.join(WORK, "asr_tmp"))
CAMPPLUS = os.environ.get(
    "S2V_CAMPPLUS", os.path.join(ROOT, "models", "campplus.onnx")
)


def _resolve_campplus() -> str:
    """定位 campplus.onnx（说话人相似度用）。

    优先级：
      1. 环境变量 S2V_CAMPPLUS
      2. $ROOT/models/campplus.onnx
      3. $ROOT/models 下任意一层子目录里的 campplus.onnx
         （CosyVoice 发行包里它放在 models/cosyvoice/<model>/campplus.onnx）
    """
    env = os.environ.get("S2V_CAMPPLUS")
    if env:
        return env
    direct = os.path.join(ROOT, "models", "campplus.onnx")
    if os.path.exists(direct):
        return direct
    models_dir = os.path.join(ROOT, "models")
    if os.path.isdir(models_dir):
        for dirpath, _dirnames, filenames in os.walk(models_dir):
            if "campplus.onnx" in filenames:
                return os.path.join(dirpath, "campplus.onnx")
    return direct


CAMPPLUS = _resolve_campplus()

# ---------------------------------------------------------------- 训练产物
EXP_DIR = os.path.join(WORK, "exp")
OUT_DIR = os.path.join(WORK, "out")
DATA_DIR = os.path.join(WORK, "data")

# 英雄相关（换英雄只需改这两项 + GROUPS/SUBTITLE_FILES 映射）
HERO = os.environ.get("S2V_HERO", "dark_willow")
HERO_ASSET = os.environ.get("S2V_HERO_ASSET", "helmet_sylph")

# ---------------------------------------------------------------- ffmpeg
_FFMPEG_CANDIDATES = [
    os.environ.get("S2V_FFMPEG", ""),
    r"C:\Program Files (x86)\FormatFactory\FFModules\Encoder\ffmpeg.exe",
    "/usr/bin/ffmpeg",
    "/usr/local/bin/ffmpeg",
]


def find_ffmpeg() -> str | None:
    """定位 ffmpeg：优先环境变量，其次 PATH，最后常见安装位置。"""
    for c in _FFMPEG_CANDIDATES:
        if c and os.path.exists(c):
            return c
    return shutil.which("ffmpeg")


FFMPEG = find_ffmpeg()


def require(cond: bool, msg: str) -> None:
    """断言前置条件，给出可执行的修复建议而不是裸 assert。"""
    if not cond:
        sys.stderr.write("[Source2Voice] 前置条件不满足: %s\n" % msg)
        raise SystemExit(2)


def ensure_dirs(*paths: str) -> None:
    for p in paths:
        os.makedirs(p, exist_ok=True)


def rel(path: str) -> str:
    """统一用正斜杠，便于跨平台与 JSONL 元数据。"""
    return os.path.abspath(path).replace("\\", "/")


if __name__ == "__main__":
    print("S2V_ROOT      =", ROOT)
    print("S2V_GAME      =", GAME, "spec:", _GAME_SPEC["game_root"])
    print("GAME_DIR     =", GAME_DIR)
    print("LANG_PACKAGES:")
    for k, v in LANG_PACKAGES.items():
        print("   %-10s %s (exists=%s)" % (k, v, os.path.exists(v)))
    print("DATASET_DIR  =", DATASET_DIR)
    print("REPO         =", REPO)
    print("MODEL        =", MODEL)
    print("PYTHON       =", PYTHON, "(exists=%s)" % os.path.exists(PYTHON))
    print("FFMPEG       =", FFMPEG)
    print("HERO         =", HERO, "/", HERO_ASSET)
    print("WHISPER      =", WHISPER_MODEL)
    print("CAMPPLUS     =", CAMPPLUS)
    print("WORK         =", WORK)
