"""Fix Chinese tail-bleed by fusing the windowed text with an isolated decode.

The windowed pass (asr_zh_windows.py) packs ~28 s of clips into one Whisper
window and maps words back by timestamp midpoint.  Whisper's Chinese "words"
are multi-character chunks, so a chunk that straddles a clip boundary is
assigned wholesale to one side: the opening characters of clip i+1 leak into
clip i, and occasionally the opening characters of clip i are pulled back into
clip i-1.  Measured on 732 suspicious clips.

An isolated decode of the same clip has no neighbour to leak from, so its
*length* is trustworthy -- but on its own it is worse: large-v3 drifts to
Traditional Chinese and makes fresh character errors (天徽/天辉, 夜宴/夜眼).

Fusion rule
-----------
  core(s)      = the alphanumeric/CJK characters of s, punctuation dropped
  old          = windowed text (good characters, possibly too long)
  iso          = isolated decode (right length, possibly wrong characters)

  len(core(iso)) >= len(core(old))  ->  keep old
  prefixes align (lcp_core >= 2)    ->  cut old after len(core(iso)) core chars
  prefixes disagree                 ->  leading bleed; fall back to iso

Punctuation is ignored when counting, so 哦,高水平战略,我就 -> 哦,高水平战略
falls out naturally from a core length of 7.

Usage
-----
  python asr_tail_merge.py --selftest          # replay known-good samples
  python asr_tail_merge.py --apply             # patch asr_cache.json
"""
import argparse
import csv
import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import s2v_config  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
ROOT = s2v_config.DATASET_DIR
META = os.path.join(ROOT, "metadata")
TRAIL = ",，、;；:： \t"
MAX_CUT = 6  # a boundary leak is 1-3 characters; more means the decode is short

# user-facing label for the CSV `text_corrected` column
KIND = {
    "cut": "boundary-trim",
    "iso-shift": "leading-leak",
    "iso-lead-bleed": "leading-leak",
    "keep-old": "punctuation",
    "glossary": "glossary",
    "traditional": "traditional",
    "twin-prefix": "twin-prefix",
}

# Whisper mishears a few Dota 2 proper nouns consistently.  Every entry below
# was verified item by item against the official English subtitle line, e.g.
#   EN "Dire's Ancient is under attack!" -> ZH 夜眼一记正受到攻击  (一记/遗迹)
# 天辉 (Radiant) and 夜魇 (Dire) are the official Simplified Chinese names.
# Context-limited entries are deliberate:
#   红武军团 / 古铜军团  are Red Mist Horde / Bronze Legion, not "structures"
#   敌方下塔刚被讨伐     uses 刚被 as "just got", not the hero Bristleback
GLOSSARY = [
    ("军团全面加固", "建筑全面加固"),
    ("天徽", "天辉"),
    ("夜眼", "夜魇"),
    ("夜宴", "夜魇"),
    ("夜焰", "夜魇"),
    ("一记", "遗迹"),
    ("尽用", "禁用"),
    ("刚被瘦", "刚背兽"),   # Bristleback
    ("刚被兽", "刚背兽"),
    ("米团", "谜团"),       # Enigma
    ("丽娜", "莉娜"),       # Lina
    ("恐怖力人", "恐怖利刃"),  # Terrorblade
    ("反捕", "反补"),       # deny (24 tower-deny lines)
    # one-off slips, each confirmed by the twin recording of the same line
    ("喜节一空", "洗劫一空"),  # EN "how to rob Weeping Rose"
    ("碰揍", "胖揍"),        # EN "beat you stupid"
    ("说发女妖", "蛇发女妖"),  # EN "some gorgons"
    ("来防我", "来烦我"),      # EN "I'm haunted by Kunkka"
]


def apply_glossary(text):
    hits = []
    for bad, good in GLOSSARY:
        if bad in text:
            text = text.replace(bad, good)
            hits.append("%s->%s" % (bad, good))
    return text, hits


def core(text):
    """Characters that carry content, with their original indices."""
    pos = [i for i, c in enumerate(text) if c.isalnum()]
    return "".join(text[i] for i in pos), pos


def lcp(a, b):
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def is_shift(a, b):
    """True when a and b hold the same characters in a different order.

    That is the fingerprint of a leading leak: clip i loses its opening
    characters to clip i-1 and gains the opening characters of clip i+1, so the
    multiset of characters survives while the string shifts.
    """
    return len(a) == len(b) and a != b and sorted(a) == sorted(b)


def rstrip_soft(text):
    """Drop a dangling half-width comma/space left behind by a cut."""
    return text.rstrip(TRAIL)


