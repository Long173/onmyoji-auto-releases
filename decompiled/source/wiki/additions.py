"""Shikigami the game has and the dataset does not, entered by hand.

The dataset's Vietnamese source stopped publishing on 22 Apr 2026 and the
fandom batch was imported once, on 14 May. Anything the game added afterwards
is simply absent, and no re-sync will bring it in — so these were read straight
off the game's own Shikigami Tales pages on **23 Aug 2026** and typed up.

Where the numbers come from, and what is missing from them:

* names, skills, level-ups, taglines and the profile blurb are transcribed from
  the in-game pages, which is why they are in English — that is the language the
  game is displaying;
* ``name_vi`` is deliberately left empty rather than filled with a
  Sino-Vietnamese reading invented here. The UI falls back to ``name_en``, so
  the card shows the name the player sees in game, which is more use than a
  guess. Two thirds of the dataset already displays that way;
* **stats are absent.** The Tales pages do not show hp/attack, and an empty
  block reads as "not known" where zeros would read as "measured, and zero".
  Filling them in means reading them off a levelled shikigami's own page.

Added at load time, like the folding in :mod:`wiki.duplicates`, so a re-sync
from Supabase cannot drop them again. If the upstream data ever grows a record
with the same id, this steps aside and keeps upstream's version — the goal is to
stop being wrong about what exists, not to overrule a real source.
"""
from __future__ import annotations

from typing import Any, Dict, List

# Read off the game on 23 Aug 2026. See the module docstring before editing.
SOURCE_NOTE = "Đọc từ trang Shikigami Tales trong game, 23/08/2026"


def _skill(name: str, tagline: str, tags: str, description: str,
           levels: List[str]) -> Dict[str, Any]:
    """One skill in the shape ``Shikigami.from_row`` expects.

    The tagline and the tags are folded into the description rather than given
    fields of their own: the model has nowhere to put them, and losing them
    would lose the part that says what the skill is *for*.
    """
    head = "[%s] %s" % (tags, tagline) if tags else tagline
    return {
        "name": name,
        "description": "%s\n%s" % (head, description),
        "levels": [{"level": index + 2, "description": text}
                   for index, text in enumerate(levels)],
        "image": "",
    }


