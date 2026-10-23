"""Repair Dota 2 proper nouns in the Chinese ASR text using the game's own name tables.

Dark Willow ships official English subtitles but no Chinese ones, so the Chinese
text came from Whisper.  Whisper transcribes the sentences well but turns proper
nouns into whatever common word sounds closest:

    Morphling 变体精灵 -> 遍体精灵      Silencer 沉默术士 -> 陈默舒适
    Radiance  辉耀     -> 灰药          Mireska  米瑞斯嘉 -> 米瑞斯家
    Weeping Rose 悲玫城 -> 杯梅城        Selemene 赛莉蒙妮 -> 塞利蒙尼

Every English subtitle line names the entity explicitly ("Never stop changing,
Morphling."), and the game's localization files carry the official Chinese
spelling.  So for each line we know *which* name must appear -- we only have to
find the slot it occupies.

Matching runs on pinyin (tone-insensitive) rather than characters, because the
confusions are phonetic: 灰药/辉耀 and 悲梅城/悲玫城 differ in every character
yet are pronounced identically.

Usage
    python asr_names.py --report     # show every proposed change, change nothing
    python asr_names.py --apply      # patch metadata/asr_cache.json
"""
import argparse
import csv
import json
import os
import re
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import s2v_config  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
ROOT = s2v_config.DATASET_DIR
META = os.path.join(ROOT, "metadata")
HERE = os.path.dirname(os.path.abspath(__file__))
NAMES = os.path.join(HERE, "dota_names.json")

# how a match was reached -> user-facing label for the CSV `text_corrected` column
TIER = {
    "homophone": "name-homophone",   # identical pinyin, different characters
    "near-pinyin": "name-near",      # one syllable off
    "one-char": "name-typo",         # one character off
    "twin": "name-twin",             # the sibling recording carries the name
}

# Fillers, pronouns and demonstratives.  A longer window that swallows one of
# these is not naming anything, it is just spilling into the next word.
STOP = set("嗯哦啊呀呃唉吧呢吗这那我你您他她它们的了是在")


def core(text):
    """Content characters only, so punctuation never splits a name."""
    return "".join(c for c in (text or "") if c.isalnum())


_PY = None


def pinyin(s):
    global _PY
    if _PY is None:
        try:
            from pypinyin import lazy_pinyin
        except ImportError:
            sys.exit("pip install pypinyin")
        _PY = lazy_pinyin
    return _PY(s, errors="ignore")


def name_table():
    d = json.load(open(NAMES, encoding="utf-8"))
    t = {}
    t.update(d["heroes"])
    for k, v in d["items"].items():
        t.setdefault(k, v)
    t.update(d["terms"])
    return t


def _scan(c, z, L, strong_only=False):
    """Windows of length L inside `c` that look like the first L characters of `z`."""
    target = z[:L]
    zp = pinyin(z)
    if len(zp) < L:
        return []
    tp = zp[:L]
    hits = []
    for i in range(0, len(c) - L + 1):
        w = c[i:i + L]
        wp = pinyin(w)
        if len(wp) != L:
            continue
        d_py = sum(1 for a, b in zip(wp, tp) if a != b)
        d_ch = sum(1 for a, b in zip(w, target) if a != b)
        if d_py == 0 and d_ch > 0:
            tier = "homophone"
        elif d_ch == 1 and L >= 3:
            tier = "one-char"
        elif d_py <= 1:
            tier = "near-pinyin"
        else:
            continue
        if strong_only and tier == "near-pinyin":
            continue
        hits.append((i, L, target, tier, d_py, d_ch))
    return hits


def _best(hits, by_length=False):
    """Cheapest match, or None when two different slots tie (ambiguous)."""
    if not hits:
        return None
    rank = {"homophone": 0, "one-char": 1, "near-pinyin": 2}
    if by_length:
        hits = sorted(hits, key=lambda h: (rank[h[3]], -h[1], h[0]))
        key = lambda h: (rank[h[3]], h[1])
    else:
        hits = sorted(hits, key=lambda h: (rank[h[3]], h[4], h[5]))
        key = lambda h: (rank[h[3]], h[4], h[5])
    b = hits[0]
    if len({h[0] for h in hits if key(h) == key(b)}) > 1:
        return None
    return b


