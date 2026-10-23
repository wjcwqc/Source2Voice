"""Build token -> audio-file mapping for Dark Willow VO and announcer packs."""
import os
import re
import sys
import json
import glob

ROOT = r"C:\Users\wjcwqc\workbuddy-ai\dwvits"
SUB = os.path.join(ROOT, "raw", "subtitles")

TOKEN_RE = re.compile(r'^\s*"([^"]+)"\s+"((?:[^"\\]|\\.)*)"\s*$')


def load_subtitles(path):
    """Parse a Valve subtitle .txt into {token: text}."""
    out = {}
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            m = TOKEN_RE.match(line.rstrip("\n"))
            if not m:
                continue
            tok, txt = m.group(1), m.group(2)
            if tok in ("lang", "Language", "Tokens"):
                continue
            txt = txt.replace('\\"', '"').replace("\\n", " ")
            out[tok] = txt
    return out


def main():
    subs = {}
    for p in glob.glob(os.path.join(SUB, "*.txt")):
        subs[os.path.basename(p)] = load_subtitles(p)
        print("%-60s %d tokens" % (os.path.basename(p), len(subs[os.path.basename(p)])))

    hero = {}
    hero.update(subs["subtitles_dark_willow_english.txt"])
    hero.update(subs["subtitles_sylph_english.txt"])
    ann = subs["subtitles_announcer_dlc_dark_willow_english.txt"]
    spree = subs["subtitles_announcer_dlc_dark_willow_killing_spree_english.txt"]

    groups = {
        "vo": (r"sounds/vo/dark_willow/*.vsnd_c", hero,
               ["dark_willow_sylph_", "sylph_sylph_"]),
        "announcer": (r"sounds/vo/announcer_dlc_dark_willow/*.vsnd_c", ann,
                      ["announcer_dlc_dark_willow_"]),
        "announcer_killing_spree": (
            r"sounds/vo/announcer_dlc_dark_willow_killing_spree/*.vsnd_c", spree,
            ["announcer_dlc_dark_willow_killing_spree_"]),
    }

    report = {}
    for gname, (pat, table, prefixes) in groups.items():
        files = sorted(glob.glob(os.path.join(ROOT, "raw", "en", pat)))
        matched, unmatched = {}, []
        for fp in files:
            stem = os.path.splitext(os.path.basename(fp))[0]  # e.g. helmet_sylph_spawn_01
            # normalise hero internal prefix to token prefix
            cands = []
            if stem.startswith("helmet_sylph_"):
                rest = stem[len("helmet_sylph_"):]
                cands = [p + rest for p in prefixes]
            else:
                cands = [p + stem for p in prefixes]
            hit = next((t for t in cands if t in table), None)
            if hit:
                matched[os.path.basename(fp)] = (hit, table[hit])
            else:
                unmatched.append(os.path.basename(fp))
        used = set(v[0] for v in matched.values())
        unused = sorted(set(table) - used)
        report[gname] = {
            "audio_files": len(files),
            "matched": len(matched),
            "unmatched_audio": unmatched,
            "unused_tokens": unused,
        }
        print("\n[%s] audio=%d matched=%d unmatched=%d unused_tokens=%d"
              % (gname, len(files), len(matched), len(unmatched), len(unused)))
        for u in unmatched[:10]:
            print("   no-text audio:", u)
        for u in unused[:10]:
            print("   no-audio token:", u)

    with open(os.path.join(ROOT, "raw", "map_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
