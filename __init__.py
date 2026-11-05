"""On-Brand: brand voice and compliance rules Hermes can't break.

Hermes surfaces used (all public):
  pre_llm_call          inject the active brand's rules so first drafts start on brand
  transform_llm_output  lint every ```copy draft in the reply, auto-fix it, flag what can't be fixed
  pre_tool_call         block outbound posts (send / post / tweet / publish ...) that break the rules
  tools                 onbrand_check, onbrand_rules, onbrand_learn, onbrand_voiceover
  /onbrand              switch brands and manage profiles from any surface
"""

from __future__ import annotations

import json
import logging
import shlex
from typing import Any, Optional

from .onbrand import engine
from .onbrand.learn import LEARN_INSTRUCTIONS, LEARN_SCHEMA, profile_from_learned, split_samples
from .onbrand.rules import PACKS, Profile, lint, slug
from .onbrand.speakify import speakify
from .onbrand.store import PLUGIN_ID, Store

logger = logging.getLogger(__name__)

_STORE = Store()
_CTX: Any = None

STARTER_PROFILES = [
    Profile(name="nimbus", display_name="Nimbus Protocol", person="third",
            tone="calm, precise, quietly confident; explains before it sells",
            banned=["revolutionary", "game-changer", "unlock", "to the moon", "LFG"],
            preferred={"NIMBUS": "Nimbus", "nimbus protocol": "Nimbus Protocol", "defi": "DeFi"},
            packs=["crypto"], max_chars=280, max_hashtags=1, max_emojis=1, max_exclamations=0,
            examples=["Nimbus Protocol has opened a new feature to its community. The team explains "
                      "how it works first, then points to where the details live."]),
    Profile(name="pixel-pals", display_name="Pixel Pals", person="first",
            tone="playful, warm, community-first; short sentences",
            banned=["utility", "roadmap drop", "alpha leak"],
            preferred={"pixel pals": "Pixel Pals", "PIXEL PALS": "Pixel Pals"},
            packs=["crypto"], max_chars=280, max_hashtags=2, max_emojis=3, max_exclamations=2),
]


# --- model access --------------------------------------------------------------------------------

def _llm(messages: list[dict[str, str]], timeout: float) -> str:
    if _CTX is None or getattr(_CTX, "llm", None) is None:
        raise RuntimeError("no model access")
    result = _CTX.llm.complete(messages=messages, max_tokens=900, temperature=0.3,
                               timeout=max(3.0, float(timeout)), purpose="on-brand repair")
    return result.text or ""


def _repair_timeout() -> float:
    try:
        value = float(_CTX.get_config("repair_timeout", 12)) if _CTX is not None else 12.0
    except Exception:
        value = 12.0
    return min(max(value, 3.0), 20.0)


def _notify(event: str, payload: dict[str, Any]) -> None:
    """Tell the Desktop pane something changed (no-op when no Desktop window is attached)."""
    try:
        from hermes_cli.plugin_events import broadcast_plugin_event
        broadcast_plugin_event(PLUGIN_ID, event, payload)
    except Exception:  # pragma: no cover - Desktop is optional
        logger.debug("on-brand: desktop event not delivered", exc_info=True)


def _resolve(brand: Optional[str]) -> Optional[Profile]:
    return _STORE.get(brand) if brand else _STORE.active()


def _err(message: str) -> str:
    return json.dumps({"error": message})


# --- hooks -----------------------------------------------------------------------------------------

def _on_pre_llm_call(**kwargs: Any) -> Optional[dict[str, str]]:
    profile = _STORE.active()
    if profile is None:
        return None
    settings = _STORE.settings()
    parts = [f"[On-Brand is active for {profile.label}. Everything you write for this brand is "
             f"checked against its rules before the user sees it.]", profile.brief()]
    if settings.get("scope") != "all":
        parts.append(engine.DRAFT_INSTRUCTION)
    return {"context": " ".join(parts)}


