"""Deterministic safety gate (SPEC §4 stage 2, §7.3; ADR-003).

The trigger list below is the authoritative one mirrored in SPEC §7.3.
Additions require updating SPEC in the same commit. Note the declared
boundary: "gluten-free" alone is a diet preference (constraint parser);
intolerance/allergy phrasing is safety.
"""

import re

SAFETY_TRIGGERS = [
    "allergy",
    "allergies",
    "allergic",
    "allergen",
    "allergens",
    "nut-free",
    "nut free",
    "peanut-free",
    "peanut free",
    "gluten intolerance",
    "gluten intolerant",
    "celiac",
    "coeliac",
    "lactose intolerance",
    "lactose intolerant",
    "safe for",
    "safe to eat",
    "is it safe",
    "pregnant",
    "pregnancy",
    "raw egg",
    "raw eggs",
    "food poisoning",
]

_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(t) for t in SAFETY_TRIGGERS) + r")\b", re.I
)


def is_safety_question(question: str) -> bool:
    return bool(_PATTERN.search(question))
