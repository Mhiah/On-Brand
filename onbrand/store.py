"""Profiles, the active brand and the check history, as JSON in the plugin's data folder.

The agent half (hooks, tools, /onbrand) and the Desktop backend (dashboard/plugin_api.py) both read
and write through this module, so they always agree. Writes are atomic (temp file + rename).
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Optional

from .rules import Profile, slug

PLUGIN_ID = "on-brand"
HISTORY_LIMIT = 60
_LOCK = threading.RLock()


def _default_dir() -> Path:
    from plugins.plugin_storage import plugin_data_dir  # Hermes' documented per-plugin data dir
    return plugin_data_dir(PLUGIN_ID)


class Store:
    def __init__(self, base_dir: Optional[Path] = None) -> None:
        self._base = Path(base_dir) if base_dir else None

    @property
    def base(self) -> Path:
        base = self._base or _default_dir()
        base.mkdir(parents=True, exist_ok=True)
        return base

    # --- raw json -----------------------------------------------------------------------------
    def _read(self, name: str, default: Any) -> Any:
        path = self.base / name
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except FileNotFoundError:
            return default
        except (OSError, ValueError):
            return default

    def _write(self, name: str, data: Any) -> None:
        path = self.base / name
        fd, tmp = tempfile.mkstemp(dir=str(self.base), prefix=f".{name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    # --- profiles -----------------------------------------------------------------------------
    def profiles(self) -> dict[str, Profile]:
        raw = self._read("profiles.json", {})
        out: dict[str, Profile] = {}
        for key, data in (raw or {}).items():
            try:
                out[key] = Profile.from_dict(data)
            except (TypeError, ValueError):
                continue
        return out

    def get(self, name: str) -> Optional[Profile]:
        return self.profiles().get(slug(name))

    def save(self, profile: Profile) -> Profile:
        with _LOCK:
            raw = self._read("profiles.json", {}) or {}
            raw[profile.name] = profile.to_dict()
            self._write("profiles.json", raw)
        return profile

    def delete(self, name: str) -> bool:
        key = slug(name)
        with _LOCK:
            raw = self._read("profiles.json", {}) or {}
            if key not in raw:
                return False
            raw.pop(key)
            self._write("profiles.json", raw)
            if self.active_name() == key:
                self.set_active(None)
        return True

    # --- active brand + settings ------------------------------------------------------------------
    def settings(self) -> dict[str, Any]:
        defaults = {"active": None, "scope": "drafts", "auto_fix": True, "gate": True,
                    "max_repairs": 2}
        defaults.update(self._read("settings.json", {}) or {})
        return defaults

    def update_settings(self, **changes: Any) -> dict[str, Any]:
        with _LOCK:
            current = self.settings()
            current.update(changes)
            self._write("settings.json", current)
        return current

    def active_name(self) -> Optional[str]:
        return self.settings().get("active")

    def active(self) -> Optional[Profile]:
        name = self.active_name()
        return self.get(name) if name else None

    def set_active(self, name: Optional[str]) -> None:
        self.update_settings(active=slug(name) if name else None)

    # --- history (feeds the Desktop pane and /onbrand log) -------------------------------------------
    def log(self, event: dict[str, Any]) -> dict[str, Any]:
        event = {"ts": time.time(), **event}
        with _LOCK:
            history = self._read("history.json", []) or []
            history.append(event)
            self._write("history.json", history[-HISTORY_LIMIT:])
        return event

    def history(self, limit: int = 20) -> list[dict[str, Any]]:
        return list(reversed((self._read("history.json", []) or [])[-limit:]))

    def stats(self) -> dict[str, Any]:
        history = self._read("history.json", []) or []
        checked = len(history)
        fixed = sum(1 for h in history if h.get("outcome") == "fixed")
        blocked = sum(1 for h in history if h.get("outcome") == "blocked")
        passed = sum(1 for h in history if h.get("outcome") == "passed")
        return {"checked": checked, "fixed": fixed, "blocked": blocked, "passed": passed}