def _on_transform_llm_output(response_text: str = "", **kwargs: Any) -> Optional[str]:
    profile = _STORE.active()
    if profile is None or not response_text:
        return None
    settings = _STORE.settings()
    try:
        result = engine.enforce(response_text, profile, _llm, scope=settings.get("scope", "drafts"),
                                auto_fix=bool(settings.get("auto_fix", True)),
                                max_repairs=int(settings.get("max_repairs", 2)),
                                call_timeout=_repair_timeout())
    except Exception:
        logger.warning("on-brand: enforcement failed; reply left unchanged", exc_info=True)
        return None
    for draft in result.drafts:
        event = _STORE.log({"kind": "draft", "brand": profile.name, "brand_label": profile.label,
                            "session_id": kwargs.get("session_id", ""), **draft.to_dict()})
        _notify("checked", event)
    return result.text if result.changed else None


def _on_pre_tool_call(tool_name: str = "", args: Optional[dict] = None, **kwargs: Any):
    settings = _STORE.settings()
    profile = _STORE.active()
    if profile is None or not settings.get("gate", True):
        return None
    if not engine.is_outbound(tool_name, settings.get("gate_patterns")):
        return None
    text = engine.outbound_text(args or {})
    if not text:
        return None
    verdict = lint(text, profile)
    outcome = "blocked" if not verdict.passed else "passed"
    event = _STORE.log({"kind": "gate", "brand": profile.name, "brand_label": profile.label,
                        "tool": tool_name, "outcome": outcome, "score_after": verdict.score,
                        "remaining": [v.detail for v in verdict.violations], "after": text[:600]})
    _notify("gate", event)
    if verdict.passed:
        return None
    return {"action": "block", "message": engine.gate_message(tool_name, profile, verdict)}


# --- tools -----------------------------------------------------------------------------------------

_BRAND_ARG = {"type": "string", "description": "Brand profile name. Defaults to the active brand."}

CHECK_SCHEMA = {
    "name": "onbrand_check",
    "description": ("Score copy against a brand's voice and compliance rules (0-100) and list every "
                    "rule it breaks. Set fix=true to get a corrected version. Use before publishing "
                    "anything for a brand, or when the user asks if copy is on brand."),
    "parameters": {"type": "object", "properties": {
        "text": {"type": "string", "description": "The copy to check."},
        "brand": _BRAND_ARG,
        "fix": {"type": "boolean", "description": "Return a corrected version too."}},
        "required": ["text"]},
}

RULES_SCHEMA = {
    "name": "onbrand_rules",
    "description": ("Create or update a brand profile's rules, or read them. Use when the user describes "
                    "how a brand should sound (person, tone, banned words, spellings, limits, "
                    "compliance). Lists replace the old list; omit a field to keep it."),
    "parameters": {"type": "object", "properties": {
        "brand": {"type": "string", "description": "Brand profile name (created if new)."},
        "display_name": {"type": "string"},
        "person": {"type": "string", "enum": ["third", "first", "any"]},
        "tone": {"type": "string"},
        "banned": {"type": "array", "items": {"type": "string"}},
        "preferred": {"type": "object", "additionalProperties": {"type": "string"},
                      "description": "Wrong spelling -> correct spelling."},
        "required": {"type": "array", "items": {"type": "string"}},
        "packs": {"type": "array", "items": {"type": "string", "enum": sorted(PACKS)}},
        "max_chars": {"type": "integer"}, "max_hashtags": {"type": "integer"},
        "max_emojis": {"type": "integer"}, "max_exclamations": {"type": "integer"},
        "examples": {"type": "array", "items": {"type": "string"}},
        "activate": {"type": "boolean", "description": "Make this the active brand."}},
        "required": ["brand"]},
}

LEARN_TOOL_SCHEMA = {
    "name": "onbrand_learn",
    "description": ("Draft a brand profile from 3 or more sample posts the user provides (their real, "
                    "approved copy). Saves it and returns the rules for the user to review."),
    "parameters": {"type": "object", "properties": {
        "brand": {"type": "string"}, "display_name": {"type": "string"},
        "samples": {"type": "array", "items": {"type": "string"}, "minItems": 2},
        "activate": {"type": "boolean"}},
        "required": ["brand", "samples"]},
}