def find_slot(c, z):
    """Locate where `z` should sit inside `c`, or None when nothing needs doing.

    Order matters.  A line that already uses an accepted short form (祸乱 for
    Bane, 巨牙 for Tusk, 末日 for Doom) must be left alone, but a line that
    contains the same characters by accident (虚无知境 contains 虚无) must still
    be repaired.

    So the full-length slot is examined first, and when the line *also* carries
    an exact short form the two readings are separated by looking at what the
    longer window swallowed: 杰克森 -> 杰克斯 is a real repair, while
    末日嗯这 -> 末日使者 merely ate the filler 嗯 and the demonstrative 这.
    """
    if z in c:
        return None
    full = _best(_scan(c, z, len(z)))
    short = any(z[:L] in c for L in range(len(z) - 1, 1, -1))
    if full:
        if not short:
            return full
        i, L = full[0], full[1]
        return None if (STOP & set(c[i:i + L])) else full
    if short:
        return None
    # shorter slots -- catches a truncated name (戴达罗斯 for 代达罗斯之殇).
    # Ranked by match strength before length: 霍乱 is a perfect homophone of
    # 祸乱 and must beat the 3-character 霍乱见, whose third character is just
    # the next word bleeding in.
    hits = []
    for L in range(len(z) - 1, 1, -1):
        hits.extend(_scan(c, z, L))
    return _best(hits, by_length=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    if not (a.apply or a.report):
        ap.error("pass --report or --apply")

    cache_path = os.path.join(META, "asr_cache.json")
    cache = json.load(open(cache_path, encoding="utf-8"))
    rows = list(csv.DictReader(open(os.path.join(META, "darkwillow_dataset.csv"),
                                    encoding="utf-8-sig")))
    zh = [r for r in rows if r["language"] == "schinese"]
    by_fn = {r["filename"]: r for r in zh}
    table = sorted(name_table().items(), key=lambda kv: -len(kv[0]))

    report, applied = {}, {}
    stats = {}
    for r in zh:
        fn = r["filename"]
        text = cache.get(fn, "")
        c = core(text)
        if not c:
            continue
        en = r["text_en_reference"] or ""
        # the English line may name several entities; longest name wins so
        # "Nyx Assassin" is not shadowed by "Nyx"
        used = set()
        for enn, z in table:
            m = None
            for cand in re.finditer(r"(?<![A-Za-z])" + re.escape(enn) + r"(?![A-Za-z])", en):
                if any(i in used for i in range(cand.start(), cand.end())):
                    continue
                m = cand
                break
            if not m:
                continue
            used.update(range(m.start(), m.end()))
            if z in c:
                continue
            hit = find_slot(c, z)
            tier = None
            if hit:
                i, L, target, tier, _, _ = hit
                wrong = c[i:i + L]
                # splice back into the original text, keeping punctuation
                pos = [k for k, ch in enumerate(text) if ch.isalnum()]
                s, e = pos[i], pos[i + L - 1] + 1
                new = text[:s] + target + text[e:]
            else:
                # fall back on the sibling recording: helmet_sylph_X and sylph_X
                # are the same line twice, so if one carries the name, adopt it
                twin = None
                if fn.startswith("helmet_sylph_"):
                    twin = "sylph_" + fn[len("helmet_sylph_"):]
                elif fn.startswith("sylph_"):
                    twin = "helmet_sylph_" + fn[len("sylph_"):]
                if twin and twin in by_fn and z in core(cache.get(twin, "")):
                    new, tier, wrong = cache[twin], "twin", c
                else:
                    continue
            if new == text:
                continue
            stats[tier] = stats.get(tier, 0) + 1
            applied[fn] = {"en": en, "old": text, "new": new, "name": enn,
                           "expected": z, "wrong": wrong, "tier": tier,
                           "kind": TIER[tier]}
            report["%s|%s" % (fn, enn)] = {
                "en": en, "old": text, "new": new, "expected": z,
                "found": wrong, "kind": TIER[tier],
            }
            cache[fn] = new

    # write first: the report below can be long, and losing the run because a
    # reader closed the pipe early would be a silent, expensive mistake
    if a.apply:
        json.dump(cache, open(cache_path, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        json.dump(report, open(os.path.join(META, "asr_name_fix.json"), "w",
                               encoding="utf-8"), ensure_ascii=False, indent=1)

    print("applied by tier: %s" % stats)
    print("lines changed  : %d" % len(applied))
    print()
    for fn in sorted(applied):
        v = applied[fn]
        print("%-34s %-15s %-6s  %s" % (fn, v["name"], v["expected"], v["kind"]))
        print("      %s" % v["old"])
        print("   -> %s" % v["new"])
    if a.apply:
        print("\npatched -> %s" % cache_path)
        print("report  -> %s" % os.path.join(META, "asr_name_fix.json"))


if __name__ == "__main__":
    main()
