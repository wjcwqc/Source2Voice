"""Turn the manifest (+ ASR cache) into the final dataset deliverables."""
import argparse
import csv
import json
import os
import wave

GROUP_LABEL = {
    "vo": "hero in-game voice lines",
    "announcer": "Dark Willow announcer pack",
    "announcer_killing_spree": "Dark Willow killing-spree announcer pack",
}
LANG_CODE = {"english": "en", "schinese": "zh"}
G2S_LANG = {"english": "en", "schinese": "zh"}


def wav_seconds(path):
    try:
        with wave.open(path, "rb") as w:
            return round(w.getnframes() / float(w.getframerate()), 3)
    except Exception:  # noqa: BLE001
        return None


def variant_of(filename):
    if filename.startswith("helmet_sylph_"):
        return "helmet_sylph"
    if filename.startswith("sylph_"):
        return "sylph"
    return "announcer"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    a = ap.parse_args()
    root = a.root
    meta = os.path.join(root, "metadata")

    manifest = json.load(open(os.path.join(meta, "manifest.json"), encoding="utf-8"))
    asr_path = os.path.join(meta, "asr_cache.json")
    asr = json.load(open(asr_path, encoding="utf-8")) if os.path.exists(asr_path) else {}
    # clips whose Chinese line was reworked by asr_tail_merge.py
    fix_path = os.path.join(meta, "asr_tail_fix.json")
    fixed = json.load(open(fix_path, encoding="utf-8")) if os.path.exists(fix_path) else {}
    # clips whose Chinese line had a proper noun repaired by asr_names.py
    nm_path = os.path.join(meta, "asr_name_fix.json")
    named = json.load(open(nm_path, encoding="utf-8")) if os.path.exists(nm_path) else {}
    # clips whose Chinese transcript cannot be trusted (mark_nonverbal.py)
    nv_path = os.path.join(meta, "nonverbal.json")
    nv = json.load(open(nv_path, encoding="utf-8")) if os.path.exists(nv_path) else {}

    rows = []
    # Chinese clips ship no subtitle table, so carry the English line over by filename
    en_by_file = {}
    for m in manifest:
        if m["language"] == "english" and m["text"]:
            en_by_file.setdefault(m["filename"], m["text"])

    for m in manifest:
        lang, grp, fn = m["language"], m["group"], m["filename"]
        wav_abs = os.path.join(root, m["wav"]).replace("\\", "/")
        mp3_abs = os.path.join(root, m["mp3"]).replace("\\", "/")
        text_en = m["text"] or en_by_file.get(fn, "")
        text_zh = asr.get(fn, "") if lang == "schinese" else ""
        text = text_zh if lang == "schinese" else text_en
        if lang == "english":
            src = "official valve subtitle"
            usable = "yes"
        elif nv.get(fn) == "hallucination":
            src = "hallucination (cleared)"
            usable = "no"
        elif nv.get(fn) == "nonverbal":
            src = "non-verbal (grunt/laugh)"
            usable = "no"
        elif nv.get(fn) == "rescued":
            src = "whisper large-v3 asr (twin-rescued)"
            usable = "yes"
        elif text_zh:
            src = "whisper large-v3 asr"
            usable = "yes"
        else:
            src = "non-verbal (no speech detected)"
            usable = "no"
        corrected = fixed[fn]["kind"] if fn in fixed else ""
        # a line can be boundary-trimmed and then name-repaired; show both
        nm = [v["kind"] for k, v in named.items() if k.split("|")[0] == fn]
        if nm:
            corrected = "+".join([corrected] + nm) if corrected else nm[0]
        if nv.get(fn) == "rescued":
            corrected = "twin-rescue"
        rows.append({
            "language": lang,
            "lang_code": LANG_CODE[lang],
            "group": grp,
            "group_label": GROUP_LABEL[grp],
            "variant": variant_of(fn),
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

    rows.sort(key=lambda r: (r["language"], r["group"], r["filename"]))

    csv_path = os.path.join(meta, "darkwillow_dataset.csv")
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
    for lang in sorted(set(r["language"] for r in rows)):
        for grp in sorted(set(r["group"] for r in rows)):
            sel = [r for r in rows if r["language"] == lang and r["group"] == grp]
            if not sel:
                continue
            usable = [r for r in sel
                      if r["usable_for_tts"] == "yes" and r["text"].strip()]
            skipped += len(sel) - len(usable)
            p = os.path.join(meta, "%s_dark_willow_%s.list" % (lang, grp))
            with open(p, "w", encoding="utf-8") as f:
                for r in usable:
                    f.write("%s|dark_willow|%s|%s\n"
                            % (r["wav"], G2S_LANG[lang], r["text"]))
            made += 1
            print("wrote", p, len(usable))
    print("skipped (no text):", skipped)

    # deduplicated hero list (helmet_sylph variant only, higher bitrate source)
    ded = [r for r in rows
           if r["language"] == "english" and r["group"] == "vo"
           and r["variant"] == "helmet_sylph" and r["text"].strip()
           and r["usable_for_tts"] == "yes"]
    if ded:
        p = os.path.join(meta, "english_dark_willow_vo_dedup.list")
        with open(p, "w", encoding="utf-8") as f:
            for r in ded:
                f.write("%s|dark_willow|en|%s\n" % (r["wav"], r["text"]))
        print("wrote", p, len(ded))

    # Chinese hero list limited to the same 985 unique lines (drop the duplicate
    # legacy `sylph_*` naming) so a zh model sees each line once
    zh_ded = [r for r in rows
              if r["language"] == "schinese" and r["group"] == "vo"
              and r["variant"] == "helmet_sylph" and r["text"].strip()
              and r["usable_for_tts"] == "yes"]
    if zh_ded:
        p = os.path.join(meta, "schinese_dark_willow_vo_dedup.list")
        with open(p, "w", encoding="utf-8") as f:
            for r in zh_ded:
                f.write("%s|dark_willow|zh|%s\n" % (r["wav"], r["text"]))
        print("wrote", p, len(zh_ded))

    # stats
    stats = {}
    for r in rows:
        k = "%s/%s" % (r["language"], r["group"])
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