VOICEOVER_SCHEMA = {
    "name": "onbrand_voiceover",
    "description": ("Turn on-brand copy into a voiceover script that reads naturally aloud: no "
                    "markdown, links or symbols, numbers and money spelled out, short sentences. "
                    "Checks the copy against the brand first."),
    "parameters": {"type": "object", "properties": {
        "text": {"type": "string"}, "brand": _BRAND_ARG,
        "ssml": {"type": "boolean", "description": "Add SSML pause tags for TTS engines."}},
        "required": ["text"]},
}


def tool_check(args: dict, **kwargs: Any) -> str:
    text = (args.get("text") or "").strip()
    if not text:
        return _err("text is required")
    profile = _resolve(args.get("brand"))
    if profile is None:
        return _err("No brand selected. Run /onbrand use <brand> or pass brand.")
    if args.get("fix"):
        result = engine.fix_draft(text, profile, _llm)
        out = {"brand": profile.label, **result.verdict_before.to_dict(),
               "fixed_text": result.after, "fixed_score": result.verdict_after.score,
               "outcome": result.outcome}
        _STORE.log({"kind": "check", "brand": profile.name, "brand_label": profile.label,
                    **result.to_dict()})
        return json.dumps(out)
    return json.dumps({"brand": profile.label, **lint(text, profile).to_dict()})


def tool_rules(args: dict, **kwargs: Any) -> str:
    name = (args.get("brand") or "").strip()
    if not name:
        return _err("brand is required")
    existing = _STORE.get(name)
    data = existing.to_dict() if existing else {"name": name, "display_name": name}
    for key in ("display_name", "person", "tone", "banned", "preferred", "required", "packs",
                "max_chars", "max_hashtags", "max_emojis", "max_exclamations", "examples"):
        if key in args and args[key] is not None:
            data[key] = args[key]
    try:
        profile = _STORE.save(Profile.from_dict(data))
    except (TypeError, ValueError) as exc:
        return _err(f"invalid rules: {exc}")
    if args.get("activate"):
        _STORE.set_active(profile.name)
    _notify("profiles", {"active": _STORE.active_name()})
    return json.dumps({"saved": profile.to_dict(), "active": _STORE.active_name() == profile.name,
                       "created": existing is None})


def tool_learn(args: dict, **kwargs: Any) -> str:
    name = (args.get("brand") or "").strip()
    samples = [s for s in (args.get("samples") or []) if isinstance(s, str) and s.strip()]
    if not name or len(samples) < 2:
        return _err("brand and at least 2 samples are required")
    if _CTX is None:
        return _err("model access unavailable")
    try:
        result = _CTX.llm.complete_structured(
            instructions=LEARN_INSTRUCTIONS,
            input=[{"type": "text", "text": "\n\n---\n\n".join(samples)}],
            json_schema=LEARN_SCHEMA, schema_name="brand_profile", temperature=0.2,
            max_tokens=900, timeout=40, purpose="on-brand learn")
    except Exception as exc:
        return _err(f"could not learn the profile: {exc}")
    if result.content_type != "json" or not isinstance(result.parsed, dict):
        return _err("the model did not return a usable profile; try again with clearer samples")
    profile = _STORE.save(profile_from_learned(name, result.parsed, args.get("display_name") or ""))
    if args.get("activate"):
        _STORE.set_active(profile.name)
    _notify("profiles", {"active": _STORE.active_name()})
    return json.dumps({"saved": profile.to_dict(), "review": "Check these rules with the user; "
                       "they can change any of them with onbrand_rules or /onbrand."})


def tool_voiceover(args: dict, **kwargs: Any) -> str:
    text = (args.get("text") or "").strip()
    if not text:
        return _err("text is required")
    profile = _resolve(args.get("brand"))
    checked = text
    verdict = None
    if profile is not None:
        result = engine.fix_draft(text, profile, _llm)
        checked, verdict = result.after, result.verdict_after
    spoken = speakify(checked, ssml=bool(args.get("ssml")))
    return json.dumps({"script": spoken.text, "brand": profile.label if profile else None,
                       "brand_score": verdict.score if verdict else None,
                       "spoken_changes": spoken.changes,
                       "words": len(spoken.text.split()),
                       "approx_seconds": round(len(spoken.text.split()) / 2.5)})


# --- /onbrand --------------------------------------------------------------------------------------

