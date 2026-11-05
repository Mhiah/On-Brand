"""Brand profiles and the deterministic linter that checks copy against them.

Pure Python, no Hermes imports: every verdict On-Brand gives is reproducible and unit-tested.
The LLM is only ever used to *repair* copy; whether copy passes is always decided here.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

HARD, SOFT = "hard", "soft"

_EMOJI_RE = re.compile(
    "[\U0001F1E6-\U0001F1FF\U0001F300-\U0001F5FF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF"
    "\U0001F900-\U0001F9FF\U0001FA70-\U0001FAFF☀-➿]")
_HASHTAG_RE = re.compile(r"(?<![\w#])#[A-Za-z0-9_]+")
_FIRST_PERSON_PLURAL_RE = re.compile(r"\b(we|we're|we've|we'll|we'd|us|our|ours|ourselves)\b",
                                     re.IGNORECASE)
_FIRST_PERSON_SINGULAR_RE = re.compile(r"\b(I|I'm|I've|I'll|I'd|me|my|mine)\b")

# --- Compliance packs ------------------------------------------------------------------------
# Each pack: forbidden claims (always hard) + a disclaimer that becomes required when a trigger
# topic appears in the copy.
PACKS: dict[str, dict[str, Any]] = {
    "crypto": {
        "label": "Crypto / Web3 promotion",
        "forbidden": [
            (r"\bguarantee(d|s)?\b[^.!?\n]{0,40}\b(returns?|profits?|gains?|yield|apy|income)\b",
             "promises guaranteed returns"),
            (r"\b(risk[- ]free|no[- ]risk|can'?t lose|cannot lose|zero risk)\b", "claims no risk"),
            (r"\b\d{2,4}\s?x\b(?!\s?(faster|cheaper|more efficient|speed))", "promises a price multiple"),
            (r"\b(to the moon|moon(ing)?\s+soon|next 100x|get rich|life[- ]changing (money|gains))\b",
             "hype price prediction"),
            (r"\b(buy|ape|load up)\s+(now|today|before it'?s too late)\b", "pushes an urgent buy"),
        ],
        "triggers": r"\b(price|token|invest(ing|ment)?|returns?|apy|apr|yield|airdrop|presale|"
                    r"staking rewards?|profit|pump|mint price|floor price)\b",
        "disclaimers": ["NFA", "not financial advice", "DYOR", "do your own research"],
        "disclaimer_hint": "add 'NFA' or 'DYOR' when talking about price, tokens or returns",
    },
    "health": {
        "label": "Health and fitness claims",
        "forbidden": [
            (r"\b(cures?|heals?|treats?)\b[^.!?\n]{0,30}\b(disease|cancer|diabetes|anxiety|depression)\b",
             "medical cure claim"),
            (r"\b(lose|drop)\s+\d+\s?(kg|lbs?|pounds)\s+in\s+\d+\s+(days?|weeks?)\b",
             "specific rapid weight-loss promise"),
            (r"\bguaranteed results?\b", "guaranteed results"),
        ],
        "triggers": r"\b(supplement|diet|weight|detox|cure|treatment|symptom)\b",
        "disclaimers": ["not medical advice", "consult a doctor", "consult your doctor"],
        "disclaimer_hint": "add 'not medical advice' when making health claims",
    },
}


@dataclass
class Profile:
    name: str
    display_name: str = ""
    person: str = "any"                  # "third" | "first" | "any"
    tone: str = ""                       # free text, used for generation and repair
    banned: list[str] = field(default_factory=list)
    preferred: dict[str, str] = field(default_factory=dict)  # wrong -> right (auto-fixed)
    required: list[str] = field(default_factory=list)        # must appear in every draft
    packs: list[str] = field(default_factory=list)           # compliance packs, e.g. ["crypto"]
    max_chars: int = 0                   # 0 = no limit (280 for X posts)
    max_hashtags: int = -1               # -1 = no limit
    max_emojis: int = -1
    max_exclamations: int = -1
    examples: list[str] = field(default_factory=list)        # on-brand sample lines
    notes: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Profile":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        clean = {k: v for k, v in (data or {}).items() if k in known}
        if not clean.get("name"):
            raise ValueError("profile needs a name")
        clean["name"] = slug(clean["name"])
        return cls(**clean)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def label(self) -> str:
        return self.display_name or self.name

    def brief(self) -> str:
        """The rules as a compact instruction block for the model."""
        lines = [f"Brand: {self.label}."]
        if self.person == "third":
            lines.append("Write about the brand in the THIRD person (use the brand name, 'the team', "
                         "'they'). Never 'we', 'us' or 'our'.")
        elif self.person == "first":
            lines.append("Write as the brand in the first person plural ('we', 'our').")
        if self.tone:
            lines.append(f"Tone: {self.tone}.")
        if self.banned:
            lines.append("Never use: " + ", ".join(repr(b) for b in self.banned) + ".")
        if self.preferred:
            lines.append("Spell these exactly: " + ", ".join(f"{v} (not {k})" for k, v in
                                                             self.preferred.items()) + ".")
        if self.required:
            lines.append("Every draft must include: " + ", ".join(repr(r) for r in self.required) + ".")
        limits = []
        if self.max_chars:
            limits.append(f"at most {self.max_chars} characters per draft")
        if self.max_hashtags >= 0:
            limits.append(f"at most {self.max_hashtags} hashtags")
        if self.max_emojis >= 0:
            limits.append(f"at most {self.max_emojis} emoji")
        if self.max_exclamations >= 0:
            limits.append(f"at most {self.max_exclamations} exclamation marks")
        if limits:
            lines.append("Limits: " + "; ".join(limits) + ".")
        for pack in self.packs:
            spec = PACKS.get(pack)
            if spec:
                lines.append(f"Compliance ({spec['label']}): no guaranteed returns, no 'risk-free', "
                             f"no hype price predictions; {spec['disclaimer_hint']}."
                             if pack == "crypto" else
                             f"Compliance ({spec['label']}): {spec['disclaimer_hint']}.")
        if self.examples:
            lines.append("Tone examples (copy the voice only; never reuse their facts, numbers or claims, and never state anything the user did not give you): " + " | ".join(self.examples[:3]))
        if self.notes:
            lines.append(f"Notes: {self.notes}")
        return " ".join(lines)


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s[:48] or "brand"


@dataclass
class Violation:
    rule: str
    severity: str
    detail: str
    fixable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Verdict:
    score: int
    violations: list[Violation]

    @property
    def passed(self) -> bool:
        return not any(v.severity == HARD for v in self.violations)

    @property
    def hard(self) -> list[Violation]:
        return [v for v in self.violations if v.severity == HARD]

    def to_dict(self) -> dict[str, Any]:
        return {"score": self.score, "passed": self.passed,
                "violations": [v.to_dict() for v in self.violations]}

    def summary(self) -> str:
        if not self.violations:
            return f"{self.score}/100, on brand"
        return f"{self.score}/100: " + "; ".join(v.detail for v in self.violations)


def _phrase_re(phrase: str) -> re.Pattern:
    escaped = re.escape(phrase.strip())
    left = r"\b" if re.match(r"\w", phrase.strip()) else ""
    right = r"\b" if re.search(r"\w$", phrase.strip()) else ""
    return re.compile(left + escaped + right, re.IGNORECASE)


def lint(text: str, profile: Profile) -> Verdict:
    text = text or ""
    found: list[Violation] = []

    def add(rule: str, severity: str, detail: str, fixable: bool = False) -> None:
        found.append(Violation(rule, severity, detail, fixable))

    # Voice / person.
    if profile.person == "third":
        hits = sorted({m.group(0).lower() for m in _FIRST_PERSON_PLURAL_RE.finditer(text)})
        if hits:
            add("person", HARD, f"first person ({', '.join(hits)}) in a third-person brand")
    elif profile.person == "first":
        if _FIRST_PERSON_SINGULAR_RE.search(text):
            add("person", SOFT, "singular 'I/me/my' in a brand that speaks as 'we'")

    # Vocabulary.
    for word in profile.banned:
        if word.strip() and _phrase_re(word).search(text):
            add("banned", HARD, f"banned word '{word}'")
    for wrong, right in profile.preferred.items():
        if not wrong.strip():
            continue
        pattern = re.compile(r"(?<!\w)" + re.escape(wrong) + r"(?!\w)")
        if pattern.search(text) and wrong != right:
            add("spelling", SOFT, f"'{wrong}' should be '{right}'", fixable=True)
    for phrase in profile.required:
        if phrase.strip() and not _phrase_re(phrase).search(text):
            add("required", HARD, f"missing required '{phrase}'")

    # Shape limits.
    if profile.max_chars and len(text) > profile.max_chars:
        add("length", HARD, f"{len(text)} characters, limit is {profile.max_chars}")
    if profile.max_hashtags >= 0:
        n = len(_HASHTAG_RE.findall(text))
        if n > profile.max_hashtags:
            add("hashtags", SOFT, f"{n} hashtag{'' if n == 1 else 's'}, limit is {profile.max_hashtags}")
    if profile.max_emojis >= 0:
        n = len(_EMOJI_RE.findall(text))
        if n > profile.max_emojis:
            add("emoji", SOFT, f"{n} emoji, limit is {profile.max_emojis}")
    if profile.max_exclamations >= 0:
        n = text.count("!")
        if n > profile.max_exclamations:
            add("exclamations", SOFT,
                f"{n} exclamation mark{'' if n == 1 else 's'}, limit is {profile.max_exclamations}")

    # Compliance packs.
    for pack in profile.packs:
        spec = PACKS.get(pack)
        if not spec:
            continue
        for pattern, label in spec["forbidden"]:
            if label and re.search(pattern, text, re.IGNORECASE):
                add("compliance", HARD, f"{spec['label']}: {label}")
        if re.search(spec["triggers"], text, re.IGNORECASE):
            has_disclaimer = any(_phrase_re(d).search(text) for d in spec["disclaimers"])
            if not has_disclaimer:
                add("disclaimer", HARD, f"{spec['label']}: {spec['disclaimer_hint']}")

    score = 100 - 22 * sum(v.severity == HARD for v in found) - 8 * sum(v.severity == SOFT for v in found)
    return Verdict(score=max(0, score), violations=found)


def mechanical_fix(text: str, profile: Profile) -> str:
    """Fixes that need no judgement: exact spellings of brand names and terms."""
    for wrong, right in profile.preferred.items():
        if wrong.strip() and wrong != right:
            text = re.sub(r"(?<!\w)" + re.escape(wrong) + r"(?!\w)", right, text)
    return text
