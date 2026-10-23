"""Mark the Chinese lines whose transcript cannot be trusted.

Two failure modes survived the boundary/glossary corrections:

1. **Hallucination.** On a non-speech or noisy clip Whisper large-v3 sometimes
   emits stock text instead of nothing.  Two clips (`*_kill_05`, English line
   "Tsk tsk tsk...") produced YouTube boilerplate -- 优优独播剧场 / 请不吝点赞
   订阅 转发 打赏 -- and one speech clip produced a laughter repetition loop.

2. **Non-verbal line.** Grunts, laughs and screams (English line "Ugh!",
   "Hahahaha!", "Ha ya!") do get *some* text out of Whisper, but it is a
   transliteration of a noise, not speech.  As a (text -> speech) training pair
   that is actively harmful.

Neither is fixed by rewriting the text; the honest treatment is to keep the
audio, mark the transcript unusable, and drop the pair from the training lists.

Writes metadata/nonverbal.json = {filename: "hallucination" | "nonverbal"}
and blanks the hallucinated text in asr_cache.json.

Usage:  python mark_nonverbal.py [--dry-run]
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

# Every token observed in an interjection-only English subtitle line.  A line is
# non-verbal when *all* of its tokens are in here -- that is why real short
# lines such as "Shiny.", "Too easy." or "Mine." stay verbal.
INTERJECTIONS = {
    "uh", "ugh", "uhh", "uhhh", "ah", "ahh", "aah", "ahhh", "a", "ay", "ay-a",
    "ha", "hah", "haha", "hahaha", "hahahaha", "hahahahahah", "ahaha", "ahhaha",
    "ahhahahaha", "ahhhahahahahaha", "hahahahaha", "heh", "eheh", "hee", "hihi",
    "hu", "huh", "huu", "hu-ah", "hu-dah", "hu ah", "ha ya", "ha-dya",
    "haa-dya", "huu-dya", "hya-ga", "da", "dya", "dah", "ga", "gah", "gaah",
    "guh", "bah", "err", "mrf", "hm", "hmm", "hrm", "mm", "mmm", "pff", "grr",
    "rawr", "whoa", "woah", "yo", "hmph", "ow", "aw", "eh", "oof", "uff",
    "nonono", "tsk", "tut", "haa", "haaa", "hyah", "hyahh", "yah", "ya",
    # elongated forms (doubled vowels) that are not real words
    "uugh", "uuugh", "aagh", "aaagh", "aww", "awww", "awwww", "awwwww",
    "boo", "hoo", "noo", "ooh", "ooo", "oooh", "ooooo", "ohhh", "ohhhh",
    "ohhhhh", "soo", "sooo", "wee", "yeessss", "hrrrrgg", "huaa", "hht",
    "mhm", "mmhmm", "hrrm", "grrr", "grrrr", "rawrr", "meh", "pfft",
}

BOILERPLATE = [
    "优优独播", "独播剧场", "请不吝", "点赞", "订阅", "转发", "打赏",
    "明镜", "点点栏目", "字幕组", "感谢观看", "amara.org", "subtitle",
    "thanks for watching", "yoyo television",
]

# a unit of 1-3 characters repeated 6+ times in a row
LOOP_RE = re.compile(r"(.{1,3})\1{5,}")
TOKEN_RE = re.compile(r"[\s,.'\"!?…\-]+")
# laughter variants are open-ended (hahahahahaha, ahhahahahahaa, ...), so match
# them structurally -- but never swallow a real word made of the same letters
LAUGH_RE = re.compile(r"^[haeiouy]+$")
REAL_WORDS = {"you", "your", "yours", "yeah", "yay", "yoyo", "hue", "hoe",
              "hay", "eye", "eyes", "howl", "how", "hail", "heal", "hill",
              "hull", "hell", "hello", "hole", "holy", "hue"}


def is_interjection(tok: str) -> bool:
    if tok in INTERJECTIONS:
        return True
    return len(tok) >= 2 and bool(LAUGH_RE.match(tok)) and tok not in REAL_WORDS


def is_nonverbal(en_ref: str) -> bool:
    e = (en_ref or "").strip().lower()
    if not e:
        return False
    parts = [p for p in TOKEN_RE.split(e) if p]
    return bool(parts) and all(is_interjection(p) for p in parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    cache_path = os.path.join(META, "asr_cache.json")
    cache = json.load(open(cache_path, encoding="utf-8"))
    rows = [r for r in csv.DictReader(open(os.path.join(META, "darkwillow_dataset.csv"),
                                           encoding="utf-8-sig"))
            if r["language"] == "schinese"]

    marks, blanked, rescued = {}, [], []
    for r in rows:
        fn, t, en = r["filename"], cache.get(r["filename"], "") or "", r["text_en_reference"]
        if not t.strip():
            continue
        low = t.lower()
        bad = None
        if any(k in low for k in BOILERPLATE):
            bad = "boilerplate"
        else:
            loop = LOOP_RE.search(t)
            if loop and not is_nonverbal(en):
                # a repetition loop on a line that does have words
                bad = "loop:%s" % loop.group(0)[:12]
        if bad:
            marks[fn] = "hallucination"
            blanked.append((fn, t, en, bad))
        elif is_nonverbal(en):
            marks[fn] = "nonverbal"

    # A hallucinated clip whose twin (helmet_sylph_X / sylph_X -- the same
    # recording, same subtitle) decodes cleanly can be repaired instead of
    # dropped: copy the twin's transcript.
    rescued = []
    for fn in [f for f, v in marks.items() if v == "hallucination"]:
        stem = None
        if fn.startswith("helmet_sylph_"):
            stem = fn[len("helmet_sylph_"):]
            twin = "sylph_" + stem
        elif fn.startswith("sylph_"):
            stem = fn[len("sylph_"):]
            twin = "helmet_sylph_" + stem
        if not twin or twin in marks or not (cache.get(twin, "") or "").strip():
            continue
        rescued.append((fn, cache[fn][:28], cache[twin]))
        cache[fn] = cache[twin]
        marks[fn] = "rescued"

    for fn in [f for f, v in marks.items() if v == "hallucination"]:
        cache[fn] = ""

    nv = sum(1 for v in marks.values() if v == "nonverbal")
    hl = sum(1 for v in marks.values() if v == "hallucination")
    print("zh lines with text : %d" % sum(1 for r in rows if (cache.get(r['filename']) or '').strip()))
    print("non-verbal lines   : %d   (grunt/laugh/scream; transcript dropped from training)" % nv)
    print("hallucinations     : %d   (text blanked)" % hl)
    print("rescued from twin  : %d" % len(rescued))
    for fn, t, good in rescued:
        print("   %-36s %s -> %s" % (fn, t, good))
    for fn, t, en, why in blanked:
        if marks.get(fn) == "hallucination":
            print("   BLANK %-30s [%s] %s | EN=%s" % (fn, why, t[:36], en[:36]))
    by_group = {}
    for r in rows:
        if marks.get(r["filename"]) == "nonverbal":
            by_group[r["group"]] = by_group.get(r["group"], 0) + 1
    print("non-verbal by group: %s" % by_group)

    out = os.path.join(META, "nonverbal.json")
    json.dump(marks, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("report -> %s" % out)
    if a.dry_run:
        print("(dry run: asr_cache.json untouched)")
        return
    json.dump(cache, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("patched -> %s" % cache_path)


if __name__ == "__main__":
    main()