HELP = """On-Brand commands
  /onbrand                      status: active brand, settings, totals
  /onbrand list                 all brand profiles
  /onbrand use <brand>          turn enforcement on for a brand
  /onbrand off                  turn enforcement off
  /onbrand show [brand]         a brand's rules
  /onbrand new <brand>          create an empty profile
  /onbrand starter              add two example profiles to try
  /onbrand set <brand> <field> <value>
        fields: person (third|first|any), tone, max_chars, max_hashtags, max_emojis,
                max_exclamations, display_name
  /onbrand ban <brand> <word> [word ...]       /onbrand unban <brand> <word>
  /onbrand spell <brand> <wrong> <right>       always correct a spelling
  /onbrand require <brand> <phrase>            must appear in every draft
  /onbrand pack <brand> <crypto|health> [off]  compliance pack
  /onbrand check <text>         score text against the active brand
  /onbrand log                  recent checks, fixes and blocks
  /onbrand scope drafts|all     check ```copy blocks only (default) or whole replies
  /onbrand autofix on|off       rewrite off-brand drafts automatically
  /onbrand gate on|off          block off-brand outbound posts
  /onbrand delete <brand>"""

_INT_FIELDS = {"max_chars", "max_hashtags", "max_emojis", "max_exclamations"}


def _status() -> str:
    s = _STORE.settings()
    p = _STORE.active()
    st = _STORE.stats()
    head = f"On-Brand: {'ON for ' + p.label if p else 'off'}"
    return (f"{head}\nscope={s.get('scope')} autofix={'on' if s.get('auto_fix') else 'off'} "
            f"gate={'on' if s.get('gate') else 'off'}\n"
            f"checked {st['checked']} | passed {st['passed']} | fixed {st['fixed']} | "
            f"blocked {st['blocked']}\nType /onbrand help for commands.")


def _show(profile: Profile) -> str:
    d = profile.to_dict()
    lines = [f"{profile.label} ({profile.name})"]
    for key in ("person", "tone", "banned", "preferred", "required", "packs", "max_chars",
                "max_hashtags", "max_emojis", "max_exclamations", "examples"):
        val = d.get(key)
        if val in (None, "", [], {}, -1, 0):
            continue
        lines.append(f"  {key}: {val}")
    return "\n".join(lines)


def _edit(name: str, fn) -> str:
    profile = _STORE.get(name)
    if profile is None:
        return f"No brand '{name}'. Create it with /onbrand new {name}"
    fn(profile)
    _STORE.save(profile)
    _notify("profiles", {"active": _STORE.active_name()})
    return _show(profile)


