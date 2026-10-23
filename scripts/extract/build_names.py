"""Build an authoritative EN->ZH proper-noun table straight from Dota 2's own files.

Dark Willow has official English subtitles (resource/subtitles/subtitles_sylph_english.txt)
but no Chinese ones, so the Chinese text had to be produced by ASR.  ASR gets the
sentences right but mangles proper nouns -- 变体精灵 (Morphling) came out as
遍体精灵, 沉默术士 (Silencer) as 陈默舒适, 辉耀 (Radiance) as 灰药.

The game ships the correct Chinese spelling of every hero, item and lore name in
its localization files.  This script extracts them so a later pass can repair the
ASR text by cross-referencing the English subtitle, which names the entity
explicitly ("Never stop changing, Morphling.").

Sources inside pak01_dir.vpk
    resource/localization/*_english.txt     token -> English string
    resource/localization/*_schinese.txt    token -> Chinese string
    scripts/npc/heroes/npc_dota_hero_*.txt  workshop_guide_name (EN display name)

Output: tools/dota_names.json
"""
import glob
import json
import os
import re
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import s2v_config  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

GAME = s2v_config.LANG_PACKAGES["english"]
LOC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_loc")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dota_names.json")

# Lore nouns that appear in Dark Willow's own lines but never in a tooltip, so
# they cannot be paired by token.  Each entry names the token its Chinese form
# was read out of, so the claim can be re-checked.
TERMS = {
    "Selemene": ("赛莉蒙妮", "DOTA_Tooltip_ability_mirana_selemenes_faithful"),
    "Nothl Realm": ("虚无之境", "DOTA_Tooltip_ability_dota_dazzle_nothl_projection_Lore"),
    # EN "demon hunters ... bartering ..." / ZH "在悲玫城用一些残件做交换"
    "Weeping Rose": ("悲玫城", "DOTA_Tooltip_ability_item_imp_claw_Lore"),
    "Roseleaf": ("玫叶城", "DOTA_Item_Desc_Copy_of_Hearts_of_Misrule"),
    "Stonehall": ("石堂城", "StoreBanner_Header_LC_StonehallRoyalGuard"),
    "Mireska": ("米瑞斯嘉", "Debut_DuelingFates_DarkWillow_Mireska"),
    "Mireska Sunbreeze": ("米瑞斯嘉·晴风", "npc_dota_hero_dark_willow_bio"),
    "Yunero": ("尤涅若", "DOTA_Tooltip_ability_juggernaut_blade_fury_Lore"),
    "Revtel": ("瑞文特尔", "npc_dota_hero_dark_willow_bio"),
    "Jex": ("杰克斯", "npc_dota_hero_dark_willow_bio"),
    "Donte": ("唐特", "Debut_DuelingFates_Pangolier_Donte"),
    "Dark Willow": ("邪影芳灵", "Debut_DuelingFates_DarkWillow_Name"),
    "Viper": ("蝮蛇", "DOTA_Tooltip_ability_viper_poison_attack_Description"),
    # These three exist only in Dark Willow's own lines, so the game has no
    # official spelling.  The Chinese voice acting is nonetheless consistent,
    # and ASR reproduces the same sound most often correctly -- so the modal
    # form across the corpus is taken as the intended one.  Counts recorded so
    # the vote can be audited.
    "Jasper Circle": ("圣刀会", "corpus 7 圣刀会 / 3 圣灯会 / 1 圣道会 / 1 圣诞会"),
    "Quoidge": ("求师岭", "corpus 4 求师岭 / 1 球狮岭 / 1 球师岭"),
    "Omexe": ("欧梅克斯", "corpus 3 欧梅克斯 / 1 欧美克斯"),
}


def parse(path):
    """Flatten a Valve KV localization file into {token: string}."""
    txt = open(path, encoding="utf-8-sig", errors="replace").read()
    return dict(re.findall(r'^\s*"([^"]+)"\s+"((?:[^"\\]|\\.)*)"\s*$', txt, re.M))


def ensure_loc():
    """Extract the localization + hero-definition files out of the game if absent.

    Cached under tools/_loc so repeat runs are instant; the cache is disposable
    and can be deleted at any time.
    """
    if glob.glob(os.path.join(LOC, "*_schinese.txt")):
        return
    if not os.path.exists(GAME):
        sys.exit("game not found at %s (and no cached %s)" % (GAME, LOC))
    from vpk import Vpk
    os.makedirs(LOC, exist_ok=True)
    v = Vpk(GAME)
    n = 0
    for e in v.entries:
        keep = (e.path.startswith("resource/localization/")
                and e.path.endswith(("_schinese.txt", "_english.txt"))) \
            or e.path.startswith("scripts/npc/heroes/") \
            or e.path == "resource/subtitles/subtitles_sylph_english.txt"
        if not keep:
            continue
        flat = e.path.replace("resource/localization/", "").replace("/", "__")
        if e.path.startswith("scripts/npc/heroes/"):
            flat = "heroes_" + os.path.basename(e.path)
        open(os.path.join(LOC, flat), "wb").write(v.data(e))
        n += 1
    print("extracted %d files -> %s" % (n, LOC))


def load_loc():
    ensure_loc()
    en, zh = {}, {}
    for p in glob.glob(os.path.join(LOC, "*_english.txt")):
        en.update(parse(p))
    for p in glob.glob(os.path.join(LOC, "*_schinese.txt")):
        zh.update(parse(p))
    return en, zh


def heroes():
    """EN display name -> official Chinese name, via #npc_dota_hero_<internal>."""
    en, zh = load_loc()
    zhmap = {k[1:]: v for k, v in zh.items() if k.startswith("#npc_dota_hero_")}
    out = {}
    for p in glob.glob(os.path.join(LOC, "heroes_npc_dota_hero_*.txt")):
        t = open(p, encoding="utf-8-sig", errors="replace").read()
        m = re.search(r'"workshop_guide_name"\s+"([^"]+)"', t)
        if not m:
            continue
        internal = "npc_dota_hero_" + os.path.basename(p)[len("heroes_npc_dota_hero_"):-4]
        z = zhmap.get(internal)
        if z:
            out[m.group(1)] = z
    return out


def items():
    """EN item name -> official Chinese name, paired by tooltip token."""
    en, zh = load_loc()
    out = {}
    for k, v in zh.items():
        if not k.startswith("DOTA_Tooltip_Ability_item_") or k not in en:
            continue
        e = en[k]
        # skip recipes, notes and anything templated
        if not e or not v or "%" in v or "<" in v or len(v) > 8:
            continue
        if "Recipe" in e or "recipe" in k:
            continue
        out[e] = v
    return out


def main():
    data = {
        "heroes": heroes(),
        "items": items(),
        "terms": {k: v[0] for k, v in TERMS.items()},
        "term_source": {k: v[1] for k, v in TERMS.items()},
    }
    json.dump(data, open(OUT, "w", encoding="utf-8"), ensure_ascii=False,
              indent=1, sort_keys=True)
    print("heroes : %d" % len(data["heroes"]))
    print("items  : %d" % len(data["items"]))
    print("terms  : %d" % len(data["terms"]))
    print("-> %s" % OUT)


if __name__ == "__main__":
    main()