def fuse(old, iso, simp=None, prev_old=""):
    """Return (new_text, reason)."""
    old = old.strip()
    iso = (iso or "").strip()
    old_core, old_pos = core(old)
    if not iso:
        return rstrip_soft(old), "iso-empty"
    # large-v3 drifts to Traditional Chinese without neighbour context; align
    # and measure on the Simplified form or every long line looks misaligned
    iso = (simp or iso).strip()
    iso_core, _ = core(iso)
    if not iso_core:
        return rstrip_soft(old), "iso-empty"
    if not old_core:
        return rstrip_soft(old), "old-empty"

    aligned = lcp(old_core, iso_core) >= 2
    if not aligned:
        # A single substituted character (夜眼/夜宴) is an ASR slip, not a
        # boundary leak -- only a genuine character rotation justifies
        # abandoning the windowed text, whose characters are otherwise better.
        if is_shift(old_core, iso_core):
            return rstrip_soft(iso), "iso-shift"
        # Leading leak: clip i lost its opening characters to clip i-1.  Only
        # trust the decode when the previous clip's raw text actually ends with
        # the character this decode starts with -- that is the fingerprint of
        # the character having travelled backwards.
        gain = len(iso_core) - len(old_core)
        if 0 < gain <= 2 and iso_core.endswith(old_core) and prev_old:
            prev_core, _ = core(prev_old)
            if prev_core and iso_core.startswith(prev_core[-1]):
                return rstrip_soft(iso), "iso-lead-bleed"
        return rstrip_soft(old), "keep-old"

    n = len(iso_core)
    if n >= len(old_core):
        return rstrip_soft(old), "keep-old"
    if len(old_core) - n > MAX_CUT:
        # a leak is 1-3 characters; a bigger gap means the isolated decode
        # dropped words rather than the window picking up a neighbour
        return rstrip_soft(old), "keep-old"
    if n >= len(old_pos):
        return rstrip_soft(old), "keep-old"
    return rstrip_soft(old[:old_pos[n]]), "cut"


_CC = None


def to_simplified(text):
    """Traditional -> Simplified; returns None when opencc is unavailable."""
    global _CC
    if _CC is None:
        try:
            from opencc import OpenCC
        except ImportError:
            return None
        _CC = OpenCC("t2s")
    return _CC.convert(text)


def selftest():
    d = json.load(open(os.path.join(META, "asr_iso0.json"), encoding="utf-8"))
    rows = {r["filename"]: r
            for r in csv.DictReader(open(os.path.join(META, "darkwillow_dataset.csv"),
                                         encoding="utf-8-sig"))}
    for fn, v in d.items():
        new, why = fuse(v["old"], v["new"], to_simplified(v["new"]))
        new, gl = apply_glossary(new)
        tag = "   " if new == v["old"] else "FIX"
        print("%s %-38s [%s]%s" % (tag, fn, why, " " + ",".join(gl) if gl else ""))
        print("      EN =%s" % rows[fn]["text_en_reference"])
        print("      old=%s" % v["old"])
        print("      iso=%s" % v["new"])
        print("      new=%s" % new)