RECORDS: List[Dict[str, Any]] = [
    {
        "id": "bishamonten",
        "rarity": "SSR",
        "name_vi": "",
        "name_en": "Bishamonten",
        "name_jp": "",
        "friendly_name": [],
        "description": "",
        "lore": "One of the Seven Fuko no Kami, he presides over victory's "
                "blessing in games of chance. He looks vicious and violent, but "
                "he is truly proud, untamed and fiercely righteous. "
                "(VA: Masaya Fukunishi)",
        "obtain": [],
        "stats": {},
        "recommended_souls": [],
        "countered_by": [],
        "slot_mains": {},
        "role": [],
        "image": "shikigami/ssr/bishamonten.png",
        "source_url": "",
        "sort_index": 0,
        "skills": [
            _skill(
                "Thunder Fist", "Hey, I'm not an evil god, don't run!", "Damage",
                "Hmph, this blessing is not for you. Gather fortune into the "
                "body and strike the target for 100% ATK damage.",
                ["Increases damage to 105%.",
                 "Increases damage to 110%.",
                 "Increases damage to 115%.",
                 "Increases the damage to 120% and grants 1 stack of "
                 "Fortune Might."],
            ),
            _skill(
                "Discipline", "You lot, get over here and train together.",
                "Accelerator, Buff, Orb",
                "Effective Exclusively. With a rallying drumbeat and elephant's "
                "cheer, awaken Elephant Drum on the field, Sustainable for 3 "
                "turns. If Elephant Drum is already on the field, sound "
                "Elephant Drum instead, gaining 1 orb, 2 stacks of Fortune "
                "Might, and raising all allies' Move Bar by 10%.",
                ["When Elephant Drum sounds, the 2 enemies with the lowest HP "
                 "ratio lose 10% of their Max HP, up to 100% of Bishamonten's "
                 "starting ATK.",
                 "When an enemy loses HP, Bishamonten gains 1 stack of Heart "
                 "Drum (up to 6 stacks per action).",
                 "While Elephant Drum is on the field, this unit shares 30% of "
                 "the single-target damage allies take.",
                 "Upper Hand: Cast Discipline."],
            ),
            _skill(
                "Heavenbreaker Staff",
                "Bear a thousand weights, ring out boundless blessings!",
                "Damage",
                "With thunderous force, mercy finds its path. The drumsticks "
                "join into a long staff and consume all Fortune Might to attack "
                "the enemy target, dealing 300% ATK damage, with the damage "
                "multiplier increasing by an additional 30% for each Fortune "
                "Might consumed. After use, before the start of the next turn, "
                "sound Elephant Drum and increase the Move Bar boost to 20%.",
                ["Damage increased to 330%, with each stack's Fortune Might "
                 "coefficient boost increased to 35%.",
                 "While Elephant Drum is on the field, orb cost is reduced by 1.",
                 "Damage increased to 360%, with each stack's Fortune Might "
                 "coefficient boost increased to 40%.",
                 "If the damage dealt during the attack is absorbed, shared or "
                 "nullified, immediately gain 3 stacks of Fortune Might and "
                 "attack the same target 1 more time. This effect does not "
                 "trigger consecutively."],
            ),
        ],
    },
    {
        "id": "fuzenkitsune",
        "rarity": "SSR",
        "name_vi": "",
        "name_en": "Fuzenkitsune",
        "name_jp": "",
        "friendly_name": [],
        "description": "",
        "lore": "The true lord of Sand City, a wild fox blessed with the Lucky "
                "Eye, sees through the flow of fate and uses it to chase luck "
                "and dodge disaster. He looks lazy, carefree and fond of "
                "pleasure. (VA: Shinnosuke Tachibana)",
        "obtain": [],
        "stats": {},
        "recommended_souls": [],
        "countered_by": [],
        "slot_mains": {},
        "role": [],
        "image": "shikigami/ssr/fuzenkitsune.png",
        "source_url": "",
        "sort_index": 0,
        "skills": [
            _skill(
                "Dice Strike", "Watch the dice, catch it!", "Damage",
                "A flick to the forehead, no dodging allowed! Toss a dice at "
                "the enemy and deal 100% damage.",
                ["Increases damage to 105%.",
                 "Increases damage to 110%.",
                 "Increases damage to 115%.",
                 "Increases damage to 125%."],
            ),
            _skill(
                "Fate's Favor", "Lend me some of your luck!", "Weaken",
                "Effective Exclusively. Fortune rolls and fate flips. At the "
                "start of battle and each turn, gains or refreshes Phantom "
                "Dice. [Cast] has a 50% Base Chance to inflict Fortune Dice on "
                "enemy shikigami until the shield from Phantom Dice disappears.",
                ["Increases the base chance to 100%.",
                 "When Phantom Dice disappears or refreshes, increases Move Bar "
                 "by 20%.",
                 "Guaranteed to inflict on cast.",
                 "When obtains or refreshes Phantom Dice, all allies recover HP "
                 "equal to 98% of Fuzenkitsune's starting ATK."],
            ),
            _skill(
                "Fox Trick", "Bliss of gold, fortune turns upside down!",
                "Damage",
                "Fox shadows predict fate and reveal fortune or doom. Summon a "
                "magic circle to strike all enemies once, then command the fox "
                "shadow to attack one designated enemy once. If 600% of ATK is "
                "higher than HP when this skill is cast, it deals damage equal "
                "to 100% and 265% of ATK respectively. Otherwise, it deals "
                "damage equal to 10% and 21% of max HP respectively.",
                ["Fox shadow damage increases to 275% and 24% respectively.",
                 "Dealing damage does not trigger the enemy's Soul effects or "
                 "passives.",
                 "Fox shadow damage increases to 300% and 30% respectively.",
                 "If Fortune Dice is present, reduces skill orb cost by 1."],
            ),
        ],
    },
    {
        "id": "ignis_suzuhikohime",
        "rarity": "SP",
        "name_vi": "",
        "name_en": "Ignis Suzuhikohime",
        "name_jp": "",
        "friendly_name": [],
        "description": "",
        "lore": "Once bound to the snowy mountain, a Madame Saint who dances "
                "for the gods, she now shatters every chain of the past and "
                "leads her people beyond the peaks in search of a new tomorrow. "
                "(VA: Mikako Komatsu)",
        "obtain": [],
        "stats": {},
        "recommended_souls": [],
        "countered_by": [],
        "slot_mains": {},
        "role": [],
        "image": "shikigami/sp/ignis_suzuhikohime.png",
        "source_url": "",
        "sort_index": 0,
        "skills": [
            _skill(
                "Chiming Blade", "Well? Even the bell blade burns hot.",
                "Damage",
                "Thrusts the bell blade forward and strikes the target once, "
                "dealing 100% ATK damage.",
                ["Increases damage to 105%.",
                 "Increases damage to 110%.",
                 "Increases damage to 115%.",
                 "Increases damage to 125%."],
            ),
            _skill(
                "Blazing Vigil", "Heart aflame, night glows.",
                "Shield, Dmg UP, Dmg Reduced",
                "Effective Exclusively. At the start of battle, ignites the "
                "seven emotions, gaining Fire Veil equal to 220% of ATK until "
                "the next turn, while granting all allies 1 stack of Inner "
                "Fire. At the end of the turn, transfers a random ally's Inner "
                "Fire to self. [Cast] Remove all of the target's Controlling "
                "Effects.",
                ["Fire Veil increases to 240% of ATK.",
                 "Fire Veil increases to 260% of ATK.",
                 "Fire Veil increases to 280% of ATK.",
                 "At the end of a turn, if a Controlling Effect disappears, "
                 "gain Fire Veil equal to 280% of ATK and increase Move Bar."],
            ),
            _skill(
                "World Aflame", "One bell toll, a world aflame.",
                "Damage, Accelerator",
                "Effective Exclusively. Ring the bell as a command to transfer "
                "the chosen ally's Inner Fire to self and raise their Move Bar "
                "by 20%. Then deal 3 hits of damage at 35% ATK to all enemies. "
                "If no other allies carry Inner Fire, this skill is permanently "
                "replaced with Blazing Truth, and its level scales with World "
                "Aflame.",
                ["Increases damage to 40%.",
                 "Damage ignores enemy Soul effects.",
                 "Increases damage to 45%.",
                 "Increases damage to 50%."],
            ),
        ],
    },
]

