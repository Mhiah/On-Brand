"""Turn written assistant text into text that sounds natural when spoken aloud.

Pure functions, no Hermes imports, so everything here is unit-testable on its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# --- AI-isms that sound robotic when read out loud -------------------------------------------

_FILLER_OPENERS = [
    r"certainly[!,.]?\s*", r"absolutely[!,.]?\s*", r"of course[!,.]?\s*", r"sure thing[!,.]?\s*",
    r"great question[!,.]?\s*", r"i'?d be happy to help( you)?( with that)?[!,.]?\s*",
    r"i'?d be glad to help[!,.]?\s*", r"as an ai( language model)?,?\s*",
]
_OPENER_RE = re.compile(r"^(?:" + "|".join(_FILLER_OPENERS) + r")+", re.IGNORECASE)

_CONTRACTIONS = [
    (r"\bdo not\b", "don't"), (r"\bdoes not\b", "doesn't"), (r"\bdid not\b", "didn't"),
    (r"\bis not\b", "isn't"), (r"\bare not\b", "aren't"), (r"\bwas not\b", "wasn't"),
    (r"\bcannot\b", "can't"), (r"\bcan not\b", "can't"), (r"\bwill not\b", "won't"),
    (r"\bwould not\b", "wouldn't"), (r"\bshould not\b", "shouldn't"), (r"\bhave not\b", "haven't"),
    (r"\bit is\b", "it's"), (r"\bthat is\b", "that's"), (r"\bthere is\b", "there's"),
    (r"\bI am\b", "I'm"), (r"\bI will\b", "I'll"), (r"\bI have\b", "I've"), (r"\bwe are\b", "we're"),
    (r"\byou are\b", "you're"), (r"\bthey are\b", "they're"), (r"\blet us\b", "let's"),
]

_ABBREVIATIONS = [
    (r"\be\.g\.,?", "for example,"), (r"\bi\.e\.,?", "that is,"), (r"\betc\.", "and so on."),
    (r"\bvs\.?", "versus"), (r"\bapprox\.", "about"), (r"\bw/o\b", "without"), (r"\bw/\b", "with"),
]

_UNITS = {"kb": "kilobytes", "mb": "megabytes", "gb": "gigabytes", "tb": "terabytes",
          "ms": "milliseconds", "s": "seconds", "km": "kilometers", "kg": "kilograms"}

_SCALE = {"k": "thousand", "m": "million", "b": "billion"}

_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
         "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
         "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def number_to_words(n: int) -> str:
    """Spell out an integer (supports up to the billions)."""
    if n < 0:
        return "minus " + number_to_words(-n)
    if n < 20:
        return _ONES[n]
    if n < 100:
        tens, rest = divmod(n, 10)
        return _TENS[tens] + (f" {_ONES[rest]}" if rest else "")
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        return f"{_ONES[hundreds]} hundred" + (f" {number_to_words(rest)}" if rest else "")
    for size, name in ((10**9, "billion"), (10**6, "million"), (10**3, "thousand")):
        if n >= size:
            head, rest = divmod(n, size)
            return f"{number_to_words(head)} {name}" + (f" {number_to_words(rest)}" if rest else "")
    return str(n)


def _spell_number(raw: str) -> str:
    raw = raw.replace(",", "")
    if "." in raw:
        whole, frac = raw.split(".", 1)
        digits = " ".join(_ONES[int(d)] for d in frac if d.isdigit())
        return f"{number_to_words(int(whole or 0))} point {digits}"
    return number_to_words(int(raw))


# --- Markdown / structure removal ------------------------------------------------------------

_CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_LINK_RE = re.compile(r"\[([^\]]+)\]\((?:[^)]+)\)")
_BARE_URL_RE = re.compile(r"https?://\S+")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$", re.MULTILINE)
_BOLD_ITALIC_RE = re.compile(r"(\*\*\*|\*\*|\*|__|_)(.+?)\1")
_BULLET_RE = re.compile(r"^\s*(?:[-*+•])\s+(.*)$", re.MULTILINE)
_NUMBERED_RE = re.compile(r"^\s*\d+[.)]\s+(.*)$", re.MULTILINE)
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)
_EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF☀-➿]+")

_ORDINALS = ["First", "Second", "Third", "Fourth", "Fifth", "Sixth", "Seventh", "Eighth", "Ninth",
             "Tenth"]


@dataclass
class SpeakResult:
    text: str
    changes: list[str] = field(default_factory=list)
    score: int = 100  # how speakable the ORIGINAL text was (100 = already great)


def _speakability_penalties(text: str) -> list[tuple[str, int]]:
    pens: list[tuple[str, int]] = []
    if "```" in text:
        pens.append(("code block", 25))
    if _HEADING_RE.search(text):
        pens.append(("headings", 10))
    if _TABLE_ROW_RE.search(text):
        pens.append(("table", 20))
    if _BULLET_RE.search(text) or _NUMBERED_RE.search(text):
        pens.append(("list markup", 10))
    if _LINK_RE.search(text) or _BARE_URL_RE.search(text):
        pens.append(("links", 10))
    if _EMOJI_RE.search(text):
        pens.append(("emoji", 5))
    if _OPENER_RE.search(text.strip()):
        pens.append(("filler opener", 5))
    if "—" in text or "–" in text:
        pens.append(("em dashes", 5))
    long_sents = [s for s in re.split(r"(?<=[.!?])\s+", text) if len(s.split()) > 28]
    if long_sents:
        pens.append(("very long sentences", 10))
    return pens


def split_long_sentence(sentence: str, max_words: int = 22) -> list[str]:
    """Break an over-long sentence at natural spoken seams (conjunctions/semicolons/commas)."""
    words = sentence.split()
    if len(words) <= max_words:
        return [sentence]
    parts = re.split(r"(?<=[;:])\s+|,\s+(?=(?:and|but|so|which|because|while|then|or)\b)", sentence)
    out: list[str] = []
    buf = ""
    for part in parts:
        candidate = f"{buf}, {part}" if buf else part
        if buf and len(candidate.split()) > max_words:
            out.append(buf.rstrip(",;:") + ".")
            buf = part[0].upper() + part[1:] if part else part
        else:
            buf = candidate
    if buf:
        out.append(buf)
    return out if len(out) > 1 else [sentence]


def speakify(text: str, *, ssml: bool = False, max_sentence_words: int = 22,
             keep_emoji: bool = False) -> SpeakResult:
    """Rewrite ``text`` so a TTS voice (or a human reading it aloud) sounds natural."""
    original = text
    changes: list[str] = []
    penalties = _speakability_penalties(text)

    def note(label: str) -> None:
        if label not in changes:
            changes.append(label)

    # 1. Code, tables, links: say that they exist instead of reading them out.
    if _CODE_BLOCK_RE.search(text):
        text = _CODE_BLOCK_RE.sub(" I've put the code in the chat. ", text)
        note("code block replaced with a spoken pointer")
    if _TABLE_ROW_RE.search(text):
        text = _TABLE_ROW_RE.sub("", text)
        text = text.rstrip() + "\nThere's a table in the chat with the details."
        note("table replaced with a spoken pointer")
    text = _INLINE_CODE_RE.sub(r"\1", text)
    text = _LINK_RE.sub(r"\1", text)
    if _BARE_URL_RE.search(text):
        text = _BARE_URL_RE.sub("the link in the chat", text)
        note("urls replaced")

    # 2. Markdown noise.
    text = _HEADING_RE.sub(lambda m: m.group(1).rstrip(".:") + ".", text)
    for _ in range(2):
        text = _BOLD_ITALIC_RE.sub(r"\2", text)

    # 3. Lists become spoken sequences.
    counter = {"n": 0}

    def _bullet(m: re.Match) -> str:
        counter["n"] += 1
        idx = counter["n"] - 1
        lead = _ORDINALS[idx] if idx < len(_ORDINALS) else "Next"
        body = m.group(1).strip().rstrip(".")
        return f"{lead}, {body}." if idx == 0 else f"{'Then' if idx % 2 else 'Also'}, {body}."

    if _BULLET_RE.search(text) or _NUMBERED_RE.search(text):
        text = _NUMBERED_RE.sub(_bullet, _BULLET_RE.sub(_bullet, text))
        note("list spoken as a sequence")

    # 4. Filler openers, emoji, dashes.
    if _OPENER_RE.search(text.strip()):
        text = _OPENER_RE.sub("", text.strip(), count=1)
        text = text[:1].upper() + text[1:] if text else text
        note("filler opener removed")
    if not keep_emoji and _EMOJI_RE.search(text):
        text = _EMOJI_RE.sub("", text)
        note("emoji removed")
    text = re.sub(r"\s*[—–]\s*", ", ", text)

    # 5. Numbers, money, percent, units, abbreviations.
    def _money(m: re.Match) -> str:
        amount, scale = m.group(1), (m.group(2) or "").lower()
        spoken = _spell_number(amount)
        return f"{spoken} {_SCALE[scale]} dollars" if scale else f"{spoken} dollars"

    text = re.sub(r"\$(\d[\d,]*(?:\.\d+)?)\s?([kKmMbB])?\b", _money, text)
    text = re.sub(r"(\d[\d,]*(?:\.\d+)?)\s?%", lambda m: _spell_number(m.group(1)) + " percent", text)
    text = re.sub(r"\b(\d+(?:\.\d+)?)\s?(kb|mb|gb|tb|ms|km|kg)\b",
                  lambda m: f"{_spell_number(m.group(1))} {_UNITS[m.group(2).lower()]}", text,
                  flags=re.IGNORECASE)
    text = re.sub(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d{1,9})(?![\w.]*\d)(?!\.\d)",
                  lambda m: _spell_number(m.group(1)), text)
    for pat, repl in _ABBREVIATIONS:
        text = re.sub(pat, repl, text, flags=re.IGNORECASE)
    text = text.replace("&", " and ")

    # 6. Contractions for a conversational feel.
    for pat, repl in _CONTRACTIONS:
        def _swap(m: re.Match, _r: str = repl) -> str:
            return _r[:1].upper() + _r[1:] if m.group(0)[:1].isupper() else _r
        new = re.sub(pat, _swap, text, flags=re.IGNORECASE)
        if new != text:
            note("contractions")
        text = new

    # 7. Shorter sentences.
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    rebuilt: list[str] = []
    for s in sentences:
        pieces = split_long_sentence(s, max_sentence_words)
        if len(pieces) > 1:
            note("long sentences split")
        rebuilt.extend(pieces)
    text = " ".join(rebuilt)

    # 8. Tidy whitespace, optional SSML pauses.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", " ", text).strip()
    text = re.sub(r"\s+([,.!?])", r"\1", text)
    text = re.sub(r",\s*,", ",", text)
    if ssml:
        text = re.sub(r"(?<=[.!?])\s+", ' <break time="350ms"/> ', text)
        text = re.sub(r",\s+", ', <break time="150ms"/> ', text)
        text = f"<speak>{text}</speak>"
        note("ssml pauses added")

    score = max(0, 100 - sum(p for _, p in penalties))
    if text == original:
        changes = []
    return SpeakResult(text=text, changes=changes, score=score)
