"""Turn the manifest (+ optional ASR cache) into the final dataset deliverables.

通用版：英雄名 / 资产前缀从英雄档案 JSON 读取，不再硬编码 dark_willow。
"""
import argparse
import csv
import json
import os
import wave

GROUP_LABEL = {
    "vo": "hero in-game voice lines",
    "announcer": "announcer pack",
    "announcer_killing_spree": "killing-spree announcer pack",
}
# 语言键 -> 短代码。语言键既可能是 "english" 也可能是 "en"。
LANG_CODE = {
    "english": "en", "en": "en",
    "schinese": "zh", "chinese": "zh", "zh": "zh",
    "japanese": "ja", "ja": "ja",
    "korean": "ko", "ko": "ko",
    "french": "fr", "fr": "fr",
    "german": "de", "de": "de",
    "spanish": "es", "es": "es",
    "russian": "ru", "ru": "ru",
    "portuguese": "pt", "pt": "pt",
    "italian": "it", "it": "it",
}


def lang_code(lang: str) -> str:
    """把语言键归一成两字母短代码（english -> en, schinese -> zh）。"""
    k = (lang or "").strip().lower()
    return LANG_CODE.get(k, k[:2])


def wav_seconds(path):
    try:
        with wave.open(path, "rb") as w:
            return round(w.getnframes() / float(w.getframerate()), 3)
    except Exception:  # noqa: BLE001
        return None


def variant_of(filename, asset_prefixes):
    """音频命名变体：返回该文件命中的资产前缀（去掉尾部下划线）。"""
    for p in sorted(asset_prefixes, key=len, reverse=True):
        if filename.startswith(p):
            return p.rstrip("_")
    return "default"


