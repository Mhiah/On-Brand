"""Draft a brand profile from sample posts (the model proposes, the user keeps the final say)."""

from __future__ import annotations

import re
from typing import Any

from .rules import PACKS, Profile, slug

LEARN_INSTRUCTIONS = (
    "You are a brand strategist. Study the sample posts and describe the brand voice as enforceable "
    "rules. person: 'third' if the posts talk ABOUT the brand by name, 'first' if they speak AS the "
    "brand ('we', 'our'), else 'any'. tone: under 15 words. banned: words or phrases the brand clearly "
    "avoids that generic AI copy overuses (for example 'revolutionary', 'game-changer', 'unlock'), at "
    "most 8. preferred: exact spellings of the brand's names and terms as they appear in the samples, "
    "mapped from likely misspellings (for example {'RIALO': 'Rialo'}). max_emojis, max_hashtags, "
    "max_exclamations: the highest count used in any single sample. packs: include 'crypto' if the "
    "brand is about tokens, DeFi, NFTs or trading. examples: the 2 most typical samples verbatim.")

LEARN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "person": {"type": "string", "enum": ["third", "first", "any"]},
        "tone": {"type": "string"},
        "banned": {"type": "array", "items": {"type": "string"}},
        "preferred": {"type": "object", "additionalProperties": {"type": "string"}},
        "max_emojis": {"type": "integer"},
        "max_hashtags": {"type": "integer"},
        "max_exclamations": {"type": "integer"},
        "packs": {"type": "array", "items": {"type": "string"}},
        "examples": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["person", "tone", "banned", "preferred", "max_emojis", "max_hashtags",
                 "max_exclamations", "packs", "examples"],
}


def split_samples(raw: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"\n\s*(?:---+|===+)\s*\n|\n{2,}", raw or "") if p.strip()]
    return parts


def profile_from_learned(name: str, data: dict[str, Any], display_name: str = "") -> Profile:
    def as_int(key: str, default: int = -1) -> int:
        try:
            return max(-1, int(data.get(key, default)))
        except (TypeError, ValueError):
            return default

    preferred = data.get("preferred") or {}
    if not isinstance(preferred, dict):
        preferred = {}
    return Profile(
        name=slug(name),
        display_name=display_name or name,
        person=data.get("person") if data.get("person") in ("third", "first", "any") else "any",
        tone=str(data.get("tone") or "")[:160],
        banned=[str(b) for b in (data.get("banned") or [])][:8],
        preferred={str(k): str(v) for k, v in preferred.items() if str(k) != str(v)},
        packs=[p for p in (data.get("packs") or []) if p in PACKS],
        max_emojis=as_int("max_emojis"),
        max_hashtags=as_int("max_hashtags"),
        max_exclamations=as_int("max_exclamations"),
        examples=[str(e)[:280] for e in (data.get("examples") or [])][:3],
    )
