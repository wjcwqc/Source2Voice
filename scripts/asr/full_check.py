# -*- coding: utf-8 -*-
"""综合体检 dataset.csv 中文 text 列：专有名词残留 / 繁体残留 / 幻觉 / 异常文本。只读 dry-run。"""
import csv
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import asr_names  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import s2v_config  # noqa: E402

CSV_PATH = os.path.join(s2v_config.META_DIR, "dataset.csv")

try:
    from opencc import OpenCC
    _cc = OpenCC("t2s")
    def trad_chars(s):
        return [ch for ch in s if _cc.convert(ch) != ch]
    print("[繁体检测] 使用 opencc (t2s)")
except Exception:
    TRAD_SET = set(
        "東車馬鳥魚風飛說時話語點國學龍鳳寶貝見長門關開張號書寫聽讀畫"
        "話誰說請謝語調論識議談讓詞試詩話許誤話謝選言誰請誰"
        "東車東軍軍隊車馬騎駕輪轉輕較載辦辦辦辦"
        "鳥鳳鳴鳳鳳飛風颳飄飛飯飲飲飯餘餘餘"
        "說語誒說誰誰誰話語誰"
        "點點點點點點點點點點點點"
        "學學學學學學"
        "見見見見見見"
        "門關開開關關開開關"
        "張張張張張張"
        "書書書書書書"
        "話話話話"
        "誰誰誰"
        "請請請"
        "讀讀讀"
        "聽聽聽"
    )
    def trad_chars(s):
        return [ch for ch in s if ch in TRAD_SET]
    print("[繁体检测] opencc 不可用，使用内置常见繁体字表（可能漏检生僻字）")

HALLU_KW = ["优优独播", "独播剧场", "请不吝", "点赞", "订阅", "转发",
            "打赏", "明镜", "点点栏目", "字幕组", "Amara", "YoYo"]
REPEAT = re.compile(r"(.)\1{6,}|(.{1,2})\2{6,}|(.{1,3})\3{5,}")


def main():
    rows = [r for r in csv.DictReader(open(CSV_PATH, encoding="utf-8-sig", newline=""))
            if r.get("language") == "schinese"]
    by_fn = {r["filename"]: r for r in rows}
    table = sorted(asr_names.name_table().items(), key=lambda kv: -len(kv[0]))

    name_fix, trad, halluc, anomaly = [], [], [], []

    for r in rows:
        fn, text, en = r["filename"], r["text"], (r["text_en_reference"] or "")
        c = asr_names.core(text)

        # 1) 专有名词残留
        if c:
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
                hit = asr_names.find_slot(c, z)
                new, tier, wrong = None, None, None
                if hit:
                    i, L, target, tier, _, _ = hit
                    wrong = c[i:i + L]
                    pos = [k for k, ch in enumerate(text) if ch.isalnum()]
                    new = text[:pos[i]] + target + text[pos[i + L - 1] + 1:]
                else:
                    twin = ("sylph_" + fn[11:] if fn.startswith("helmet_sylph_")
                            else "helmet_sylph_" + fn[6:] if fn.startswith("sylph_") else None)
                    if twin and twin in by_fn and z in asr_names.core(by_fn[twin]["text"]):
                        new, tier, wrong = by_fn[twin]["text"], "twin", c
                if new and new != text:
                    name_fix.append((fn, enn, expected := z, wrong, tier, en, text, new))

        # 2) 繁体
        tc = trad_chars(text)
        if tc:
            trad.append((fn, "".join(sorted(set(tc))), text))

        # 3) 幻觉
        if any(k in text for k in HALLU_KW):
            halluc.append((fn, text))
        elif REPEAT.search(text) and not re.fullmatch(r"[啊哈呃哦嗯唉呀嘿哈]+[。!！?？,，\s]*", text):
            # 重复循环且非纯叹词
            if not re.search(r"[A-Za-z]", en):  # 英文不是喊声才可疑
                anomaly.append((fn, "repeat", text))

        # 4) 含 ASCII 字母/数字
        if re.search(r"[A-Za-z0-9]", text):
            anomaly.append((fn, "ascii", text))

        # 5) 空 / 过长
        if not text.strip():
            anomaly.append((fn, "empty", text))
        elif len(text) > 40:
            anomaly.append((fn, "long", text))

    print(f"\n共 {len(rows)} 条")
    print(f"\n=== [1] 专有名词残留错字 {len(name_fix)} 处 ===")
    for fn, enn, exp, wrong, tier, en, old, new in name_fix:
        print(f"{fn}  [{enn}] {tier}")
        print(f"   EN: {en}")
        print(f"   旧: {old}   (错写 {wrong} → 应 {exp})")
        print(f"   新: {new}")
    print(f"\n=== [2] 繁体残留 {len(trad)} 条 ===")
    for fn, chars, text in trad:
        print(f"{fn}  繁体字[{chars}]  {text}")
    print(f"\n=== [3] 幻觉 {len(halluc)} 条 ===")
    for fn, text in halluc:
        print(f"{fn}  {text}")
    print(f"\n=== [4] 异常文本 {len(anomaly)} 条 ===")
    for fn, kind, text in anomaly:
        print(f"{fn}  [{kind}]  {text}")


if __name__ == "__main__":
    main()
