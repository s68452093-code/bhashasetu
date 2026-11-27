"""In-window player for the embedded realistic ISL avatar demo."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtWebEngineWidgets import QWebEngineView


AVATAR_CLIPS = {
    "HELLO": ("HELLO", 3.33), "THANK_YOU": ("THANK YOU", 2.64),
    "PLEASE": ("PLEASE", 3.84), "SORRY": ("SORRY", 3.36),
    "YES": ("YES", 3.40), "NO": ("NO", 3.04),
    "HELP": ("HELP", 3.32), "WATER": ("WATER", 3.20),
    "FOOD": ("FOOD", 3.20),
}
AVATAR_REVIEW_STATUS = "pending fluent ISL signer review"


def find_demo_file(base_dir=None):
    root = Path(base_dir) if base_dir else Path(__file__).resolve().parent
    candidate = root / "realistic_isl_avatar_demo.html"
    return candidate if candidate.is_file() else None


def clip_key_for(gloss):
    value = "_".join(str(gloss or "").strip().upper().split())
    return value if value in AVATAR_CLIPS else None


def unsupported_glosses(glosses):
    return [str(gloss) for gloss in glosses if clip_key_for(gloss) is None]


class AvatarStage(QWebEngineView):
    clip_started = Signal(str)
    ready_changed = Signal(bool)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("avatarStage")
        self._ready = False
        path = find_demo_file()
        if path is None:
            self.failed.emit("realistic_isl_avatar_demo.html is missing from this folder.")
            return
        self.loadFinished.connect(self._on_loaded)
        self.load(QUrl.fromLocalFile(str(path.resolve())))

    @property
    def available(self):
        return self._ready

    def unavailable_reason(self):
        if find_demo_file() is None:
            return "The avatar demo file is missing from the Scout folder."
        return "The in-window avatar is still loading. Wait a moment and try again."

    def _on_loaded(self, ok):
        self._ready = bool(ok)
        self.ready_changed.emit(self._ready)
        if not ok:
            self.failed.emit("The avatar demo could not be loaded inside the app.")

    def play_gloss(self, gloss):
        key = clip_key_for(gloss)
        if not self._ready or key is None:
            return False
        selector = json.dumps(f'.sign-btn[data-sign="{key}"]')
        script = (f"(() => {{ const b = document.querySelector({selector}); "
                  "if (!b) return false; b.click(); return true; })()")
        self.page().runJavaScript(script, lambda result: None)
        self.clip_started.emit(key)
        return True
