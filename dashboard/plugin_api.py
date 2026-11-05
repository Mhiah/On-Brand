"""Backend routes for the On-Brand Desktop pane, mounted at /api/plugins/on-brand/.

Reads and writes the same JSON store as the agent half, so the pane and /onbrand always agree.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

_PKG_DIR = Path(__file__).resolve().parents[1] / "onbrand"
_PKG_NAME = "_on_brand_pane_core"


def _load_core():
    if _PKG_NAME in sys.modules:
        return sys.modules[_PKG_NAME]
    spec = importlib.util.spec_from_file_location(
        _PKG_NAME, _PKG_DIR / "__init__.py", submodule_search_locations=[str(_PKG_DIR)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[_PKG_NAME] = module
    spec.loader.exec_module(module)
    return module


_load_core()
from _on_brand_pane_core.rules import lint  # noqa: E402
from _on_brand_pane_core.store import Store  # noqa: E402

router = APIRouter()
_store = Store()


def _snapshot() -> dict[str, Any]:
    settings = _store.settings()
    profiles = _store.profiles()
    active = _store.active()
    return {
        "active": active.to_dict() if active else None,
        "profiles": [{"name": k, "label": p.label, "person": p.person, "packs": p.packs}
                     for k, p in profiles.items()],
        "settings": {k: settings.get(k) for k in ("scope", "auto_fix", "gate")},
        "stats": _store.stats(),
        "history": _store.history(25),
    }


@router.get("/state")
async def state() -> dict[str, Any]:
    return _snapshot()


@router.post("/use")
async def use(body: dict) -> dict[str, Any]:
    name = (body or {}).get("name")
    if name and _store.get(name) is None:
        raise HTTPException(status_code=404, detail=f"no brand '{name}'")
    _store.set_active(name or None)
    return _snapshot()


@router.post("/settings")
async def settings(body: dict) -> dict[str, Any]:
    body = body or {}
    changes: dict[str, Any] = {}
    if body.get("scope") in ("drafts", "all"):
        changes["scope"] = body["scope"]
    for key in ("auto_fix", "gate"):
        if isinstance(body.get(key), bool):
            changes[key] = body[key]
    if changes:
        _store.update_settings(**changes)
    return _snapshot()


@router.post("/check")
async def check(body: dict) -> dict[str, Any]:
    text = ((body or {}).get("text") or "").strip()
    profile = _store.get(body.get("brand")) if body.get("brand") else _store.active()
    if not text or profile is None:
        raise HTTPException(status_code=400, detail="text and an active brand are required")
    return {"brand": profile.label, **lint(text, profile).to_dict()}