def handle_command(raw: str) -> str:
    try:
        argv = shlex.split(raw or "")
    except ValueError:
        argv = (raw or "").split()
    if not argv:
        return _status()
    cmd, rest = argv[0].lower(), argv[1:]

    if cmd in ("help", "-h", "--help"):
        return HELP
    if cmd == "list":
        profiles = _STORE.profiles()
        if not profiles:
            return "No brands yet. Try /onbrand starter or /onbrand new <brand>."
        active = _STORE.active_name()
        return "\n".join(f"{'*' if k == active else ' '} {p.label} ({k})" for k, p in profiles.items())
    if cmd == "use" and rest:
        profile = _STORE.get(rest[0])
        if profile is None:
            return f"No brand '{rest[0]}'. See /onbrand list."
        _STORE.set_active(profile.name)
        _notify("profiles", {"active": profile.name})
        return f"On-Brand is ON for {profile.label}. Drafts are checked and fixed before you see them."
    if cmd == "off":
        _STORE.set_active(None)
        _notify("profiles", {"active": None})
        return "On-Brand is off."
    if cmd == "show":
        profile = _resolve(rest[0] if rest else None)
        return _show(profile) if profile else "No brand selected."
    if cmd == "new" and rest:
        if _STORE.get(rest[0]):
            return f"'{rest[0]}' already exists."
        profile = _STORE.save(Profile(name=slug(rest[0]), display_name=" ".join(rest)))
        return f"Created {profile.label}. Add rules with /onbrand set|ban|spell|pack, or ask Hermes."
    if cmd == "starter":
        for p in STARTER_PROFILES:
            if not _STORE.get(p.name):
                _STORE.save(Profile.from_dict(p.to_dict()))
        return "Added example brands: Nimbus Protocol (nimbus), Pixel Pals (pixel-pals). /onbrand use nimbus"
    if cmd == "delete" and rest:
        return f"Deleted {rest[0]}." if _STORE.delete(rest[0]) else f"No brand '{rest[0]}'."
    if cmd == "set" and len(rest) >= 3:
        field, value = rest[1].lower(), " ".join(rest[2:])
        if field == "person" and value not in ("third", "first", "any"):
            return "person must be third, first or any"
        if field in _INT_FIELDS:
            try:
                value = int(value)
            except ValueError:
                return f"{field} must be a number"
        elif field not in ("person", "tone", "display_name", "notes"):
            return f"Unknown field '{field}'. See /onbrand help."
        return _edit(rest[0], lambda p: setattr(p, field, value))
    if cmd == "ban" and len(rest) >= 2:
        return _edit(rest[0], lambda p: p.banned.extend(w for w in rest[1:] if w not in p.banned))
    if cmd == "unban" and len(rest) >= 2:
        return _edit(rest[0], lambda p: setattr(p, "banned", [w for w in p.banned
                                                                if w.lower() != rest[1].lower()]))
    if cmd == "spell" and len(rest) == 3:
        return _edit(rest[0], lambda p: p.preferred.__setitem__(rest[1], rest[2]))
    if cmd == "require" and len(rest) >= 2:
        return _edit(rest[0], lambda p: p.required.append(" ".join(rest[1:])))
    if cmd == "pack" and len(rest) >= 2:
        pack = rest[1].lower()
        if pack not in PACKS:
            return f"Unknown pack. Available: {', '.join(sorted(PACKS))}"
        off = len(rest) > 2 and rest[2].lower() == "off"
        return _edit(rest[0], lambda p: setattr(
            p, "packs", [x for x in p.packs if x != pack] + ([] if off else [pack])))
    if cmd == "check" and rest:
        profile = _STORE.active()
        if profile is None:
            return "No brand selected. /onbrand use <brand>"
        verdict = lint(" ".join(rest), profile)
        return f"{profile.label}: {verdict.summary()}"
    if cmd == "log":
        rows = _STORE.history(10)
        if not rows:
            return "Nothing checked yet."
        out = []
        for h in rows:
            what = h.get("tool") or h.get("kind")
            detail = "; ".join(h.get("fixed") or h.get("remaining") or []) or "clean"
            out.append(f"[{h.get('outcome')}] {h.get('brand_label')} {what} "
                       f"{h.get('score_before', h.get('score_after'))}->{h.get('score_after')}: {detail}")
        return "\n".join(out)
    if cmd == "scope" and rest and rest[0] in ("drafts", "all"):
        _STORE.update_settings(scope=rest[0])
        return f"Scope: {rest[0]}."
    if cmd in ("autofix", "gate") and rest and rest[0] in ("on", "off"):
        key = "auto_fix" if cmd == "autofix" else "gate"
        _STORE.update_settings(**{key: rest[0] == "on"})
        return f"{cmd} {rest[0]}."
    return HELP


# --- registration ----------------------------------------------------------------------------------

def register(ctx) -> None:
    global _CTX
    _CTX = ctx
    ctx.register_hook("pre_llm_call", _on_pre_llm_call)
    hold = False
    try:
        hold = bool(ctx.get_config("hold_stream", False))
    except Exception:
        logger.debug("on-brand: could not read hold_stream setting", exc_info=True)
    ctx.register_hook("transform_llm_output", _on_transform_llm_output, hold_stream=hold)
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)
    for schema, handler in ((CHECK_SCHEMA, tool_check), (RULES_SCHEMA, tool_rules),
                            (LEARN_TOOL_SCHEMA, tool_learn), (VOICEOVER_SCHEMA, tool_voiceover)):
        ctx.register_tool(name=schema["name"], toolset="on-brand", schema=schema, handler=handler)
    ctx.register_command("onbrand", handler=handle_command,
                         description="Brand voice rules: switch brands, manage rules, see fixes",
                         args_hint="[use <brand>|off|list|show|check|log|help]")