# Ids the game has that are still not covered. Kept as a list rather than as a
# comment so a test can report it and nobody has to remember.
#
# The two frogs were never imported at all: the batch wrote their names onto the
# SSR rows `ngu_soan_tan` and `ngoc_tao_tien` instead of creating records. They
# would need their own pages read off the game the way these three were.
STILL_MISSING = ("miketsu_frog", "tamamo_no_mae_frog")

# Below this many rows, the thing being loaded is not the shikigami roster and
# these records have no business in it.
#
# Found by breaking three loader tests: they build a three-record dataset to
# check that rarity files are read and that the sync cache wins over the bundle,
# and this quietly appended three more, so a test about *loading* started
# failing on a count about *content*. The real roster is in the hundreds; a
# handful of rows is a fixture, an excerpt, or somebody else's data.
MIN_ROSTER = 50


def add_missing(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Append the hand-entered records that the given rows do not already have.

    Upstream wins on a clash: if the dataset grows a real record for one of
    these, that is the one to keep, and this quietly stops adding its own.

    Anything too small to be the roster is passed straight back — see
    ``MIN_ROSTER``.
    """
    if len(rows) < MIN_ROSTER:
        return list(rows)
    known = {row.get("id") for row in rows if isinstance(row, dict)}
    return list(rows) + [dict(record) for record in RECORDS
                         if record["id"] not in known]
