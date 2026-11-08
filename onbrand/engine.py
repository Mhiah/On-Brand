"""Enforcement: find drafts in a reply, lint them, fix them, and gate outbound posts.

No Hermes imports. The model is passed in as ``llm(messages) -> str`` so the whole loop is testable
with a fake model, and so a broken or slow model can never stop a reply (we fail open, and say so).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .rules import Profile, Verdict, lint, mechanical_fix

LLM = Callable[[list[dict[str, str]], float], str]  # (messages, timeout_seconds) -> text

# Copy goes in ```copy blocks: they render as copy-ready boxes in every Hermes surface, and they let
# On-Brand enforce the drafts without touching Hermes' own chatter around them.
_DRAFT_RE = re.compile(r"```(?:copy|draft|post|tweet)[^\n]*\n(.*?)\n?```", re.DOTALL | re.IGNORECASE)

DRAFT_INSTRUCTION = (
    "Put every piece of copy you write for this brand (posts, tweets, threads, captions, emails, "
    "announcements) in its own fenced block that starts with ```copy and ends with ```. One block per "
    "post. Keep explanations outside the blocks.")


@dataclass
class DraftResult:
    before: str
    after: str
    verdict_before: Verdict
    verdict_after: Verdict
    outcome: str            # passed | fixed | flagged
    attempts: int = 0
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"outcome": self.outcome, "attempts": self.attempts, "note": self.note,
                "score_before": self.verdict_before.score, "score_after": self.verdict_after.score,
                "fixed": [v.detail for v in self.verdict_before.violations
                          if v.detail not in {w.detail for w in self.verdict_after.violations}],
                "remaining": [v.detail for v in self.verdict_after.violations],
                "before": self.before[:600], "after": self.after[:600]}


@dataclass
class EnforceResult:
    text: str
    changed: bool
    drafts: list[DraftResult] = field(default_factory=list)


def extract_drafts(text: str) -> list[re.Match]:
    return list(_DRAFT_RE.finditer(text or ""))


def _clean_model_output(text: str) -> str:
    text = (text or "").strip()
    fence = re.match(r"^```[^\n]*\n(.*?)\n?```$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    return text


def repair_messages(draft: str, profile: Profile, verdict: Verdict) -> list[dict[str, str]]:
    problems = "\n".join(f"- {v.detail}" for v in verdict.violations)
    return [
        {"role": "system", "content": (
            "You are a meticulous brand copy editor. Rewrite the draft so it follows EVERY brand rule "
            "and fixes EVERY listed problem. Keep the meaning, facts, names, numbers and links. Do not "
            "add claims. Return only the rewritten copy: no quotes, no labels, no commentary.")},
        {"role": "user", "content": (
            f"BRAND RULES\n{profile.brief()}\n\nPROBLEMS FOUND\n{problems}\n\nDRAFT\n{draft}")},
    ]


def fix_draft(draft: str, profile: Profile, llm: Optional[LLM], *, max_repairs: int = 2,
              deadline: Optional[float] = None, call_timeout: float = 12.0) -> DraftResult:
    first = lint(draft, profile)
    if not first.violations:
        return DraftResult(draft, draft, first, first, "passed")

    best_text, best = draft, first
    candidate = mechanical_fix(draft, profile)
    if candidate != draft:
        verdict = lint(candidate, profile)
        if verdict.score >= best.score:
            best_text, best = candidate, verdict

    attempts, note = 0, ""
    while best.violations and llm is not None and attempts < max_repairs:
        remaining = (deadline - time.monotonic()) if deadline else call_timeout
        if remaining < 3:
            note = "time budget used up"
            break
        attempts += 1
        try:
            raw = llm(repair_messages(best_text, profile, best), min(call_timeout, remaining))
            candidate = mechanical_fix(_clean_model_output(raw), profile)
        except Exception as exc:  # model down, timeout, no credentials: never block the reply
            note = f"repair unavailable ({type(exc).__name__})"
            break
        if not candidate:
            continue
        verdict = lint(candidate, profile)
        if verdict.score > best.score or (verdict.passed and not best.passed):
            best_text, best = candidate, verdict

    if not best.violations:
        outcome = "fixed"
    elif best.passed and best_text != draft:
        outcome = "fixed"   # only soft issues left
    else:
        outcome = "flagged"
    return DraftResult(draft, best_text, first, best, outcome, attempts, note)


def _flag_note(result: DraftResult) -> str:
    issues = "; ".join(v.detail for v in result.verdict_after.violations)
    return f"\n\nOn-Brand: still off brand ({result.verdict_after.score}/100): {issues}"


def enforce(text: str, profile: Profile, llm: Optional[LLM], *, scope: str = "drafts",
            auto_fix: bool = True, max_repairs: int = 2, budget_s: float = 24.0,
            call_timeout: float = 12.0) -> EnforceResult:
    """Check (and, with auto_fix, repair) the drafts in a reply. ``scope='all'`` treats the whole
    reply as one draft."""
    if not text:
        return EnforceResult(text, False)
    repairs = max_repairs if auto_fix else 0
    model = llm if auto_fix else None
    deadline = time.monotonic() + budget_s
    opts = {"max_repairs": repairs, "deadline": deadline, "call_timeout": call_timeout}

    if scope == "all":
        result = fix_draft(text, profile, model, **opts)
        if not auto_fix:
            result.after = text
        out = result.after + (_flag_note(result) if result.outcome == "flagged" else "")
        return EnforceResult(out, out != text, [result])

    matches = extract_drafts(text)
    if not matches:
        return EnforceResult(text, False)
    pieces: list[str] = []
    results: list[DraftResult] = []
    cursor = 0
    for m in matches:
        body = m.group(1)
        result = fix_draft(body, profile, model, **opts)
        if not auto_fix:
            result.after = body
        results.append(result)
        block = m.group(0).replace(body, result.after, 1) if result.after != body else m.group(0)
        if result.outcome == "flagged":
            block += _flag_note(result)
        pieces.append(text[cursor:m.start()])
        pieces.append(block)
        cursor = m.end()
    pieces.append(text[cursor:])
    out = "".join(pieces)
    return EnforceResult(out, out != text, results)


# --- outbound gate ---------------------------------------------------------------------------------

DEFAULT_GATE_PATTERNS = [r"send", r"post", r"tweet", r"publish", r"reply", r"cast", r"(^|_)dm($|_)",
                         r"broadcast", r"announce", r"webhook", r"create_message", r"discord", r"telegram", r"slack", r"schedule_(post|tweet)", r"create_(post|tweet)"]
_TEXT_KEYS = ("text", "content", "message", "body", "caption", "tweet", "status", "post", "html",
              "markdown", "description", "comment", "reply")
_NEVER_GATE = {"onbrand_check", "onbrand_voiceover", "onbrand_learn", "read_file", "search_files",
               "web_search", "web_extract", "session_search", "react_to_message"}


def is_outbound(tool_name: str, patterns: Optional[list[str]] = None) -> bool:
    name = (tool_name or "").lower()
    if not name or name in _NEVER_GATE:
        return False
    return any(re.search(p, name) for p in (patterns or DEFAULT_GATE_PATTERNS))


def outbound_text(args: Any) -> str:
    """Collect the human-readable copy a tool call would send."""
    found: list[str] = []

    def walk(node: Any, key: str = "", depth: int = 0) -> None:
        if depth > 4:
            return
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, str(k).lower(), depth + 1)
        elif isinstance(node, list):
            for v in node:
                walk(v, key, depth + 1)
        elif isinstance(node, str) and key in _TEXT_KEYS and node.strip():
            found.append(node.strip())

    walk(args)
    return "\n\n".join(found)


def gate_message(tool_name: str, profile: Profile, verdict: Verdict) -> str:
    issues = "\n".join(f"- {v.detail}" for v in verdict.hard)
    return (f"On-Brand blocked {tool_name}: this copy breaks {profile.label}'s brand rules "
            f"({verdict.score}/100).\n{issues}\nRewrite the copy to fix every point above, then call "
            f"{tool_name} again. (Brand rules: {profile.brief()})")