def load_hero_cfg(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--hero", default=None,
                    help="英雄档案 JSON（提供后输出文件名带英雄名）")
    ap.add_argument("--speaker", default=None, help=".list 里的说话人标签")
    a = ap.parse_args()
    root = a.root
    meta = os.path.join(root, "metadata")

    hero_cfg = load_hero_cfg(a.hero) if a.hero else {}
    hero_key = hero_cfg.get("hero_key", "")
    speaker = a.speaker or hero_cfg.get("hero_key") or "speaker"
    asset_prefixes = hero_cfg.get("asset_prefixes", [])

    manifest = json.load(open(os.path.join(meta, "manifest.json"), encoding="utf-8"))
    asr_path = os.path.join(meta, "asr_cache.json")
    asr = json.load(open(asr_path, encoding="utf-8")) if os.path.exists(asr_path) else {}
    fix_path = os.path.join(meta, "asr_tail_fix.json")
    fixed = json.load(open(fix_path, encoding="utf-8")) if os.path.exists(fix_path) else {}
    nm_path = os.path.join(meta, "asr_name_fix.json")
    named = json.load(open(nm_path, encoding="utf-8")) if os.path.exists(nm_path) else {}
    nv_path = os.path.join(meta, "nonverbal.json")
    nv = json.load(open(nv_path, encoding="utf-8")) if os.path.exists(nv_path) else {}

    rows = []
    # Chinese clips ship no subtitle table, so carry the English line over by filename
    en_by_file = {}
    for m in manifest:
        if m["language"] == "english" and m["text"]:
            en_by_file.setdefault((m.get("hero_key", ""), m["filename"]), m["text"])
        if m["language"] == "english" and m["text"]:
            en_by_file.setdefault(("", m["filename"]), m["text"])

    for m in manifest:
        lang, grp, fn = m["language"], m["group"], m["filename"]
        hk = m.get("hero_key", hero_key)
        wav_abs = os.path.join(root, m["wav"]).replace("\\", "/")
        mp3_abs = os.path.join(root, m["mp3"]).replace("\\", "/")
        text_en = m["text"] or en_by_file.get((hk, fn), "") or en_by_file.get(("", fn), "")
        # 官方字幕缺失的语言（Dota 2 中文）从 ASR 缓存取文本；
        # 官方字幕已有的语言（Deadlock 英文）直接用 m["text"]。
        text_asr = asr.get(fn, "")
        if m["text"]:
            text = m["text"]
            src = "official subtitle"
            usable = "yes"
        elif text_asr:
            text = text_asr
            src = "whisper large-v3 asr"
            usable = "yes"
        else:
            text = ""
            src = "no speech detected"
            usable = "no"
        if nv.get(fn) == "hallucination":
            src = "hallucination (cleared)"
            usable = "no"
            text = ""
        elif nv.get(fn) == "nonverbal":
            src = "non-verbal (grunt/laugh)"
            usable = "no"
            text = ""
        elif nv.get(fn) == "rescued":
            src = "whisper large-v3 asr (twin-rescued)"
            usable = "yes"
        corrected = fixed[fn]["kind"] if fn in fixed else ""
        nm = [v["kind"] for k, v in named.items() if k.split("|")[0] == fn]
        if nm:
            corrected = "+".join([corrected] + nm) if corrected else nm[0]
        if nv.get(fn) == "rescued":
            corrected = "twin-rescue"
        rows.append({
            "hero": hk,
            "language": lang,
            "lang_code": lang_code(lang),
            "group": grp,
            "group_label": GROUP_LABEL.get(grp, grp),
            "variant": variant_of(fn, asset_prefixes),
            "filename": fn,
            "token": m["token"],
            "text": text,
            "text_en_reference": text_en,
            "text_source": src,
            "text_corrected": corrected,
            "usable_for_tts": usable,
            "duration_sec": wav_seconds(os.path.join(root, m["wav"])),
            "wav": wav_abs,
            "mp3": mp3_abs,
        })

    rows.sort(key=lambda r: (r["hero"], r["language"], r["group"], r["filename"]))

    tag = ("_%s" % hero_key) if hero_key else ""
    csv_path = os.path.join(meta, "dataset%s.csv" % tag)
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("wrote", csv_path, len(rows), "rows")

    # GPT-SoVITS style .list  ->  wav|speaker|lang|text
    # clips whose transcript is missing or untrustworthy are skipped: an empty
    # or hallucinated transcript would break / mislead training pipelines
    made = 0
    skipped = 0
    heroes = sorted(set(r["hero"] for r in rows))
    for hk in heroes:
        for lang in sorted(set(r["language"] for r in rows if r["hero"] == hk)):
            for grp in sorted(set(r["group"] for r in rows
                                  if r["hero"] == hk and r["language"] == lang)):
                sel = [r for r in rows if r["hero"] == hk and r["language"] == lang
                       and r["group"] == grp]
                if not sel:
                    continue
                usable = [r for r in sel
                          if r["usable_for_tts"] == "yes" and r["text"].strip()]
                skipped += len(sel) - len(usable)
                spk = speaker if not hero_key else hk
                p = os.path.join(meta, "%s_%s_%s.list" % (lang, hk, grp))
                with open(p, "w", encoding="utf-8") as f:
                    for r in usable:
                        f.write("%s|%s|%s|%s\n"
                                % (r["wav"], spk, lang_code(lang), r["text"]))
                made += 1
                print("wrote", p, len(usable))
    print("skipped (no text):", skipped)

    # stats
    stats = {}
    for r in rows:
        k = "%s/%s/%s" % (r["hero"], r["language"], r["group"])
        s = stats.setdefault(k, {"count": 0, "seconds": 0.0, "with_text": 0, "usable": 0})
        s["count"] += 1
        s["seconds"] += r["duration_sec"] or 0
        if r["text"].strip():
            s["with_text"] += 1
        if r["usable_for_tts"] == "yes":
            s["usable"] += 1
    with open(os.path.join(meta, "stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    for k in sorted(stats):
        s = stats[k]
        print("  %-42s %5d clips  %7.1f min  text %d  usable %d"
              % (k, s["count"], s["seconds"] / 60, s["with_text"], s["usable"]))


if __name__ == "__main__":
    main()
