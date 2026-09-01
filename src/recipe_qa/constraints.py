"""Deterministic extraction of hard constraints from the question (SPEC §7.2).

Regex + vocabulary only — no LLM. This module is the authoritative source of
the aliases; SPEC §7.2 mirrors it.
"""

import re

from pydantic import BaseModel

DIET_ALIASES: dict[str, str] = {
    "vegan": "vegan",
    "vegetarian": "vegetarian",
    "veggie": "vegetarian",
    "meatless": "vegetarian",
    "gluten-free": "gluten-free",
    "gluten free": "gluten-free",
}

# "quick"/"fast"/"half an hour" → 30 minutes (SPEC §7.2)
_QUICK_WORDS = re.compile(r"\b(quick(ly)?|fast|speedy)\b", re.I)
_HALF_HOUR = re.compile(r"\bhalf an hour\b", re.I)
_BOUNDED_TIME = re.compile(
    r"(?:under|within|in|less than|at most|no more than|max(?:imum)?)\s+"
    r"(\d+)\s*(minutes?|mins?|hours?|hrs?)",
    re.I,
)
_N_MINUTE = re.compile(r"(\d+)[-\s]min(?:ute)?\b", re.I)
_EXCLUDE = re.compile(r"\b(?:without|with no|no)\s+([a-z]+)", re.I)
_EXCLUDE_STOPWORDS = {
    "more", "less", "matter", "idea", "time", "need", "the", "a", "an", "any",
    "one", "problem", "rush", "hurry",
}


class Constraints(BaseModel):
    max_time_minutes: int | None = None
    diet: str | None = None
    exclude_ingredients: list[str] = []

    def any(self) -> bool:
        return bool(self.max_time_minutes or self.diet or self.exclude_ingredients)


def _extract_time(question: str) -> int | None:
    match = _BOUNDED_TIME.search(question)
    if match:
        value = int(match.group(1))
        return value * 60 if match.group(2).lower().startswith("h") else value
    match = _N_MINUTE.search(question)
    if match:
        return int(match.group(1))
    if _HALF_HOUR.search(question):
        return 30
    if _QUICK_WORDS.search(question):
        return 30
    return None


def _extract_diet(question: str) -> str | None:
    lowered = question.lower()
    # longest alias first so "gluten free" wins over nothing and "vegan" is
    # not shadowed by "vegetarian" substring quirks
    for alias in sorted(DIET_ALIASES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(alias)}\b", lowered):
            return DIET_ALIASES[alias]
    return None


def _normalize_ingredient(word: str) -> str:
    word = word.lower()
    return word[:-1] if word.endswith("s") and len(word) > 3 else word


def _extract_exclusions(question: str) -> list[str]:
    exclusions = []
    for match in _EXCLUDE.finditer(question):
        word = _normalize_ingredient(match.group(1))
        if word not in _EXCLUDE_STOPWORDS and word not in exclusions:
            exclusions.append(word)
    return exclusions


def extract_constraints(question: str) -> Constraints:
    return Constraints(
        max_time_minutes=_extract_time(question),
        diet=_extract_diet(question),
        exclude_ingredients=_extract_exclusions(question),
    )
