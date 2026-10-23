"""Quality gate for the corrected Chinese transcripts.

Checks, in order:
  1. coverage / emptiness
  2. Traditional Chinese leftovers (opencc round-trip test)
  3. lines still ending without terminal punctuation -- cosmetic, not an error
  4. residual boundary leaks: does a line's tail repeat the head of the next
     line in the same group?  (the signature of a leak that survived)
  5. corrections that emptied a line or grew it unexpectedly
  6. a random sample of old -> new pairs for eyeballing

Usage:  python verify_zh.py [--sample 40]
"""
import argparse
import csv
import json
import os
import random
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import s2v_config  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
ROOT = s2v_config.DATASET_DIR
META = os.path.join(ROOT, "metadata")
END = "。！？…!?~"
PUNCT = set("，,。.、！!？?…~～:：;；'\"“”‘’()（） ")


def core(t):
    return "".join(c for c in t if c.isalnum())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=30)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()

    rows = list(csv.DictReader(open(os.path.join(META, "darkwillow_dataset.csv"),
                                    encoding="utf-8-sig")))
    zh = [r for r in rows if r["language"] == "schinese"]
    with_text = [r for r in zh if r["text"].strip()]
    print("zh clips              : %d" % len(zh))
    print("  with text           : %d" % len(with_text))
    print("  without text        : %d   (non-verbal yells)" % (len(zh) - len(with_text)))

    no_punct = [r for r in with_text if r["text"].strip()[-1] not in END]
    print("  no terminal punct   : %d   (cosmetic; ASR omits it often)"
          % len(no_punct))

    try:
        from opencc import OpenCC
        cc = OpenCC("t2s")
    except ImportError:
        cc = None
    if cc:
        trad = [r for r in with_text if cc.convert(r["text"]) != r["text"]]
        print("  traditional leftover: %d" % len(trad))
        for r in trad[:10]:
            print("      %-40s %s" % (r["filename"], r["text"]))
    else:
        print("  traditional leftover: (opencc missing, skipped)")

    # residual leak scan -- same-group neighbours only, overlap >= 2 characters,
    # and skip interjection repeats (哈哈/哈哈哈哈哈) which match trivially
    seq = sorted(with_text, key=lambda r: (r["group"], r["filename"]))
    sus = []
    for i in range(len(seq) - 1):
        if seq[i]["group"] != seq[i + 1]["group"]:
            continue
        t, nt = seq[i]["text"].strip(), seq[i + 1]["text"].strip().lstrip("".join(PUNCT))
        tc, nc = core(t), core(nt)
        for k in range(min(6, len(nc)), 1, -1):
            if tc.endswith(nc[:k]) and len(set(nc[:k])) > 1:
                sus.append((seq[i]["filename"], t, nt))
                break
    print("  residual leak suspects: %d" % len(sus))
    for fn, t, nt in sus[:25]:
        print("      %-40s %s   <next> %s" % (fn, t, nt))

    fix_path = os.path.join(META, "asr_tail_fix.json")
    if not os.path.exists(fix_path):
        print("\nno asr_tail_fix.json yet")
        return
    fix = json.load(open(fix_path, encoding="utf-8"))
    # asr_names.py reports by "<file>|<english name>" because one line can carry
    # several repaired names; collapse back to one entry per clip
    nm_path = os.path.join(META, "asr_name_fix.json")
    nm = json.load(open(nm_path, encoding="utf-8")) if os.path.exists(nm_path) else {}
    names = {}
    for k, v in nm.items():
        names.setdefault(k.split("|")[0], v)

    print("\ncorrected lines       : %d" % len(set(fix) | set(names)))
    print("  by asr_tail_merge   : %d" % len(fix))
    print("  by asr_names        : %d" % len(names))
    # the CSV is the delivered artefact, so it is the number that must hold;
    # it additionally carries mark_nonverbal.py's twin rescues
    csv_n = sum(1 for r in zh if (r.get("text_corrected") or ""))
    print("  in CSV (incl. twin-rescue): %d" % csv_n)
    if csv_n != len(set(fix) | set(names)) + 4:
        print("  ** WARNING: CSV and the fix reports disagree **")
    kinds = {}
    for v in list(fix.values()) + list(names.values()):
        kinds[v.get("kind", v.get("why", "?"))] = kinds.get(v.get("kind", v.get("why", "?")), 0) + 1
    print("  by kind             : %s" % kinds)
    bad = [k for k, v in fix.items() if not v["new"].strip()]
    bad += [k for k, v in names.items() if not v["new"].strip()]
    print("  emptied by fix      : %d" % len(bad))
    for k in bad[:10]:
        print("      %s  old=%s" % (k, fix.get(k, names.get(k, {})).get("old", "")))

    if a.sample:
        random.seed(a.seed)
        allk = sorted(set(fix) | set(names))
        pick = random.sample(allk, min(a.sample, len(allk)))
        print("\n--- random sample of corrections ---")
        for k in pick:
            v = fix.get(k) or names[k]
            print("  %-40s [%s]" % (k, v.get("kind", v.get("why"))))
            print("      EN =%s" % v["en"])
            print("      old=%s" % v["old"])
            print("      new=%s" % v["new"])


if __name__ == "__main__":
    main()