def apply_fix(iso_files, dry=False):
    cache_path = os.path.join(META, "asr_cache.json")
    cache = json.load(open(cache_path, encoding="utf-8"))
    orig = dict(cache)  # neighbour lookups must see the un-patched text
    seq = list(csv.DictReader(open(os.path.join(META, "darkwillow_dataset.csv"),
                                   encoding="utf-8-sig")))
    rows = {r["filename"]: r for r in seq}
    # the CSV is sorted (language, group, filename); a leak travels from clip i
    # into clip i-1, so the predecessor in that order is the only candidate
    prev_of = {}
    zh_seq = [r for r in seq if r["language"] == "schinese"]
    for i in range(1, len(zh_seq)):
        if zh_seq[i]["group"] == zh_seq[i - 1]["group"]:
            prev_of[zh_seq[i]["filename"]] = zh_seq[i - 1]["filename"]
    iso = {}
    for p in iso_files:
        for k, v in json.load(open(p, encoding="utf-8")).items():
            # the pilot run stored {"old": .., "new": ..}, later runs store str
            iso[k] = v["new"] if isinstance(v, dict) else v

    report, why_count = {}, {}
    gloss_count = {}

    def note(fn, old, new, iso_text, why, gl):
        if new == old:
            return
        prev = report.get(fn)
        report[fn] = {
            "en": rows.get(fn, {}).get("text_en_reference", ""),
            "old": prev["old"] if prev else old,
            "iso": iso_text,
            "new": new,
            "why": why if not prev else prev["why"],
            "kind": KIND.get(prev["why"] if prev else why, why),
            "glossary": (prev["glossary"] if prev else []) + gl,
        }
        cache[fn] = new

    # pass 1 -- boundary fusion, only for the clips that were re-decoded
    for fn, raw in iso.items():
        old = cache.get(fn, "")
        if not old:
            continue
        simp = to_simplified(raw)
        new, why = fuse(old, raw, simp, orig.get(prev_of.get(fn, ""), ""))
        why_count[why] = why_count.get(why, 0) + 1
        note(fn, old, new, raw, why, [])

    # pass 2 -- glossary over *every* Chinese line.  Most misheard proper nouns
    # (天徽/夜眼) sit in lines that were never flagged for a boundary leak, so
    # running the glossary only inside pass 1 would miss ~85% of them.
    for r in zh_seq:
        fn = r["filename"]
        old = cache.get(fn, "")
        if not old:
            continue
        new, gl = apply_glossary(old)
        if gl:
            for h in gl:
                gloss_count[h] = gloss_count.get(h, 0) + 1
        note(fn, old, new, iso.get(fn, ""), "glossary", gl)

    # pass 3 -- script normalisation.  Whisper large-v3 drifts to Traditional
    # Chinese on a handful of lines even in the windowed pass, and the isolated
    # decodes used above can be Traditional too.  opencc t2s is a no-op on
    # already-Simplified text, so running it over everything is safe.
    for r in zh_seq:
        fn = r["filename"]
        old = cache.get(fn, "")
        if not old:
            continue
        new = to_simplified(old) or old
        if new != old:
            why_count["traditional"] = why_count.get("traditional", 0) + 1
        note(fn, old, new, iso.get(fn, ""), "traditional", [])

    # pass 4 -- twin cross-check.  helmet_sylph_X and sylph_X are two encodings
    # of the *same* recording and share one subtitle line, so their transcripts
    # must agree.  Measured: 762/975 pairs identical; in 82 the shorter one is a
    # strict suffix of the longer, i.e. it lost its opening characters to a
    # window boundary.  The longer form is the complete one, so adopt it.
    for r in zh_seq:
        fn = r["filename"]
        if not fn.startswith("helmet_sylph_"):
            continue
        twin = "sylph_" + fn[len("helmet_sylph_"):]
        a, b = cache.get(fn, ""), cache.get(twin, "")
        if not a or not b:
            continue
        ca, cb = core(a)[0], core(b)[0]
        if ca == cb or not ca or not cb:
            continue
        if ca.endswith(cb) and 0 < len(ca) - len(cb) <= 5:
            note(twin, b, a, iso.get(twin, ""), "twin-prefix", [])
            why_count["twin-prefix"] = why_count.get("twin-prefix", 0) + 1
        elif cb.endswith(ca) and 0 < len(cb) - len(ca) <= 5:
            note(fn, a, b, iso.get(fn, ""), "twin-prefix", [])
            why_count["twin-prefix"] = why_count.get("twin-prefix", 0) + 1

    # pass 5 -- lines whose English subtitle is the same sentence (or one
    # contains the other, e.g. "It's your turn to ban." vs "Oh! It's your turn
    # to ban.") are alternative takes of one line, so their transcripts must
    # agree.  Where one is a strict suffix of the other it lost its opening
    # characters at a window boundary.  This catches the announcer takes, which
    # have no helmet_/sylph_ twin.
    by_group = {}
    for r in zh_seq:
        by_group.setdefault(r["group"], []).append(r)
    for _g, rs in by_group.items():
        for a in rs:
            fa = a["filename"]
            ca = core(cache.get(fa, ""))[0]
            if len(ca) < 2:
                continue
            ea = a["text_en_reference"].strip().lower()
            for b in rs:
                fb = b["filename"]
                if fa == fb:
                    continue
                eb = b["text_en_reference"].strip().lower()
                if not (ea and eb and (ea == eb or ea in eb or eb in ea)):
                    continue
                cb = core(cache.get(fb, ""))[0]
                if len(cb) > len(ca) and cb.endswith(ca) and len(cb) - len(ca) <= 5:
                    note(fa, cache[fa], cache[fb], iso.get(fa, ""), "twin-prefix", [])
                    why_count["twin-prefix"] = why_count.get("twin-prefix", 0) + 1
                    break

    print("reasons : %s" % why_count)
    print("glossary: %s" % gloss_count)
    print("changed : %d of %d zh lines" % (len(report), len(zh_seq)))
    out = os.path.join(META, "asr_tail_fix.json")
    json.dump(report, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("report -> %s" % out)
    if not dry:
        json.dump(cache, open(cache_path, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("patched -> %s" % cache_path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--iso", nargs="*", default=None)
    a = ap.parse_args()
    if a.selftest:
        selftest()
    elif a.apply:
        files = a.iso or [os.path.join(META, "asr_iso%d.json" % i) for i in range(8)]
        files = [p for p in files if os.path.exists(p)]
        if not files:
            sys.exit("no asr_iso*.json found")
        print("inputs: %s" % ", ".join(os.path.basename(p) for p in files))
        apply_fix(files, dry=a.dry_run)
    else:
        ap.error("pass --selftest or --apply")


if __name__ == "__main__":
    main()
