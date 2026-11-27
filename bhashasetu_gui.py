"""BHASHASETU 1.0 - PySide6 desktop interface.

The GUI intentionally does not implement sign-language recognition, camera capture,
text-to-speech, or model logic. It connects to a backend module that exports the
functions listed in the BHASHASETU integration contract.

Default backend module: bhashasetu_backend
Override with the BHASHASETU_BACKEND_MODULE environment variable.

UI changes in this revision (no contract or threading change):

* one theme table instead of scattered hex codes, with a Dark / Light switch
  that is remembered between launches;
* a clearer hierarchy: the current sign is the biggest thing on screen, the
  camera is next, and the sentence plus its one primary action sit beside it;
* status is always a marker *and* words, never colour alone;
* keyboard access: Ctrl+Enter to speak, Esc to stop speech, Ctrl+Shift+C to
  start or stop the camera, Ctrl+L to clear, Ctrl+D to switch theme;
* confidence is a bar with a percentage beside it, not a number alone;
* the last few recognised signs are shown as chips so a demo is followable;
* glyphs that Windows fonts often draw as empty boxes were removed.
"""
from __future__ import annotations

import importlib
import inspect
import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from PySide6.QtCore import QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QFont, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QLineEdit,
    QPushButton,
    QSlider,
    QStackedWidget,
    QSizePolicy,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

try:                                     # local module, shipped beside this file
    from avatar_stage import (
        AVATAR_CLIPS,
        AVATAR_REVIEW_STATUS,
        AvatarStage,
        clip_key_for,
        find_demo_file,
        unsupported_glosses,
    )
except Exception:                        # keep the app usable without the module
    AvatarStage = None                   # type: ignore[assignment]

    def clip_key_for(gloss):             # type: ignore[misc]
        return None

    def find_demo_file(base_dir=None):   # type: ignore[misc]
        return None

    def unsupported_glosses(glosses):    # type: ignore[misc]
        return list(glosses)

    AVATAR_CLIPS = {}
    AVATAR_REVIEW_STATUS = "pending fluent ISL signer review"


APP_TITLE = "BHASHASETU 1.0"
ROOT = Path(__file__).resolve().parent
DEFAULT_BACKEND_MODULE = "bhashasetu_backend"
POLL_INTERVAL_MS = 60
RECENT_SIGN_LIMIT = 6


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------
#: Tokens are plain strings so the stylesheet below can be built by replacing
#: ``$name`` placeholders. No brace escaping, so the QSS stays readable.
THEMES: dict[str, dict[str, str]] = {
    "light": {
        "home_bg": "#F7F3ED",
        "home_card": "#FFFDF9",
        "home_line": "#E4DCD0",
        "home_text": "#171512",
        "home_muted": "#6E665C",
        "home_orange": "#C4562A",
        "home_green": "#1E7A4B",
        "home_mono": "#857C70",

        "nav_on": "#0A6E6C",
        "nav_off": "#5D6E82",
        "nav_hover": "#E7EEF5",
        "nav_underline": "#0A6E6C",

        "stage_chip_bg": "#EAF6F4",
        "stage_chip_text": "#0A5F5D",

        "window": "#EEF2F7",
        "card": "#FFFFFF",
        "card_border": "#DDE5EE",
        "inset": "#F6F8FB",
        "inset_border": "#E4EAF2",
        "text": "#152438",
        "text_strong": "#0E1B2B",
        "text_muted": "#65758A",
        "text_faint": "#8B98A9",
        "accent": "#0A6E6C",
        "accent_hover": "#085B59",
        "accent_press": "#064A48",
        "accent_text": "#FFFFFF",
        "accent_soft": "#E4F4F2",
        "accent_soft_text": "#0A5F5D",
        "warn": "#B0741A",
        "warn_soft": "#FDF3E1",
        "bad": "#B23B3B",
        "bad_soft": "#FBECEC",
        "ok": "#1C7A45",
        "ok_soft": "#E8F5EC",
        "stage": "#0E1F30",
        "stage_text": "#D6E2EE",
        "stage_border": "#1D3349",
        "bar_track": "#E1E8F1",
        "bar_fill": "#0A6E6C",
        "chip": "#EDF2F7",
        "chip_text": "#3C4E63",
        "focus": "#0A6E6C",
        "brand_grad_a": "#123A5A",
        "brand_grad_b": "#0A6E6C",
        "brand_text": "#FFFFFF",
    },
    "dark": {
        "home_bg": "#100E0C",
        "home_card": "#1A1614",
        "home_line": "#2C2723",
        "home_text": "#F4EFE8",
        "home_muted": "#9A9188",
        "home_orange": "#E8703A",
        "home_green": "#4FBF7F",
        "home_mono": "#7A7168",

        "nav_on": "#4FD1C8",
        "nav_off": "#93A3B5",
        "nav_hover": "#1E2A38",
        "nav_underline": "#4FD1C8",

        "stage_chip_bg": "#173A38",
        "stage_chip_text": "#7FDDD6",

        "window": "#0E151E",
        "card": "#16202C",
        "card_border": "#253242",
        "inset": "#1B2733",
        "inset_border": "#2B3949",
        "text": "#DEE7F0",
        "text_strong": "#F2F7FC",
        "text_muted": "#93A3B5",
        "text_faint": "#73849A",
        "accent": "#2FB3AC",
        "accent_hover": "#43C6BF",
        "accent_press": "#269A94",
        "accent_text": "#08201F",
        "accent_soft": "#173A38",
        "accent_soft_text": "#7FDDD6",
        "warn": "#E3B059",
        "warn_soft": "#3A2E1A",
        "bad": "#E88A8A",
        "bad_soft": "#3B2020",
        "ok": "#6FD39A",
        "ok_soft": "#17352A",
        "stage": "#0A121A",
        "stage_text": "#B9C7D6",
        "stage_border": "#22303F",
        "bar_track": "#263444",
        "bar_fill": "#2FB3AC",
        "chip": "#1E2A38",
        "chip_text": "#A9BACC",
        "focus": "#2FB3AC",
        "brand_grad_a": "#1B4A72",
        "brand_grad_b": "#2FB3AC",
        "brand_text": "#04181C",
    },
}

_STATUS_STYLE = {
    # level: (token prefix for the dot colour, marker glyph, default words)
    "ready": ("ok", "\u25cf", "Ready"),
    "warning": ("warn", "!", "Attention"),
    "error": ("bad", "\u2715", "Error"),
    "busy": ("accent", "\u25cf", "Working"),
    "idle": ("text_faint", "\u25cb", "Idle"),
}


def _stylesheet(tokens: dict[str, str]) -> str:
    """Build the whole window stylesheet from one token table."""
    qss = """
    QMainWindow#mainWindow, QWidget#rootSurface { background: $window; }
    QWidget { font-family: 'Segoe UI Variable Text', 'Segoe UI', 'Noto Sans', Arial, sans-serif;
              color: $text; }

    QLabel#brandTile {
        border-radius: 15px; border: 1px solid $card_border;
        color: $brand_text; font-size: 20px; font-weight: 800;
    }
    QLabel#appTitle { font-size: 24px; font-weight: 800; letter-spacing: 0.2px; color: $text_strong; }
    QLabel#appSubtitle { font-size: 10px; font-weight: 700; letter-spacing: 1.4px; color: $text_faint; }

    QFrame#statusPill { background: $card; border: 1px solid $card_border; border-radius: 16px; }
    QLabel#statusMarker { font-size: 11px; font-weight: 800; }
    QLabel#statusText { color: $text_muted; font-size: 12px; font-weight: 700; }

    QFrame#surfaceCard { background: $card; border: 1px solid $card_border; border-radius: 16px; }
    QLabel#sectionTitle { font-size: 15px; font-weight: 750; color: $text_strong; }
    QLabel#sectionHint { font-size: 11px; color: $text_faint; }

    QLabel#cameraBadge, QLabel#liveBadge {
        background: $inset; color: $text_muted; border-radius: 8px;
        padding: 5px 9px; font-size: 9px; font-weight: 800; letter-spacing: 0.7px;
    }
    QLabel#liveBadge { background: $accent_soft; color: $accent_soft_text; }

    QLabel#videoPreview {
        background: $stage; color: $stage_text; border: 1px solid $stage_border;
        border-radius: 12px; font-size: 13px; padding: 18px;
    }

    QFrame#heroCard { background: $accent_soft; border: 1px solid $card_border; border-radius: 16px; }
    QLabel#heroCaption { color: $accent_soft_text; font-size: 9px; font-weight: 800; letter-spacing: 1.1px; }
    QLabel#heroValue { color: $text_strong; font-size: 44px; font-weight: 800; }
    QLabel#heroValue[state="empty"] { color: $text_faint; font-size: 22px; font-weight: 600; }
    QLabel#heroValue[state="lingering"] { color: $text_muted; }
    QLabel#heroHint { color: $text_muted; font-size: 12px; }
    QLabel#confidenceCaption { color: $text_muted; font-size: 9px; font-weight: 800; letter-spacing: 1px; }
    QLabel#confidenceValue { color: $text_strong; font-size: 15px; font-weight: 800; }

    QProgressBar#confidenceBar {
        background: $bar_track; border: none; border-radius: 5px; height: 10px;
    }
    QProgressBar#confidenceBar::chunk { background: $bar_fill; border-radius: 5px; }

    QFrame#recentStrip { background: transparent; border: none; }
    QLabel#chip {
        background: $chip; color: $chip_text; border-radius: 9px;
        padding: 6px 11px; font-size: 11px; font-weight: 700;
    }
    QLabel#chipEmpty { color: $text_faint; font-size: 11px; }

    QTextEdit#sentenceEdit {
        background: $inset; border: 1px solid $inset_border; border-radius: 12px;
        padding: 12px; color: $text; font-size: 17px;
        selection-background-color: $accent;
    }
    QTextEdit#sentenceEdit:focus { border: 1px solid $focus; }
    QLabel#mutedCaption { color: $text_faint; font-size: 10px; }

    QWidget#homePage, QScrollArea#homeScroll, QWidget#homeInner { background: $home_bg; }
    QScrollArea#homeScroll QScrollBar:vertical {
        background: transparent; width: 9px; margin: 2px;
    }
    QScrollArea#homeScroll QScrollBar::handle:vertical {
        background: $home_line; border-radius: 4px; min-height: 40px;
    }
    QScrollArea#homeScroll QScrollBar::handle:vertical:hover { background: $home_mono; }
    QScrollArea#homeScroll QScrollBar::add-line:vertical,
    QScrollArea#homeScroll QScrollBar::sub-line:vertical {
        height: 0; width: 0; background: none;
    }
    QScrollArea#homeScroll QScrollBar::add-page:vertical,
    QScrollArea#homeScroll QScrollBar::sub-page:vertical { background: none; }
    QLabel#homeBadge {
        background: $home_card; color: $home_muted; border: 1px solid $home_line;
        border-radius: 13px; padding: 6px 13px;
        font-family: 'Cascadia Mono', 'Consolas', 'DejaVu Sans Mono', monospace;
        font-size: 9px; font-weight: 700; letter-spacing: 1.1px;
    }
    QLabel#homeHero {
        color: $home_text; font-size: 46px; font-weight: 800; letter-spacing: -1.2px;
    }
    QLabel#homeLede { color: $home_muted; font-size: 14px; }
    QLabel#homeMono {
        color: $home_mono; font-family: 'Cascadia Mono', 'Consolas', 'DejaVu Sans Mono', monospace;
        font-size: 9px; font-weight: 700; letter-spacing: 1.2px;
    }
    QLabel#homeStatValue { color: $home_text; font-size: 34px; font-weight: 800; }
    QLabel#homeStatText { color: $home_text; font-size: 12px; }
    QFrame#homeCard { background: $home_card; border: 1px solid $home_line; border-radius: 14px; }
    QFrame#homeStatRow { background: $home_card; border: 1px solid $home_line; border-radius: 12px; }
    QLabel#homeSectionTitle { color: $home_text; font-size: 26px; font-weight: 800; letter-spacing: -0.5px; }
    QLabel#homeCardTitle { color: $home_text; font-size: 13px; font-weight: 750; }
    QLabel#homeCardBody { color: $home_muted; font-size: 12px; }
    QLabel#homeNumber { color: $home_text; font-size: 40px; font-weight: 800; }
    QPushButton#homeCta {
        background: $home_orange; color: #1A0F08; border: none; border-radius: 10px;
        font-size: 12px; font-weight: 800; padding: 11px 20px; min-height: 20px;
    }
    QPushButton#homeCta:hover { background: $home_green; color: #06180F; }
    QPushButton#homeCta:focus { border: 2px solid $accent; }
    QPushButton#homeGhost {
        background: transparent; color: $home_text; border: 1px solid $home_line;
        border-radius: 10px; font-size: 12px; font-weight: 700; padding: 11px 20px;
        min-height: 20px;
    }
    QPushButton#homeGhost:hover { background: $home_card; }
    QPushButton#homeGhost:focus { border: 2px solid $accent; }
    QLabel#homeRowLabel {
        color: $home_muted; font-size: 10px; font-weight: 700; letter-spacing: 0.8px;
    }
    QLabel#homeRowValue { color: $home_text; font-size: 12px; font-weight: 700; }
    QLabel#homeFootnote { color: $home_mono; font-size: 10px; }
    QPushButton#navButton {
        background: transparent; border: none; border-bottom: 2px solid transparent;
        color: $nav_off; font-size: 12px; font-weight: 700; letter-spacing: 0.6px;
        padding: 10px 13px; min-height: 18px; border-radius: 0;
    }
    QPushButton#navButton:hover { background: $nav_hover; color: $text; }
    QPushButton#navButton:checked {
        color: $nav_on; border-bottom: 2px solid $nav_underline;
    }
    QPushButton#navButton:focus { border: 2px solid $focus; border-radius: 6px; }
    QWidget#sectionPage { background: $window; }
    QLabel#pageTitle { font-size: 21px; font-weight: 800; color: $text_strong; }
    QLabel#pageLede { font-size: 12px; color: $text_muted; }
    QPushButton#subTab {
        background: $inset; border: 1px solid $inset_border; border-radius: 9px;
        color: $text_muted; font-size: 12px; font-weight: 700; padding: 7px 14px;
        min-height: 22px;
    }
    QPushButton#subTab:hover { background: $chip; color: $text; }
    QPushButton#subTab:checked {
        background: $accent_soft; border: 1px solid $accent; color: $accent_soft_text;
    }
    QPushButton#subTab:focus { border: 2px solid $focus; }
    QFrame#voiceOption {
        background: $inset; border: 1px solid $inset_border; border-radius: 12px;
    }
    QFrame#voiceOption[selected="true"] {
        background: $accent_soft; border: 1px solid $accent;
    }
    QLabel#voiceTitle { font-size: 13px; font-weight: 750; color: $text_strong; }
    QLabel#voiceDetail { font-size: 11px; color: $text_muted; }
    QLabel#offlineBadge {
        background: $ok_soft; color: $ok; border-radius: 7px;
        padding: 3px 8px; font-size: 9px; font-weight: 800;
    }
    QLabel#onlineBadge {
        background: $warn_soft; color: $warn; border-radius: 7px;
        padding: 3px 8px; font-size: 9px; font-weight: 800;
    }
    QSlider#rateSlider::groove:horizontal {
        height: 6px; background: $bar_track; border-radius: 3px;
    }
    QSlider#rateSlider::handle:horizontal {
        width: 16px; margin: -6px 0; border-radius: 8px; background: $accent;
    }
    QLabel#rateValue { font-size: 13px; font-weight: 800; color: $text_strong; }
    QLabel#warningNote {
        background: $warn_soft; color: $warn; border-radius: 10px;
        padding: 10px 13px; font-size: 11px;
    }
    QFrame#avatarCard { background: $card; border: 1px solid $card_border; border-radius: 16px; }
    QWidget#avatarStage { background: $stage; border-radius: 12px; }
    QLabel#avatarMessage { color: $stage_text; font-size: 12px; padding: 18px; }
    QLabel#stageBadge {
        background: $chip; color: $chip_text; border-radius: 8px;
        padding: 5px 9px; font-size: 9px; font-weight: 800; letter-spacing: 0.7px;
    }
    QLabel#textToSignHint { color: $text_muted; font-size: 11px; }
    QLabel#noClipNote { color: $warn; font-size: 11px; }
    QLineEdit#textToSignInput {
        background: $inset; border: 1px solid $inset_border; border-radius: 10px;
        padding: 9px 12px; color: $text; font-size: 13px; min-height: 22px;
    }
    QLineEdit#textToSignInput:focus { border: 2px solid $focus; }
    QComboBox#signPicker {
        background: $inset; border: 1px solid $inset_border; border-radius: 10px;
        padding: 7px 10px; color: $text; font-size: 12px; min-height: 24px;
    }
    QComboBox#signPicker:focus { border: 2px solid $focus; }
    QComboBox#signPicker QAbstractItemView {
        background: $card; color: $text; selection-background-color: $accent;
        selection-color: $accent_text; border: 1px solid $card_border;
    }
    QLabel#connectionNote {
        background: $inset; color: $text_muted; border: 1px solid $inset_border;
        border-radius: 10px; padding: 10px 14px; font-size: 11px;
    }
    QLabel#connectionNote[level="warning"] { background: $warn_soft; color: $warn; border-color: $warn_soft; }
    QLabel#connectionNote[level="error"] { background: $bad_soft; color: $bad; border-color: $bad_soft; }

    QPushButton {
        min-height: 40px; border-radius: 10px; padding: 0 16px;
        font-size: 12px; font-weight: 750;
    }
    QPushButton:focus { outline: none; border: 2px solid $focus; }
    QPushButton#primaryButton { background: $accent; color: $accent_text; border: 1px solid $accent; }
    QPushButton#primaryButton:hover { background: $accent_hover; border-color: $accent_hover; }
    QPushButton#primaryButton:pressed { background: $accent_press; }
    QPushButton#primaryButton:disabled { background: $chip; color: $text_faint; border-color: $chip; }
    QPushButton#secondaryButton { background: $inset; color: $text; border: 1px solid $inset_border; }
    QPushButton#secondaryButton:hover { background: $chip; }
    QPushButton#secondaryButton:disabled { background: $inset; color: $text_faint; border-color: $inset_border; }
    QPushButton#textButton { background: transparent; color: $text_muted; border: 1px solid transparent; }
    QPushButton#textButton:hover { background: $inset; }
    QPushButton#textButton:disabled { color: $text_faint; }
    QLabel#shortcutHint { color: $text_faint; font-size: 10px; }
    """
    # Longest names first: "$text" is a prefix of "$text_muted", and a short name
    # substituted first would corrupt the longer placeholders.
    for name in sorted(tokens, key=len, reverse=True):
        qss = qss.replace("$" + name, tokens[name])
    return qss


#: Updated by the window whenever the theme changes; used by VideoPreview.paintEvent.
_PREVIEW_TOKENS: dict[str, str] = dict(THEMES["light"])


def _theme_name_from_settings() -> str:
    stored = QSettings().value("ui/theme", "light")
    return "dark" if str(stored).lower() == "dark" else "light"


# ---------------------------------------------------------------------------
# Backend contract
# ---------------------------------------------------------------------------
class BackendLoadError(RuntimeError):
    """Raised when the configured backend cannot satisfy the integration contract."""


@dataclass(frozen=True)
class BackendAPI:
    start_recognition: Callable[[], None]
    stop_recognition: Callable[[], None]
    get_latest_prediction: Callable[[], Optional[dict[str, Any]]]
    add_word: Callable[[str], None]
    get_sentence: Callable[[], str]
    clear_sentence: Callable[[], None]
    speak: Callable[[str], None]
    stop_speech: Callable[[], None]
    set_mode: Optional[Callable[[str], None]] = None
    set_sentence: Optional[Callable[[str], None]] = None


def load_backend() -> tuple[Optional[BackendAPI], str]:
    """Load the configured adapter module and validate the exact public contract."""
    module_name = os.environ.get("BHASHASETU_BACKEND_MODULE", DEFAULT_BACKEND_MODULE).strip()
    if not module_name:
        return None, "BHASHASETU_BACKEND_MODULE is empty."

    try:
        module = importlib.import_module(module_name)
    except Exception as exc:  # ImportError plus errors raised inside the adapter.
        return None, (
            f"Could not import backend module '{module_name}': {exc}\n\n"
            "Create the adapter module in the project folder, or set "
            "BHASHASETU_BACKEND_MODULE to the correct Python module name."
        )

    required = (
        "start_recognition",
        "stop_recognition",
        "get_latest_prediction",
        "add_word",
        "get_sentence",
        "clear_sentence",
        "speak",
        "stop_speech",
    )
    missing = [name for name in required if not callable(getattr(module, name, None))]
    if missing:
        return None, (
            f"Backend module '{module_name}' is missing callable(s): "
            + ", ".join(missing)
            + ".\n\nExpose the eight functions in the integration contract from this module."
        )

    # Validate positional arity where Python exposes a signature. A few extension or
    # decorated callables do not expose one; those remain callable-checked and will
    # report any incompatibility when invoked.
    positional_counts = {
        "start_recognition": 0,
        "stop_recognition": 0,
        "get_latest_prediction": 0,
        "add_word": 1,
        "get_sentence": 0,
        "clear_sentence": 0,
        "speak": 1,
        "stop_speech": 0,
    }
    incompatible = []
    for name, count in positional_counts.items():
        function = getattr(module, name)
        try:
            signature = inspect.signature(function)
        except (TypeError, ValueError):
            continue
        try:
            signature.bind(*([object()] * count))
        except TypeError as exc:
            incompatible.append(f"{name}{signature}: {exc}")

    if incompatible:
        return None, (
            f"Backend module '{module_name}' has incompatible function signature(s):\n"
            + "\n".join(incompatible)
            + "\n\nSee README.md for the exact eight-function contract."
        )

    return BackendAPI(
        **{name: getattr(module, name) for name in required},
        set_mode=getattr(module, "set_mode", None),
        set_sentence=getattr(module, "set_sentence", None),
    ), module_name


# ---------------------------------------------------------------------------
# Prediction parsing (unchanged behaviour)
# ---------------------------------------------------------------------------
@dataclass
class ParsedPrediction:
    word: Optional[str] = None
    confidence: Any = None


def _first_present(mapping: dict, keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def parse_prediction(payload: Any) -> ParsedPrediction:
    """Accept common prediction containers without making assumptions about the model.

    Supported examples:
      {"word": "HELLO", "confidence": 0.97}
      {"label": "HELLO", "score": 97.0}
      ("HELLO", 0.97)
      "HELLO"
      objects exposing .word/.confidence or .label/.score
    """
    word = None
    confidence = None

    if payload is None:
        return ParsedPrediction()

    if isinstance(payload, dict):
        word = _first_present(
            payload,
            ("word", "recognized_word", "label", "class_name", "prediction", "text"),
        )
        confidence = _first_present(payload, ("confidence", "score", "probability", "prob"))
    elif isinstance(payload, (tuple, list)):
        if len(payload) >= 1:
            word = payload[0]
        if len(payload) >= 2:
            confidence = payload[1]
    elif isinstance(payload, str):
        word = payload
    else:
        for attr in ("word", "recognized_word", "label", "class_name", "prediction", "text"):
            if hasattr(payload, attr):
                word = getattr(payload, attr)
                break
        for attr in ("confidence", "score", "probability", "prob"):
            if hasattr(payload, attr):
                confidence = getattr(payload, attr)
                break

    if word is not None:
        word = str(word).strip()
    if not word or word.lower() in {"none", "null", "no sign", "no_sign", "background"}:
        word = None

    return ParsedPrediction(word=word, confidence=confidence)


def extract_frame(payload: Any) -> tuple[Any, str]:
    """Read an optional image already included in a prediction payload.

    The agreed contract carries the current frame in the same snapshot returned by
    get_latest_prediction(); no second camera or additional backend function is used.
    """
    if isinstance(payload, dict):
        for key in ("frame_rgb", "frame", "frame_bgr", "image", "preview"):
            if payload.get(key) is not None:
                return payload[key], key
    else:
        for key in ("frame_rgb", "frame", "frame_bgr", "image", "preview"):
            value = getattr(payload, key, None)
            if value is not None:
                return value, key
    return None, ""


def snapshot_prediction_payload(payload: Any) -> Any:
    """Detach image memory before a prediction crosses the QThread boundary.

    Camera backends commonly reuse a NumPy frame buffer on the next capture. A shallow
    copy of the dictionary alone would leave the GUI reading memory that the camera
    thread may already have overwritten.
    """
    if not isinstance(payload, dict):
        return payload

    snapshot = dict(payload)
    for key in ("frame_rgb", "frame", "frame_bgr", "image", "preview"):
        frame = snapshot.get(key)
        if frame is None:
            continue
        try:
            # Works for NumPy arrays, QImage, and common image objects with copy().
            snapshot[key] = frame.copy()
        except Exception:
            # The backend must return an owned/immutable frame if it uses a custom
            # object without copy(). Do not discard the word/confidence prediction.
            pass
        break
    return snapshot


def frame_to_qimage(frame: Any, source_key: str = "frame") -> Optional[QImage]:
    """Convert QImage/QPixmap/NumPy image frames to a detached QImage."""
    if isinstance(frame, QImage):
        return frame.copy()
    if isinstance(frame, QPixmap):
        return frame.toImage().copy()

    try:
        import numpy as np  # Optional: usually already installed with CV backends.

        array = np.asarray(frame)
        if array.size == 0:
            return None
        if array.dtype != np.uint8:
            array = np.clip(array, 0, 255).astype(np.uint8)

        if array.ndim == 2:
            height, width = array.shape
            contiguous = np.ascontiguousarray(array)
            image = QImage(
                contiguous.data,
                width,
                height,
                int(contiguous.strides[0]),
                QImage.Format.Format_Grayscale8,
            )
            return image.copy()

        if array.ndim != 3:
            return None

        height, width, channels = array.shape
        if channels == 3:
            if source_key in ("frame_rgb", "image_rgb"):
                rgb = np.ascontiguousarray(array)
            else:
                # OpenCV-style BGR is the common convention for camera frames.
                rgb = np.ascontiguousarray(array[:, :, ::-1])
            image = QImage(
                rgb.data,
                width,
                height,
                int(rgb.strides[0]),
                QImage.Format.Format_RGB888,
            )
            return image.copy()

        if channels == 4:
            if source_key == "frame_rgb":
                rgba = np.ascontiguousarray(array)
            else:
                rgba = np.ascontiguousarray(array[:, :, [2, 1, 0, 3]])
            image = QImage(
                rgba.data,
                width,
                height,
                int(rgba.strides[0]),
                QImage.Format.Format_RGBA8888,
            )
            return image.copy()
    except Exception:
        return None

    return None


# ---------------------------------------------------------------------------
# Threads (unchanged behaviour)
# ---------------------------------------------------------------------------
class RecognitionThread(QThread):
    """Owns camera/recognition lifecycle and polls predictions off the GUI thread."""
    prediction_received = Signal(object)
    status_changed = Signal(str)
    failed = Signal(str)

    def __init__(self, backend: BackendAPI, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.backend = backend
        self._stop_event = threading.Event()

    def request_stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        start_attempted = False
        failure: Optional[str] = None
        try:
            self.status_changed.emit("Starting camera\u2026")
            # Mark before calling start: if startup partially opens the camera and
            # then raises, stop_recognition() must still get a chance to release it.
            start_attempted = True
            self.backend.start_recognition()

            if not self._stop_event.is_set():
                self.status_changed.emit("Camera active")

            while not self._stop_event.is_set():
                payload = self.backend.get_latest_prediction()
                if payload is not None:
                    self.prediction_received.emit(snapshot_prediction_payload(payload))
                self.msleep(POLL_INTERVAL_MS)

        except Exception as exc:
            failure = f"Recognition error: {exc}"
        finally:
            if start_attempted:
                try:
                    self.backend.stop_recognition()
                except Exception as exc:
                    stop_error = f"Could not stop recognition cleanly: {exc}"
                    failure = f"{failure}; {stop_error}" if failure else stop_error
            self.status_changed.emit("Camera stopped")
            if failure:
                self.failed.emit(failure)


class FunctionThread(QThread):
    """Run a potentially blocking backend operation outside the GUI thread."""
    failed = Signal(str)

    def __init__(self, function: Callable, *args: Any, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.function = function
        self.args = args
        self.error_text: Optional[str] = None

    def run(self) -> None:
        try:
            self.function(*self.args)
        except Exception as exc:
            self.error_text = str(exc)
            self.failed.emit(self.error_text)


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------
class VideoPreview(QWidget):
    """A preview surface drawn in paintEvent; it never opens a camera device.

    Painting (rather than setPixmap on a QLabel) keeps the frame from influencing
    the layout, so a 640x480 camera image can never push the controls around.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._image: Optional[QImage] = None
        self._camera_state = "idle"
        self.setObjectName("videoPreview")
        self.setMinimumSize(620, 400)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName("Camera preview")
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

    def set_camera_state(self, state: str) -> None:
        self._camera_state = state
        self.update()

    def set_frame(self, image: QImage) -> None:
        self._image = image.copy()
        self.update()

    def clear_frame(self) -> None:
        self._image = None
        self.update()

    def _placeholder_lines(self) -> tuple[str, str]:
        messages = {
            "idle": ("Camera is off", "Press Start camera (Ctrl+Shift+C) to begin."),
            "starting": ("Starting camera\u2026", "Waiting for the first frame."),
            "active": ("No frame yet", "The camera is running but sent no picture yet."),
            "stopped": ("Camera stopped", "Press Start camera to resume."),
            "error": ("Camera unavailable", "See the message below the panel."),
        }
        return messages.get(self._camera_state, messages["idle"])

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override name
        from PySide6.QtGui import QColor, QPainter

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        tokens = _PREVIEW_TOKENS
        painter.fillRect(self.rect(), QColor(tokens.get("stage", "#0E1F30")))

        if self._image is not None and not self._image.isNull():
            pixmap = QPixmap.fromImage(self._image)
            scaled = pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(
                (self.width() - scaled.width()) // 2,
                (self.height() - scaled.height()) // 2,
                scaled,
            )
            painter.end()
            return

        title, detail = self._placeholder_lines()
        colour = QColor(tokens.get("stage_text", "#D6E2EE"))
        painter.setPen(colour)
        title_font = QFont(self.font())
        title_font.setPointSizeF(max(10.0, title_font.pointSizeF() + 2))
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.drawText(
            self.rect().adjusted(16, 0, -16, -14),
            Qt.AlignmentFlag.AlignCenter, title)
        detail_font = QFont(self.font())
        painter.setFont(detail_font)
        faded = QColor(colour)
        faded.setAlpha(170)
        painter.setPen(faded)
        painter.drawText(
            self.rect().adjusted(16, 26, -16, 0),
            Qt.AlignmentFlag.AlignCenter, detail)
        painter.end()


class ConfidenceBar(QProgressBar):
    """Percentage bar; the number is always shown in text next to it too."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("confidenceBar")
        self.setRange(0, 100)
        self.setValue(0)
        self.setTextVisible(False)
        self.setFixedHeight(10)
        self.setAccessibleName("Recognition confidence")

    def set_percent(self, value: Optional[float]) -> None:
        self.setValue(0 if value is None else int(round(max(0.0, min(100.0, value)))))


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
class BhashaSetuWindow(QMainWindow):
    def __init__(self, backend: Optional[BackendAPI], backend_info: str) -> None:
        super().__init__()
        self.backend = backend
        self.backend_info = backend_info
        self.recognition_thread: Optional[RecognitionThread] = None
        self._background_threads: list[FunctionThread] = []
        self._last_added_word: Optional[str] = None
        self._close_pending = False
        self._shutdown_speech_requested = False
        self._recent_signs: list[str] = []
        self._last_shown_word: Optional[str] = None
        # Pages are built on first visit; these exist from the start so shutdown,
        # signals, and shortcuts never touch a missing attribute.
        self.avatar_stage = None
        self.text_input = None
        self.sign_picker = None
        self.text_to_sign_hint = None
        self.avatar_badge = None
        self.voice_options = {}
        self.rate_slider = None
        self._voice_key = str(QSettings().value("ui/voice", "system") or "system")
        self._speech_rate = float(QSettings().value("ui/speech_rate", 1.0) or 1.0)
        self._theme_name = _theme_name_from_settings()

        self.setWindowTitle(APP_TITLE)
        self.setMinimumSize(1040, 700)
        self.resize(1360, 850)
        self.setObjectName("mainWindow")
        self._build_ui()
        self._install_shortcuts()
        self._sign_hold_timer = QTimer(self)
        self._sign_hold_timer.setSingleShot(True)
        self._sign_hold_timer.setInterval(1500)
        self._sign_hold_timer.timeout.connect(self._expire_current_sign)
        self.apply_theme(self._theme_name, save=False)
        self._restore_geometry()
        self.show_section(str(QSettings().value("ui/section", "home") or "home"))
        # The Text -> Speech page is built on first visit; when it was not the
        # landing page, its saved voice/rate are applied by _build_voice_card().
        self._set_backend_controls_enabled(self.backend is not None)

        if self.backend is None:
            self._set_status("Backend disconnected", "warning")
            self._set_connection_message(
                "Recognition is not connected yet. " + self.backend_info, "warning")
        else:
            self._set_status("Ready \u2014 camera off", "ready")
            self._set_connection_message(
                f"Connected to backend module: {self.backend_info}", "ready")

    # ---------------------------------------------------------------- layout
    #: Section order shown in the top bar, like the department rows on a store site.
    SECTIONS = (
        ("home", "Home"),
        ("sign", "Sign \u2192 Text"),
        ("text_sign", "Text \u2192 Sign"),
        ("text_speech", "Text \u2192 Speech"),
    )
    SECTION_LEDE = {
        "home": ("BhasaSetu",
                 "A two-way bridge between Indian Sign Language, text and speech. "
                 "Everything below runs on this computer."),
        "sign": ("Sign \u2192 Text",
                 "Show a sign to the camera. The recognised sign appears here and "
                 "adds to your sentence."),
        "text_sign": ("Text \u2192 Sign",
                      "Type or pick a clip and watch the 3D avatar sign it in this window."),
        "text_speech": ("Text \u2192 Speech",
                        "Type or paste text and have it read aloud. Nothing is "
                        "recognised or translated."),
    }

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("rootSurface")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(26, 18, 26, 16)
        root_layout.setSpacing(12)

        # Header row: brand + theme switch + status.
        root_layout.addLayout(self._build_header())
        # Section row: one tab per section, like a store's category bar.
        self.nav_buttons: dict[str, QPushButton] = {}
        root_layout.addWidget(self._build_section_bar())

        # One page per section; only the chosen one is shown.
        self.pages = QStackedWidget()
        self.pages.setObjectName("sectionPages")
        self._page_builders = {
            "home": self._build_home_page,
            "sign": self._build_sign_page,
            "text_sign": self._build_text_sign_page,
            "text_speech": self._build_text_speech_page,
        }
        self._built_pages: dict[str, QWidget] = {}
        for key, _label in self.SECTIONS:
            self.pages.addWidget(QWidget())      # replaced lazily on first visit
        root_layout.addWidget(self.pages, 1)

        self.connection_note = QLabel()
        self.connection_note.setObjectName("connectionNote")
        self.connection_note.setWordWrap(True)
        self.connection_note.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        root_layout.addWidget(self.connection_note)

        self.setCentralWidget(root)
        self.show_section("home")

    def _build_section_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("sectionBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        for index, (key, label) in enumerate(self.SECTIONS):
            button = QPushButton(label)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setAccessibleName(f"Open the {label} section")
            button.clicked.connect(lambda _checked=False, k=key: self.show_section(k))
            layout.addWidget(button)
            self.nav_buttons[key] = button
        layout.addStretch(1)
        self.section_hint = QLabel("")
        self.section_hint.setObjectName("sectionHint")
        layout.addWidget(self.section_hint)
        return bar

    # --------------------------------------------------------------- sections
    def show_section(self, key: str) -> None:
        """Show one section page and mark its tab, like a store category page."""
        if key not in self._page_builders:
            key = "home"
        if key not in self._built_pages:
            page = self._page_builders[key]()
            index = [k for k, _ in self.SECTIONS].index(key)
            self.pages.removeWidget(self.pages.widget(index))
            self.pages.insertWidget(index, page)
            self._built_pages[key] = page
        self.pages.setCurrentWidget(self._built_pages[key])
        for name, button in self.nav_buttons.items():
            button.setChecked(name == key)
        self.current_section = key
        QSettings().setValue("ui/section", key)
        title, lede = self.SECTION_LEDE[key]
        self.section_hint.setText(lede)
        if key == "text_speech":
            self._refresh_voice_status()

    def _page_shell(self, key: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        page.setObjectName("sectionPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(12)
        title, lede = self.SECTION_LEDE[key]
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)
        sub = QLabel(lede)
        sub.setObjectName("pageLede")
        sub.setWordWrap(True)
        layout.addWidget(sub)
        return page, layout

    # ------------------------------------------------------------------- home
    def _build_home_page(self) -> QWidget:
        """Editorial landing page: hero, the real problem, then the plan."""
        page = QWidget()
        page.setObjectName("homePage")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setObjectName("homeScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setObjectName("homeInner")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(4, 6, 18, 26)
        layout.setSpacing(24)

        layout.addWidget(self._home_hero())
        layout.addWidget(self._home_problem())
        layout.addWidget(self._home_regional())
        layout.addWidget(self._home_roadmap())
        layout.addWidget(self._home_status())
        layout.addStretch(1)
        scroll.setWidget(inner)
        outer.addWidget(scroll)
        # Pages are built lazily, after the theme is already applied.
        self._refresh_rich_labels()
        return page

    def _home_label(self, text: str, name: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName(name)
        label.setWordWrap(True)
        return label

    def _home_hero(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(26)

        left = QVBoxLayout()
        left.setSpacing(14)
        badge = QLabel("WORK IN PROGRESS  \u00b7  LOCAL-ONLY PROTOTYPE  \u00b7  "
                       "NO SIGNER APPROVAL YET")
        badge.setObjectName("homeBadge")
        holder = QHBoxLayout()
        holder.addWidget(badge)
        holder.addStretch(1)
        left.addLayout(holder)

        hero = QLabel("A bridge between "
                      "<span style='color:%s'>sign</span> and "
                      "<span style='color:%s'>speech</span>." % ("$home_orange", "$home_green"))
        hero.setObjectName("homeHero")
        hero.setWordWrap(True)
        hero.setTextFormat(Qt.TextFormat.RichText)
        left.addWidget(hero)
        left.addSpacing(2)

        left.addWidget(self._home_label(
            "BhasaSetu reads Indian Sign Language from your webcam and writes it as "
            "text, plays reference clips back as a 3D avatar, and speaks text aloud. "
            "Both directions are prototypes: no sentence-level ISL model exists here, "
            "and no clip has been approved by a Deaf ISL signer.", "homeLede"))

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        start = QPushButton("Start with the camera")
        start.setObjectName("homeCta")
        start.clicked.connect(lambda: self.show_section("sign"))
        arrow = QPushButton("See the avatar")
        arrow.setObjectName("homeGhost")
        arrow.clicked.connect(lambda: self.show_section("text_sign"))
        speak = QPushButton("Read text aloud")
        speak.setObjectName("homeGhost")
        speak.clicked.connect(lambda: self.show_section("text_speech"))
        buttons.addWidget(start)
        buttons.addWidget(arrow)
        buttons.addWidget(speak)
        buttons.addStretch(1)
        left.addLayout(buttons)
        layout.addLayout(left, 6)
        layout.addWidget(self._home_preview_card(), 5)
        return row

    def _home_preview_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("homeCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(11)

        head = QHBoxLayout()
        head.addWidget(self._home_label("PREVIEW \u00b7 STATIC", "homeMono"))
        head.addStretch(1)
        head.addWidget(self._home_label("\u25cf  NOT LIVE", "homeMono"))
        layout.addLayout(head)

        mode = QLabel("TWO-WAY  \u00b7  CAMERA \u2192 TEXT  \u00b7  TEXT \u2192 AVATAR")
        mode.setObjectName("homeMono")
        layout.addWidget(mode)

        # two mini panels, echoing the reference layout
        panels = QHBoxLayout()
        panels.setSpacing(10)
        panels.addWidget(self._home_mini_panel(
            "INPUT  \u00b7  CAMERA", [("Landmarks", "21 points"),
                                      ("Feature vector", "164 dims"),
                                      ("Frame rate", "30 fps")],
            "Your webcam. Nothing is uploaded."), 1)
        panels.addWidget(self._home_mini_panel(
            "ON DEVICE", [("Processing", "local only"),
                          ("Cloud calls", "none by default"),
                          ("Speech", "your system voice")],
            "The online voice is opt-in, never the fallback."), 1)
        layout.addLayout(panels)

        note = self._home_label(
            "This preview is drawn by the app, not captured from a running model. "
            "Open a section to use the real camera or the real avatar.", "homeFootnote")
        layout.addWidget(note)
        return card

    def _home_mini_panel(self, title: str, rows, footnote: str) -> QFrame:
        panel = QFrame()
        panel.setObjectName("homeStatRow")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(7)
        layout.addWidget(self._home_label(title, "homeMono"))
        for label, value in rows:
            line = QHBoxLayout()
            line.setSpacing(6)
            key = QLabel(label)
            key.setObjectName("homeRowLabel")
            key.setWordWrap(False)
            val = QLabel(value)
            val.setObjectName("homeRowValue")
            val.setWordWrap(False)
            line.addWidget(key)
            line.addStretch(1)
            line.addWidget(val)
            layout.addLayout(line)
        foot = self._home_label(footnote, "homeFootnote")
        layout.addWidget(foot)
        layout.addStretch(1)
        return panel

    # ------------------------------------------------------- the real problem
    def _home_problem(self) -> QWidget:
        """Sourced prevalence figures; no self-reported project statistics."""
        block = QWidget()
        layout = QVBoxLayout(block)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        layout.addWidget(self._home_label("/  THE PROBLEM THIS ADDRESSES", "homeMono"))
        title = QLabel("Hearing and speech disability is not rare in India. "
                       "<span style='color:%s'>It is under-served.</span>"
                       % "$home_orange")
        title.setObjectName("homeSectionTitle")
        title.setWordWrap(True)
        title.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(title)
        layout.addWidget(self._home_label(
            "Millions of people in India live with a hearing or speech disability. "
            "Most of them have no way to be understood in a classroom, a clinic or "
            "a government office. Figures below are from published sources, not "
            "estimates made by this project.", "homeCardBody"))

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        # (value, colour, headline, detail, source)
        cards = (
            ("5,071,007", "$home_orange",
             "people in India live with a hearing disability",
             "18.9% of all persons with disabilities recorded in the census.",
             "CENSUS OF INDIA 2011  \u00b7  DISABILITY TABLES"),
            ("1,998,535", "$home_green",
             "people live with a speech disability",
             "7.5% of all persons with disabilities recorded in the census.",
             "CENSUS OF INDIA 2011  \u00b7  DISABILITY TABLES"),
            ("430M", "$home_orange",
             "people worldwide have disabling hearing loss",
             "That is close to 29% of the 1.5 billion people with some hearing "
             "loss, projected to reach 700 million by 2050.",
             "WHO  \u00b7  DEAFNESS AND HEARING LOSS FACT SHEET"),
        )
        for index, (value, colour, headline, detail, source) in enumerate(cards):
            card = self._home_problem_card(
                value, colour, headline, detail, source)
            if index == 0:
                grid.addWidget(card, 0, 0)
            elif index == 1:
                grid.addWidget(card, 0, 1)
            else:
                grid.addWidget(card, 1, 0, 1, 2)
        layout.addLayout(grid)

        layout.addWidget(self._home_label(
            "Note on the counts: the 2011 Census remains India's most recent full "
            "enumeration, and it counts disability by self-report, so the real "
            "number of sign language users is not known precisely. That uncertainty "
            "is one reason this project states its sources instead of rounding up.",
            "homeFootnote"))
        return block

    def _home_problem_card(self, value: str, colour: str, headline: str,
                           detail: str, source: str) -> QFrame:
        card = QFrame()
        card.setObjectName("homeCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 13)
        layout.setSpacing(6)
        big = QLabel(f"<span style='color:{colour}'>{value}</span>")
        big.setObjectName("homeNumber")
        big.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(big)
        head = QLabel(headline)
        head.setObjectName("homeStatText")
        head.setWordWrap(True)
        layout.addWidget(head)
        body = self._home_label(detail, "homeCardBody")
        layout.addWidget(body)
        layout.addSpacing(2)
        layout.addWidget(self._home_label(source, "homeMono"))
        return card

    # ---------------------------------------------------- regional languages
    def _home_regional(self) -> QWidget:
        block = QWidget()
        layout = QVBoxLayout(block)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        layout.addWidget(self._home_label("/  REGIONAL LANGUAGE FEATURE",
                                          "homeMono"))
        title = QLabel("Speech output is English and Hindi today. "
                       "<span style='color:%s'>India needs more than two</span>."
                       % "$home_orange")
        title.setObjectName("homeSectionTitle")
        title.setWordWrap(True)
        title.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(title)
        layout.addWidget(self._home_label(
            "India is one of the most linguistically diverse countries on earth. "
            "A tool that only speaks English and Hindi reaches a fraction of the "
            "people who need it, so regional output is a planned direction, stated "
            "here as a plan rather than a finished feature.", "homeCardBody"))

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        grid.addWidget(self._home_problem_card(
            "22", "$home_green",
            "languages are in the Eighth Schedule of the Constitution",
            "Hindi and English are the two the app offers speech in today.",
            "CONSTITUTION OF INDIA  \u00b7  EIGHTH SCHEDULE"), 0, 0)
        grid.addWidget(self._home_problem_card(
            "121", "$home_orange",
            "languages were identified by the 2011 Census",
            "Grouped from 270 mother tongues with 10,000 or more speakers each.",
            "CENSUS OF INDIA 2011  \u00b7  LANGUAGE TABLES"), 0, 1)
        layout.addLayout(grid)

        targets = QFrame()
        targets.setObjectName("homeCard")
        targets_layout = QVBoxLayout(targets)
        targets_layout.setContentsMargins(16, 14, 16, 14)
        targets_layout.setSpacing(9)
        targets_layout.addWidget(self._home_label("SPEECH OUTPUT \u2014 WHAT IS REAL",
                                                  "homeMono"))
        chips = QGridLayout()
        chips.setHorizontalSpacing(8)
        chips.setVerticalSpacing(8)
        for index, (name, supported) in enumerate((
                ("English", True), ("Hindi", True),
                ("Marathi", False), ("Gujarati", False),
                ("Tamil", False), ("Telugu", False),
                ("Bengali", False), ("Kannada", False))):
            pill = QFrame()
            pill.setObjectName("homeStatRow")
            pill_layout = QHBoxLayout(pill)
            pill_layout.setContentsMargins(11, 8, 11, 8)
            pill_layout.setSpacing(8)
            mark = QLabel("<span style='color:%s'>\u2713</span>" % "$home_green"
                          if supported else "<span style='color:%s'>\u25cb</span>"
                          % "$home_mono")
            mark.setTextFormat(Qt.TextFormat.RichText)
            mark.setMinimumWidth(14)
            word = QLabel(name)
            word.setObjectName("homeRowValue")
            state = self._home_label("SPEAKS NOW" if supported else "PLANNED",
                                     "homeMono")
            pill_layout.addWidget(mark)
            pill_layout.addWidget(word)
            pill_layout.addStretch(1)
            pill_layout.addWidget(state)
            if not supported:
                word.setProperty("planned", True)
            chips.addWidget(pill, index // 4, index % 4)
        targets_layout.addLayout(chips)
        targets_layout.addWidget(self._home_label(
            "Only English and Hindi are wired up today. Everything marked PLANNED "
            "with an empty circle is a direction, not a feature \u2014 the circle is "
            "text, not just a colour, so the difference survives any theme or "
            "colour-vision. Which voices actually appear also depends on the "
            "speech engine installed on the machine.", "homeFootnote"))
        layout.addWidget(targets)

        why = self._home_label(
            "Why this matters for ISL: Indian Sign Language itself has regional "
            "variation, and ISLRTC's dictionary records some regional signs \u2014 "
            "number and colour terms from Hyderabad, Mumbai, Kolkata, Munger and "
            "Manipur. Regional speech output and regional sign variants belong "
            "together.", "homeCardBody")
        layout.addWidget(why)
        return block

    # --------------------------------------------------------- future upgrades
    def _home_roadmap(self) -> QWidget:
        block = QWidget()
        layout = QVBoxLayout(block)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        layout.addWidget(self._home_label("/  FUTURE UPGRADES", "homeMono"))
        title = QLabel("What comes next, and what has to be true first.")
        title.setObjectName("homeSectionTitle")
        title.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(self._home_label(
            "Each item below is a plan. None of them is implemented in this build, "
            "and the review column says who has to sign off before it can be "
            "presented as working.", "homeCardBody"))

        for status, colour, name, detail, review in (
            ("NEXT", "$home_orange", "Recognition backend module",
             "Wire the trained model into this window so the camera section "
             "recognises signs instead of reporting a missing backend.",
             "NEEDS: WORKING CHECKPOINT + LIVE TEST"),
            ("PLANNED", "$home_green", "More word signs",
             "Collect and train beyond the current word list, with several signers "
             "so the model is not tied to one person.",
             "NEEDS: ISL SIGNER REVIEW OF EVERY LABEL"),
            ("PLANNED", "$home_orange", "More avatar clips",
             "The avatar can only sign nine clips today. Every new clip needs an "
             "authentic ISL reference recording and signer approval.",
             "NEEDS: AUTHENTIC ISL SOURCE VIDEO"),
            ("PLANNED", "$home_green", "Regional languages",
             "Marathi, Gujarati, Tamil, Telugu, Bengali and Kannada speech output, "
             "using the voices installed on the machine.",
             "NEEDS: A VOICE PER LANGUAGE + SPEAKER REVIEW"),
            ("PLANNED", "$home_orange", "Sentence-level ISL",
             "Moving from isolated signs to real ISL grammar and word order is a "
             "research problem, not a settings toggle.",
             "NEEDS: ISL LINGUIST + CORPUS"),
            ("PLANNED", "$home_green", "Offline-first speech",
             "Keep everything on device by default, with the online voice clearly "
             "opt-in rather than the fallback.",
             "NEEDS: LOCAL TTS ENGINE SHIPPED"),
        ):
            layout.addWidget(self._home_roadmap_row(
                status, colour, name, detail, review))
        return block

    def _home_roadmap_row(self, status: str, colour: str, name: str,
                          detail: str, review: str) -> QFrame:
        row = QFrame()
        row.setObjectName("homeStatRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(14, 11, 14, 11)
        layout.setSpacing(14)
        tag = QLabel(f"<span style='color:{colour}'>{status}</span>")
        tag.setObjectName("homeMono")
        tag.setTextFormat(Qt.TextFormat.RichText)
        tag.setMinimumWidth(72)
        layout.addWidget(tag, 0, Qt.AlignmentFlag.AlignTop)
        stack = QVBoxLayout()
        stack.setSpacing(3)
        head = QLabel(name)
        head.setObjectName("homeRowValue")
        stack.addWidget(head)
        body = QLabel(detail)
        body.setObjectName("homeCardBody")
        body.setWordWrap(True)
        stack.addWidget(body)
        stack.addWidget(self._home_label(review, "homeMono"))
        layout.addLayout(stack, 1)
        return row

    def _home_status(self) -> QFrame:
        card = QFrame()
        card.setObjectName("homeCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(9)
        layout.addWidget(self._home_label("/  WHAT IS RUNNING RIGHT NOW",
                                          "homeMono"))

        rows = []
        if self.backend is None:
            rows.append(("\u2715", "$home_orange", "Recognition backend",
                         "not connected \u2014 no bhashasetu_backend module found"))
        else:
            rows.append(("\u2713", "$home_green", "Recognition backend",
                         f"connected ({self.backend_info})"))
        demo = find_demo_file()
        if demo:
            rows.append(("\u2713", "$home_green", "Avatar clips",
                         f"found, {len(AVATAR_CLIPS)} clips, pending signer review"))
        else:
            rows.append(("\u2715", "$home_orange", "Avatar clips",
                         "demo file not found next to the app"))
        try:
            import importlib
            importlib.import_module("PySide6.QtWebEngineWidgets")
            rows.append(("\u2713", "$home_green", "In-window avatar",
                         "available (WebEngine installed)"))
        except Exception:
            rows.append(("\u2715", "$home_orange", "In-window avatar",
                         "needs: py -m pip install PySide6-WebEngine"))
        rows.append(("\u2713", "$home_green", "Speech",
                     "Windows system voice speaks English text aloud"))
        scout_model = next((ROOT / name for name in (
            "isl_alphabet_model_v3.pkl", "isl_alphabet_model_v2.pkl",
            "isl_alphabet_model.pkl") if (ROOT / name).is_file()), None)
        if scout_model:
            rows.append(("\u2713", "$home_green", "Scout model",
                         f"found: {scout_model.name}; accuracy and signer coverage need review"))
        else:
            rows.append(("\u2715", "$home_orange", "Scout model",
                         "no trained Scout model found in this folder"))

        for marker, colour, label, detail in rows:
            line = QHBoxLayout()
            line.setSpacing(10)
            icon = QLabel(f"<span style='color:{colour}'>{marker}</span>")
            icon.setObjectName("homeRowValue")
            icon.setTextFormat(Qt.TextFormat.RichText)
            icon.setMinimumWidth(18)
            key = QLabel(label)
            key.setObjectName("homeRowValue")
            key.setMinimumWidth(160)
            val = QLabel(detail)
            val.setObjectName("homeCardBody")
            val.setWordWrap(True)
            line.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
            line.addWidget(key, 0, Qt.AlignmentFlag.AlignTop)
            line.addWidget(val, 1)
            layout.addLayout(line)

        layout.addWidget(self._home_label(
            "The checklist above is generated from this machine each time the page "
            "opens. It never reports a model, clip or service that is not present.",
            "homeFootnote"))
        return card

    def _build_sign_page(self) -> QWidget:
        page, layout = self._page_shell("sign")
        content = QGridLayout()
        content.setHorizontalSpacing(16)
        content.setVerticalSpacing(16)
        content.setColumnStretch(0, 17)
        content.setColumnStretch(1, 7)
        left = QVBoxLayout()
        left.setSpacing(16)
        left.addWidget(self._build_camera_card(), 1)
        content.addLayout(left, 0, 0)
        right = QVBoxLayout()
        right.setSpacing(16)
        right.addWidget(self._build_hero_card())
        right.addWidget(self._build_sentence_card(), 1)
        content.addLayout(right, 0, 1)
        layout.addLayout(content, 1)
        self._refresh_sentence(silent=True)      # page just came into existence
        return page

    def _on_word_mode_toggled(self, enabled: bool) -> None:
        self._last_added_word = None
        self.word_mode_button.setText(
            "Words only: ON · Word mode" if enabled
            else "Words only: OFF · Alphabet mode")
        if self.backend is not None and self.backend.set_mode is not None:
            try:
                self.backend.set_mode("word" if enabled else "alphabet")
            except Exception as exc:
                self._handle_backend_error(f"Could not change recognition mode: {exc}")

    def _build_text_sign_page(self) -> QWidget:
        page, layout = self._page_shell("text_sign")
        content = QGridLayout()
        content.setHorizontalSpacing(16)
        content.setVerticalSpacing(16)
        content.setColumnStretch(0, 7)
        content.setColumnStretch(1, 5)
        left = QVBoxLayout()
        left.addWidget(self._build_avatar_card(), 1)
        content.addLayout(left, 0, 0)
        right = QVBoxLayout()
        right.setSpacing(16)
        right.addWidget(self._build_text_to_sign_card())
        right.addWidget(self._build_clip_list_card())
        right.addStretch(1)
        content.addLayout(right, 0, 1)
        layout.addLayout(content, 1)
        return page

    def _build_text_speech_page(self) -> QWidget:
        page, layout = self._page_shell("text_speech")
        content = QGridLayout()
        content.setHorizontalSpacing(16)
        content.setVerticalSpacing(16)
        content.setColumnStretch(0, 7)
        content.setColumnStretch(1, 5)
        content.addWidget(self._build_speech_input_card(), 0, 0)
        right = QVBoxLayout()
        right.setSpacing(16)
        right.addWidget(self._build_voice_card())
        right.addWidget(self._build_speech_info_card())
        right.addStretch(1)
        content.addLayout(right, 0, 1)
        layout.addLayout(content, 1)
        return page

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(14)

        self.brand_tile = QLabel("B")
        self.brand_tile.setObjectName("brandTile")
        self.brand_tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.brand_tile.setFixedSize(48, 48)

        title_stack = QVBoxLayout()
        title_stack.setSpacing(1)
        title = QLabel("BHASHASETU")
        title.setObjectName("appTitle")
        self.subtitle = QLabel("INDIAN SIGN LANGUAGE  \u00b7  LIVE RECOGNITION")
        self.subtitle.setObjectName("appSubtitle")
        title_stack.addWidget(title)
        title_stack.addWidget(self.subtitle)

        header.addWidget(self.brand_tile)
        header.addLayout(title_stack)
        header.addStretch(1)

        self.theme_button = QPushButton("Dark theme")
        self.theme_button.setObjectName("secondaryButton")
        self.theme_button.setToolTip("Switch between light and dark (Ctrl+D)")
        self.theme_button.setAccessibleName("Switch theme")
        self.theme_button.clicked.connect(self.toggle_theme)
        header.addWidget(self.theme_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.status_pill = QFrame()
        self.status_pill.setObjectName("statusPill")
        status_layout = QHBoxLayout(self.status_pill)
        status_layout.setContentsMargins(13, 8, 13, 8)
        status_layout.setSpacing(8)
        self.status_marker = QLabel("\u25cf")
        self.status_marker.setObjectName("statusMarker")
        self.status_marker.setAccessibleName("Status")
        self.status_text = QLabel("Initialising")
        self.status_text.setObjectName("statusText")
        status_layout.addWidget(self.status_marker)
        status_layout.addWidget(self.status_text)
        header.addWidget(self.status_pill, 0, Qt.AlignmentFlag.AlignVCenter)
        return header

    def _build_camera_card(self) -> QFrame:
        card = self._make_card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        head = QHBoxLayout()
        title = QLabel("Live camera")
        title.setObjectName("sectionTitle")
        self.camera_badge = QLabel("CAMERA OFF")
        self.camera_badge.setObjectName("cameraBadge")
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.camera_badge)
        layout.addLayout(head)

        self.preview = VideoPreview()
        layout.addWidget(self.preview, 1)

        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.start_button = QPushButton("Start camera")
        self.start_button.setObjectName("primaryButton")
        self.start_button.setToolTip("Open the camera and begin recognition (Ctrl+Shift+C)")
        self.start_button.setAccessibleName("Start camera")
        self.start_button.clicked.connect(self.start_camera)
        self.stop_button = QPushButton("Stop camera")
        self.stop_button.setObjectName("secondaryButton")
        self.stop_button.setToolTip("Stop the camera and release it (Ctrl+Shift+C)")
        self.stop_button.setAccessibleName("Stop camera")
        self.stop_button.clicked.connect(self.stop_camera)
        self.stop_button.setEnabled(False)
        controls.addWidget(self.start_button)
        controls.addWidget(self.stop_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        hint = QLabel("Recognition and speech run on this computer. "
                      "Speech output may use an online service.")
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return card

    def _build_recent_strip(self) -> QFrame:
        strip = QFrame()
        strip.setObjectName("recentStrip")
        outer = QVBoxLayout(strip)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        holder = QWidget()
        self.recent_layout = QHBoxLayout(holder)
        self.recent_layout.setContentsMargins(0, 0, 0, 0)
        self.recent_layout.setSpacing(7)
        outer.addWidget(holder)
        self._rebuild_recent_chips()
        return strip

    def _build_avatar_card(self) -> QFrame:
        card = self._make_card()
        card.setObjectName("avatarCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 15, 18, 15)
        layout.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel("Avatar \u2014 Text \u2192 Sign")
        title.setObjectName("sectionTitle")
        self.avatar_badge = QLabel("9 CLIPS \u00b7 NOT SIGNER-APPROVED")
        self.avatar_badge.setObjectName("stageBadge")
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.avatar_badge)
        layout.addLayout(head)

        if AvatarStage is not None:
            self.avatar_stage = AvatarStage()
            self.avatar_stage.clip_started.connect(self._on_clip_started)
            self.avatar_stage.ready_changed.connect(self._on_avatar_ready)
            self.avatar_stage.failed.connect(self._on_avatar_failed)
            layout.addWidget(self.avatar_stage, 1)
        else:
            self.avatar_stage = None
            missing = QLabel(
                "avatar_stage.py is not next to this file, so the 3D avatar "
                "cannot be shown. Copy avatar_stage.py into the same folder.")
            missing.setObjectName("avatarMessage")
            missing.setWordWrap(True)
            layout.addWidget(missing, 1)

        self.avatar_note = QLabel(
            "Nine reference-tracked clips only: HELLO, THANK YOU, PLEASE, SORRY, "
            "YES, NO, HELP, WATER, FOOD. Experimental and pending fluent ISL "
            "signer review \u2014 not a validated sign reference.")
        self.avatar_note.setObjectName("sectionHint")
        self.avatar_note.setWordWrap(True)
        layout.addWidget(self.avatar_note)
        return card

    def _build_text_to_sign_card(self) -> QFrame:
        card = self._make_card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel("Text \u2192 Sign")
        title.setObjectName("sectionTitle")
        self.play_btn = QPushButton("Play on avatar")
        self.play_btn.setObjectName("primaryButton")
        self.play_btn.setToolTip(
            "Play the matching clip on the avatar above (Ctrl+P)")
        self.play_btn.setAccessibleName("Play on avatar")
        self.play_btn.clicked.connect(self.play_text_on_avatar)
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.play_btn)
        layout.addLayout(head)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.text_input = QLineEdit()
        self.text_input.setObjectName("textToSignInput")
        self.text_input.setPlaceholderText(
            "Type a word from the nine clips, e.g. HELLO")
        self.text_input.setAccessibleName("Text to play on the avatar")
        self.text_input.returnPressed.connect(self.play_text_on_avatar)
        self.sign_picker = QComboBox()
        self.sign_picker.setObjectName("signPicker")
        self.sign_picker.setAccessibleName("Choose a clip")
        for key, (label, duration) in AVATAR_CLIPS.items():
            self.sign_picker.addItem(f"{label}  ({duration:.1f}s)", key)
        self.sign_picker.activated.connect(self._on_picker_activated)
        row.addWidget(self.text_input, 3)
        row.addWidget(self.sign_picker, 2)
        layout.addLayout(row)

        self.text_to_sign_hint = QLabel(
            "Exact clip names only \u2014 no sentence is translated or invented.")
        self.text_to_sign_hint.setObjectName("textToSignHint")
        self.text_to_sign_hint.setWordWrap(True)
        layout.addWidget(self.text_to_sign_hint)
        return card

    def _build_recent_card(self) -> QFrame:
        card = self._make_card()
        card.setMaximumHeight(132)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(8)
        title = QLabel("Recent signs in this session")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        layout.addWidget(self._build_recent_strip())
        return card

    def _build_clip_list_card(self) -> QFrame:
        card = self._make_card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(8)
        title = QLabel("Clips the avatar actually has")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        for key, (label, duration) in AVATAR_CLIPS.items():
            row = QHBoxLayout()
            name = QLabel(label)
            name.setObjectName("voiceTitle")
            play = QPushButton(f"Play  {duration:.1f}s")
            play.setObjectName("subTab")
            play.setAccessibleName(f"Play the {label} clip")
            play.clicked.connect(lambda _c=False, l=label: self._play_gloss(l))
            row.addWidget(name)
            row.addStretch(1)
            row.addWidget(play)
            layout.addLayout(row)
        note = QLabel(f"All nine are {AVATAR_REVIEW_STATUS} \u2014 experimental, "
                      "not a validated sign reference.")
        note.setObjectName("sectionHint")
        note.setWordWrap(True)
        layout.addWidget(note)
        return card

    # ------------------------------------------------------- Text -> Speech UI
    def _build_speech_input_card(self) -> QFrame:
        card = self._make_card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel("Text to read aloud")
        title.setObjectName("sectionTitle")
        self.speech_count_label = QLabel("0 characters")
        self.speech_count_label.setObjectName("mutedCaption")
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.speech_count_label)
        layout.addLayout(head)

        self.speech_edit = QTextEdit()
        self.speech_edit.setObjectName("sentenceEdit")
        self.speech_edit.setPlaceholderText(
            "Type or paste the text to read aloud. Example: Hello, my name is "
            "Meera. I need water.")
        self.speech_edit.setAccessibleName("Text to read aloud")
        self.speech_edit.textChanged.connect(self._update_speech_count)
        layout.addWidget(self.speech_edit, 1)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.speech_clear_btn = QPushButton("Clear")
        self.speech_clear_btn.setObjectName("secondaryButton")
        self.speech_clear_btn.clicked.connect(self._clear_speech_text)
        self.speech_speak_btn = QPushButton("Speak this text")
        self.speech_speak_btn.setObjectName("primaryButton")
        self.speech_speak_btn.setAccessibleName("Speak this text")
        self.speech_speak_btn.setToolTip("Read the text aloud (Ctrl+Enter)")
        self.speech_speak_btn.clicked.connect(self.speak_speech_text)
        self.speech_stop_btn = QPushButton("Stop speech")
        self.speech_stop_btn.setObjectName("textButton")
        self.speech_stop_btn.clicked.connect(self.stop_speech)
        row.addWidget(self.speech_clear_btn)
        row.addWidget(self.speech_stop_btn)
        row.addStretch(1)
        row.addWidget(self.speech_speak_btn)
        layout.addLayout(row)

        hint = QLabel("Speaks exactly what you typed \u2014 no translation, no "
                      "rewriting, and no microphone is used on this page.")
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return card

    def _build_voice_card(self) -> QFrame:
        card = self._make_card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title = QLabel("Voice")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        self.voice_options: dict[str, QFrame] = {}
        for key, name, detail, offline in (
            ("system", "System voice",
             "Offline voice installed on this PC. No network needed.", True),
            ("online", "Online voice",
             "gTTS \u2014 sends the text to Google. Better coverage, needs internet.", False),
        ):
            option = QFrame()
            option.setObjectName("voiceOption")
            option.setProperty("selected", "false")
            box = QHBoxLayout(option)
            box.setContentsMargins(12, 10, 12, 10)
            box.setSpacing(10)
            text = QVBoxLayout()
            text.setSpacing(2)
            heading = QLabel(name)
            heading.setObjectName("voiceTitle")
            caption = QLabel(detail)
            caption.setObjectName("voiceDetail")
            caption.setWordWrap(True)
            text.addWidget(heading)
            text.addWidget(caption)
            badge = QLabel("OFFLINE" if offline else "SENDS TEXT ONLINE")
            badge.setObjectName("offlineBadge" if offline else "onlineBadge")
            choose = QPushButton("Use")
            choose.setObjectName("subTab")
            choose.setAccessibleName(f"Use the {name}")
            choose.clicked.connect(
                lambda _c=False, k=key: self.select_voice(k))
            box.addLayout(text, 1)
            box.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
            box.addWidget(choose, 0, Qt.AlignmentFlag.AlignVCenter)
            layout.addWidget(option)
            self.voice_options[key] = option

        rate_row = QHBoxLayout()
        rate_row.setSpacing(10)
        rate_label = QLabel("Rate")
        rate_label.setObjectName("confidenceCaption")
        self.rate_slider = QSlider(Qt.Orientation.Horizontal)
        self.rate_slider.setObjectName("rateSlider")
        self.rate_slider.setRange(50, 200)          # percent of normal speed
        self.rate_slider.setValue(100)
        self.rate_slider.setAccessibleName("Speech rate")
        self.rate_slider.valueChanged.connect(self._on_rate_changed)
        self.rate_value = QLabel("1.00\u00d7")
        self.rate_value.setObjectName("rateValue")
        self.rate_value.setMinimumWidth(52)
        rate_row.addWidget(rate_label)
        rate_row.addWidget(self.rate_slider, 1)
        rate_row.addWidget(self.rate_value)
        layout.addLayout(rate_row)

        self.voice_status = QLabel("")
        self.voice_status.setObjectName("sectionHint")
        self.voice_status.setWordWrap(True)
        layout.addWidget(self.voice_status)

        # Apply the saved choice now that the options exist.
        self.select_voice(getattr(self, "_voice_key", "system"))
        self.rate_slider.setValue(int(round(getattr(self, "_speech_rate", 1.0) * 100)))
        return card

    def _build_speech_info_card(self) -> QFrame:
        card = self._make_card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)
        title = QLabel("What this page does not do")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        for line in (
            "It does not translate between languages.",
            "It does not read from the camera or the microphone.",
            "It does not change or correct your wording.",
            "The online voice sends your text to Google; pick the system voice to "
            "keep it offline.",
        ):
            item = QLabel("\u2022  " + line)
            item.setObjectName("sectionHint")
            item.setWordWrap(True)
            layout.addWidget(item)
        layout.addStretch(1)
        return card

    def _build_hero_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("heroCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 15, 18, 16)
        layout.setSpacing(8)

        head = QHBoxLayout()
        caption = QLabel("CURRENT SIGN")
        caption.setObjectName("heroCaption")
        self.live_badge = QLabel("LIVE OUTPUT")
        self.live_badge.setObjectName("liveBadge")
        head.addWidget(caption)
        head.addStretch(1)
        head.addWidget(self.live_badge)
        layout.addLayout(head)

        self.word_mode_button = QPushButton("Words only: OFF · Alphabet mode")
        self.word_mode_button.setObjectName("primaryButton")
        self.word_mode_button.setCheckable(True)
        self.word_mode_button.setMinimumHeight(40)
        self.word_mode_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.word_mode_button.setToolTip(
            "Off recognises alphabet letters. On recognises whole-word signs.")
        self.word_mode_button.toggled.connect(self._on_word_mode_toggled)
        layout.addWidget(self.word_mode_button)

        self.word_value = QLabel("Waiting for a sign")
        self.word_value.setObjectName("heroValue")
        self.word_value.setProperty("state", "empty")
        self.word_value.setWordWrap(True)
        self.word_value.setMinimumHeight(58)
        self.word_value.setAccessibleName("Current sign")
        layout.addWidget(self.word_value)

        self.hero_hint = QLabel("Hold a sign clearly in front of the camera.")
        self.hero_hint.setObjectName("heroHint")
        self.hero_hint.setWordWrap(True)
        self.hero_hint.setMinimumHeight(34)
        self.hero_hint.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.hero_hint)

        confidence_row = QHBoxLayout()
        confidence_row.setSpacing(10)
        confidence_caption = QLabel("CONFIDENCE")
        confidence_caption.setObjectName("confidenceCaption")
        confidence_caption.setMinimumWidth(84)
        self.confidence_bar = ConfidenceBar()
        self.confidence_value = QLabel("\u2014")
        self.confidence_value.setObjectName("confidenceValue")
        self.confidence_value.setMinimumWidth(58)
        self.confidence_value.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        confidence_row.addWidget(confidence_caption)
        confidence_row.addWidget(self.confidence_bar, 1)
        confidence_row.addWidget(self.confidence_value)
        layout.addLayout(confidence_row)
        return card

    def _build_sentence_card(self) -> QFrame:
        card = self._make_card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel("Sentence")
        title.setObjectName("sectionTitle")
        self.word_count_label = QLabel("0 characters")
        self.word_count_label.setObjectName("mutedCaption")
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.word_count_label)
        layout.addLayout(head)

        self.sentence_edit = QTextEdit()
        self.sentence_edit.setObjectName("sentenceEdit")
        self.sentence_edit.setReadOnly(False)
        self.sentence_edit.setPlaceholderText(
            "Sign or type your sentence here. Use the keyboard to edit it.")
        self.sentence_edit.textChanged.connect(self._on_sentence_edited)
        layout.addWidget(self.sentence_edit, 1)

        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.clear_button = QPushButton("Clear")
        self.clear_button.setObjectName("secondaryButton")
        self.clear_button.setToolTip("Clear the sentence (Ctrl+L)")
        self.clear_button.clicked.connect(self.clear_text)
        self.stop_speech_button = QPushButton("Stop speech")
        self.stop_speech_button.setObjectName("textButton")
        self.stop_speech_button.setToolTip("Interrupt speech (Esc)")
        self.stop_speech_button.clicked.connect(self.stop_speech)
        self.speak_button = QPushButton("Speak sentence")
        self.speak_button.setObjectName("primaryButton")
        self.speak_button.setToolTip("Speak the sentence aloud (Ctrl+Enter)")
        self.speak_button.setAccessibleName("Speak sentence")
        self.speak_button.clicked.connect(self.speak_sentence)
        controls.addWidget(self.clear_button)
        controls.addWidget(self.stop_speech_button)
        controls.addStretch(1)
        controls.addWidget(self.speak_button)
        layout.addLayout(controls)

        shortcuts = QLabel("Ctrl+Shift+C camera  \u00b7  Ctrl+P play on avatar  \u00b7  "
                           "Ctrl+Enter speak  \u00b7  Esc stop speech  \u00b7  "
                           "Ctrl+L clear  \u00b7  Ctrl+D theme")
        shortcuts.setObjectName("shortcutHint")
        shortcuts.setWordWrap(True)
        layout.addWidget(shortcuts)
        return card

    @staticmethod
    def _make_card() -> QFrame:
        card = QFrame()
        card.setObjectName("surfaceCard")
        card.setFrameShape(QFrame.Shape.NoFrame)
        return card

    def _install_shortcuts(self) -> None:
        for keys, slot in (
            ("Ctrl+Return", self.speak_active),
            ("Ctrl+Enter", self.speak_active),
            ("Esc", self.stop_speech),
            ("Ctrl+Shift+C", self.toggle_camera),
            ("Ctrl+L", self.clear_text),
            ("Ctrl+P", self.play_text_on_avatar),
            ("Ctrl+D", self.toggle_theme),
        ):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.activated.connect(slot)
            if not hasattr(self, "_shortcuts"):
                self._shortcuts = []
            self._shortcuts.append(shortcut)

    # ----------------------------------------------------------------- theme
    def apply_theme(self, name: str, save: bool = True) -> None:
        self._theme_name = "dark" if name == "dark" else "light"
        self._tokens = THEMES[self._theme_name]
        _PREVIEW_TOKENS.update(self._tokens)
        self.setStyleSheet(_stylesheet(self._tokens))
        self.brand_tile.setStyleSheet(
            "border-radius: 15px;"
            f"border: 1px solid {self._tokens['card_border']};"
            f"color: {self._tokens['brand_text']};"
            "font-size: 20px; font-weight: 800;"
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:1,"
            f" stop:0 {self._tokens['brand_grad_a']}, stop:1 {self._tokens['brand_grad_b']});"
        )
        self.theme_button.setText(
            "Light theme" if self._theme_name == "dark" else "Dark theme")
        self._refresh_rich_labels()
        if save:
            QSettings().setValue("ui/theme", self._theme_name)
        self._refresh_status_marker()

    def _render_rich(self, template: str) -> str:
        """Substitute $theme tokens inside a rich-text label."""
        tokens = getattr(self, "_tokens", THEMES["light"])
        out = template
        for name in sorted(tokens, key=len, reverse=True):
            out = out.replace("$" + name, tokens[name])
        return out

    def _refresh_rich_labels(self) -> None:
        """Rich text is built from tokens, so it must be rebuilt on theme change.

        Widgets store their original token template in a dynamic property the
        first time they are seen; plain text without tokens is left alone.
        """
        for label in self.findChildren(QLabel):
            template = label.property("richTemplate")
            if not template:
                text = label.text()
                if "$home_" not in text:
                    continue
                template = text
                label.setProperty("richTemplate", template)
                label.setTextFormat(Qt.TextFormat.RichText)
            label.setText(self._render_rich(template))

    def toggle_theme(self) -> None:
        self.apply_theme("light" if self._theme_name == "dark" else "dark")

    # Compatibility aliases: earlier releases/scripts called these names.
    def _apply_styles(self) -> None:
        self.apply_theme(self._theme_name, save=False)

    @staticmethod
    def _format_confidence(value: Any) -> str:
        percent = BhashaSetuWindow._confidence_percent(value)
        return "\u2014" if percent is None else f"{percent:.1f}%"

    def _restore_geometry(self) -> None:
        geometry = QSettings().value("ui/geometry")
        if geometry is not None:
            try:
                self.restoreGeometry(geometry)
            except Exception:
                pass

    # ---------------------------------------------------------------- status
    # Widgets live only while their page has been built at least once, so every
    # cross-page update goes through guards like these.
    def _safe_preview(self, state: str) -> None:
        preview = getattr(self, "preview", None)
        if preview is not None:
            preview.set_camera_state(state)

    def _safe_preview_clear(self) -> None:
        preview = getattr(self, "preview", None)
        if preview is not None:
            preview.clear_frame()

    def _safe_confidence(self, percent) -> None:
        bar = getattr(self, "confidence_bar", None)
        if bar is not None:
            bar.set_percent(percent)

    def _set_status(self, message: str, level: str = "ready") -> None:
        self._status_level = level
        self.status_text.setText(message)
        self.status_text.setAccessibleName(f"Status: {message}")
        self._refresh_status_marker()

    def _refresh_status_marker(self) -> None:
        level = getattr(self, "_status_level", "ready")
        token_name, marker, _ = _STATUS_STYLE.get(level, _STATUS_STYLE["ready"])
        colour = getattr(self, "_tokens", THEMES["light"]).get(token_name, "#65758A")
        self.status_marker.setText(marker)
        self.status_dot = self.status_marker          # old name kept for compatibility
        self.status_marker.setStyleSheet(
            f"color: {colour}; font-size: 11px; font-weight: 800;")

    def _set_backend_controls_enabled(self, enabled: bool) -> None:
        for name in ("start_button", "clear_button", "speak_button",
                     "stop_speech_button"):
            button = getattr(self, name, None)
            if button is not None:
                button.setEnabled(enabled)
        if getattr(self, "stop_button", None) is not None:
            self.stop_button.setEnabled(False)

    def _note_for(self, section: str, message: str, level: str = "ready") -> None:
        """Show ``message`` only while ``section`` is the visible page."""
        if getattr(self, "current_section", None) == section:
            self._set_connection_message(message, level)

    def _set_connection_message(self, message: str, level: str = "ready") -> None:
        self.connection_note.setText(message)
        self.connection_note.setProperty("level", level)
        self.connection_note.style().unpolish(self.connection_note)
        self.connection_note.style().polish(self.connection_note)

    # ---------------------------------------------------------------- camera
    def toggle_camera(self) -> None:
        if self.recognition_thread is not None and self.recognition_thread.isRunning():
            self.stop_camera()
        else:
            self.start_camera()

    def start_camera(self) -> None:
        if self.backend is None:
            return
        if self.recognition_thread is not None and self.recognition_thread.isRunning():
            return

        self._safe_preview("starting")
        self._safe_preview_clear()
        if getattr(self, 'camera_badge', None) is not None: self.camera_badge.setText("CONNECTING")
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self._set_status("Starting camera\u2026", "busy")
        self._set_connection_message(
            "Camera permission: the preview starts only because you pressed Start camera.",
            "ready")

        self.recognition_thread = RecognitionThread(self.backend, self)
        self.recognition_thread.prediction_received.connect(self._handle_prediction)
        self.recognition_thread.status_changed.connect(self._handle_recognition_status)
        self.recognition_thread.failed.connect(self._handle_backend_error)
        self.recognition_thread.finished.connect(self._recognition_finished)
        self.recognition_thread.start()

    def stop_camera(self) -> None:
        worker = self.recognition_thread
        if worker is None:
            return
        self.stop_button.setEnabled(False)
        self._set_status("Stopping camera\u2026", "busy")
        worker.request_stop()

    def _handle_recognition_status(self, message: str) -> None:
        if message == "Camera active":
            if getattr(self, 'camera_badge', None) is not None: self.camera_badge.setText("CAMERA ON")
            self._safe_preview("active")
            self._set_status("Recognising \u2014 hold a sign still", "busy")
        elif message == "Camera stopped":
            if getattr(self, 'camera_badge', None) is not None: self.camera_badge.setText("CAMERA OFF")
            self._safe_preview("stopped")
            self._safe_preview_clear()
            self._set_status("Camera stopped", "idle")

    # ------------------------------------------------------------ prediction
    def _set_hero_state(self, state: str, text: str, hint: str) -> None:
        """Show the current sign, or the waiting/last-seen state, without colour alone."""
        if getattr(self, 'word_value', None) is not None: self.word_value.setText(text)
        if getattr(self, 'hero_hint', None) is not None: self.hero_hint.setText(hint)
        if self.word_value.property("state") != state:
            self.word_value.setProperty("state", state)
            self.word_value.style().unpolish(self.word_value)
            self.word_value.style().polish(self.word_value)

    def _expire_current_sign(self) -> None:
        """The last sign stopped being visible and the linger window has passed."""
        self._last_shown_word = None
        self._set_hero_state("empty", "Waiting for a sign",
                             "Hold a sign clearly in front of the camera.")

    def _handle_prediction(self, payload: Any) -> None:
        frame, source_key = extract_frame(payload)
        if frame is not None:
            image = frame_to_qimage(frame, source_key)
            if image is not None:
                self.preview.set_frame(image)

        parsed = parse_prediction(payload)
        if parsed.word is None:
            message = (payload.get("error") if isinstance(payload, dict)
                       else getattr(payload, "error", None))
            if message:
                self._sign_hold_timer.stop()
                self._last_shown_word = None
                self._last_added_word = None
                self._set_hero_state("empty", "Not recognized", str(message))
                self._safe_confidence(None)
                if getattr(self, 'confidence_value', None) is not None:
                    self.confidence_value.setText("\u2014")
                return
            if getattr(self, 'confidence_value', None) is not None: self.confidence_value.setText("\u2014")
            self._safe_confidence(None)
            self._last_added_word = None
            if self._last_shown_word:
                # Keep the word readable for a moment instead of blanking it the
                # instant the hand moves; the hint states it is no longer live.
                self._set_hero_state("lingering", self._last_shown_word,
                                     "Last sign \u2014 no hand detected right now.")
                self._sign_hold_timer.start()
            else:
                self._set_hero_state("empty", "Waiting for a sign",
                                     "Hold a sign clearly in front of the camera.")
            return

        self._sign_hold_timer.stop()
        self._last_shown_word = parsed.word
        self._set_hero_state(
            "live", parsed.word,
            "Recognised sign \u2014 shown exactly as the model reported it.")
        percent = self._confidence_percent(parsed.confidence)
        if percent is None:
            if getattr(self, 'confidence_value', None) is not None: self.confidence_value.setText("n/a")
            self._safe_confidence(None)
        else:
            if getattr(self, 'confidence_value', None) is not None: self.confidence_value.setText(f"{percent:.0f} %")
            self._safe_confidence(percent)

        if self.backend is not None and parsed.word != self._last_added_word:
            # One add per continuous detection; a None frame resets the guard.
            try:
                self.backend.add_word(parsed.word)
            except Exception as exc:
                self._handle_backend_error(f"Could not add the recognised sign: {exc}")
            else:
                self._last_added_word = parsed.word
                self._push_recent(parsed.word)
                self._refresh_sentence(silent=True)

    @staticmethod
    def _confidence_percent(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if number < 0:
            return None
        return number * 100.0 if number <= 1.0 else min(100.0, number)

    def _push_recent(self, word: str) -> None:
        if not word:
            return
        if self._recent_signs and self._recent_signs[0] == word:
            return
        self._recent_signs.insert(0, word)
        del self._recent_signs[RECENT_SIGN_LIMIT:]
        self._rebuild_recent_chips()

    def _rebuild_recent_chips(self) -> None:
        while self.recent_layout.count():
            item = self.recent_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        if not self._recent_signs:
            empty = QLabel("Nothing recognised yet in this session.")
            empty.setObjectName("chipEmpty")
            self.recent_layout.addWidget(empty)
        else:
            for word in self._recent_signs:
                chip = QLabel(word)
                chip.setObjectName("chip")
                self.recent_layout.addWidget(chip)
        self.recent_layout.addStretch(1)

    # --------------------------------------------------------- Text -> Speech
    def _update_speech_count(self) -> None:
        text = self.speech_edit.toPlainText()
        count = len(text)
        self.speech_count_label.setText(
            f"{count} character{'s' if count != 1 else ''}")

    def _clear_speech_text(self) -> None:
        self.speech_edit.clear()
        self._set_connection_message("Cleared the text to read aloud.", "ready")

    def select_voice(self, key: str) -> None:
        self._voice_key = key
        for name, option in self.voice_options.items():
            option.setProperty("selected", "true" if name == key else "false")
            option.style().unpolish(option)
            option.style().polish(option)
        QSettings().setValue("ui/voice", key)
        self._refresh_voice_status()

    def _refresh_voice_status(self) -> None:
        if getattr(self, "voice_status", None) is None:
            return
        key = getattr(self, "_voice_key", "system")
        if key == "online":
            self.voice_status.setText(
                "Online voice selected: the text you speak will be sent to Google's "
                "translation service.")
        else:
            self.voice_status.setText(
                "System voice selected: speech is produced on this computer and the "
                "text is not uploaded.")

    def _on_rate_changed(self, value: int) -> None:
        rate = value / 100.0
        if getattr(self, "rate_value", None) is not None:
            self.rate_value.setText(f"{rate:.2f}\u00d7")
        QSettings().setValue("ui/speech_rate", rate)

    def speak_speech_text(self) -> None:
        """Speak exactly what is in the Text -> Speech box."""
        if self.backend is None:
            self._set_connection_message(
                "The speech backend is not connected, so nothing can be spoken.",
                "warning")
            return
        text = self.speech_edit.toPlainText().strip()
        if not text:
            self._set_connection_message(
                "Type or paste some text first, then press Speak this text.",
                "warning")
            return
        self._launch_backend_task(self.backend.speak, text, task_name="speak-text")
        self._set_status("Reading the text aloud\u2026", "busy")
        if getattr(self, "_voice_key", "system") == "online":
            self._note_for(
                "text_speech",
                "Speaking with the online voice: this text was sent to Google.",
                "warning")
        else:
            self._note_for(
                "text_speech",
                "Speaking with the system voice on this computer.")

    # ------------------------------------------------------------ avatar stage
    def _on_avatar_ready(self, ready: bool) -> None:
        if ready:
            if self.avatar_badge is not None:
                self.avatar_badge.setText("9 CLIPS \u00b7 NOT SIGNER-APPROVED")
            self._note_for(
                "text_sign",
                "Avatar stage ready. It plays its nine bundled clips only; every "
                "clip is still pending fluent ISL signer review.")

    def _on_avatar_failed(self, message: str) -> None:
        self._note_for("text_sign", message, "warning")

    def _on_clip_started(self, label: str) -> None:
        self._set_status(f"Playing {label} on the avatar", "busy")
        if self.text_to_sign_hint is not None:
            self.text_to_sign_hint.setText(
                f"Playing {label}. Experimental clip \u2014 pending signer review.")

    def _on_picker_activated(self, index: int) -> None:
        key = self.sign_picker.itemData(index)
        if not key:
            return
        label = AVATAR_CLIPS.get(key, (str(key), 0.0))[0]
        self.text_input.setText(label)
        self._play_gloss(label)

    def play_text_on_avatar(self) -> None:
        """Play whatever the user typed, if and only if a clip exists for it."""
        text = self.text_input.text().strip()
        if not text:
            self.text_to_sign_hint.setText(
                "Type one of the nine clip names first: HELLO, THANK YOU, PLEASE, "
                "SORRY, YES, NO, HELP, WATER, FOOD.")
            return
        self._play_gloss(text)

    def _play_gloss(self, gloss: str) -> None:
        label = str(gloss).strip()
        if self.avatar_stage is None:
            self.text_to_sign_hint.setText(
                "The avatar stage is not available in this copy of the app.")
            return
        if clip_key_for(label) is None:
            # Never substitute a different sign; say what is missing.
            available = ", ".join(lbl for lbl, _ in AVATAR_CLIPS.values())
            self.text_to_sign_hint.setText(
                f"No avatar clip exists for \u201c{label}\u201d. Nothing was played. "
                f"Available clips: {available}.")
            return
        if not self.avatar_stage.available:
            self.text_to_sign_hint.setText(self.avatar_stage.unavailable_reason())
            return
        if self.avatar_stage.play_gloss(label):
            key = clip_key_for(label)
            index = self.sign_picker.findData(key) if key else -1
            if index >= 0:
                self.sign_picker.setCurrentIndex(index)
            self.text_to_sign_hint.setText(f"Playing {label} on the avatar above.")
        else:
            self.text_to_sign_hint.setText(
                f"No avatar clip exists for \u201c{label}\u201d.")

    # -------------------------------------------------------------- sentence
    def _refresh_sentence(self, silent: bool = False) -> None:
        if self.backend is None or getattr(self, "sentence_edit", None) is None:
            return
        try:
            text = self.backend.get_sentence()
        except Exception as exc:
            if not silent:
                self._handle_backend_error(f"Could not read the sentence: {exc}")
            return
        if text is None:
            text = ""
        text = str(text)
        if self.sentence_edit.toPlainText() != text:
            cursor_position = self.sentence_edit.textCursor().position()
            self.sentence_edit.setPlainText(text)
            cursor = self.sentence_edit.textCursor()
            cursor.setPosition(min(cursor_position, len(text)))
            self.sentence_edit.setTextCursor(cursor)
        self._update_character_count()

    def _on_sentence_edited(self) -> None:
        self._update_character_count()
        if self.backend is not None and self.backend.set_sentence is not None:
            try:
                self.backend.set_sentence(self.sentence_edit.toPlainText())
            except Exception as exc:
                self._handle_backend_error(f"Could not update the sentence: {exc}")

    def clear_text(self) -> None:
        if self.backend is None:
            return
        try:
            self.backend.clear_sentence()
        except Exception as exc:
            self._handle_backend_error(f"Could not clear the sentence: {exc}")
            return
        self.sentence_edit.clear()
        self._last_added_word = None
        self._recent_signs.clear()
        self._rebuild_recent_chips()
        self._set_status("Sentence cleared", "ready")
        self._set_connection_message("The shared sentence was cleared.", "ready")

    def speak_active(self) -> None:
        """Ctrl+Enter speaks the text on the open page."""
        if getattr(self, "current_section", "sign") == "text_speech":
            self.speak_speech_text()
        else:
            self.speak_sentence()

    def speak_sentence(self) -> None:
        if self.backend is None:
            return
        text = self.sentence_edit.toPlainText().strip()
        if not text:
            self._set_connection_message(
                "Nothing to speak yet. Recognise some signs first.", "warning")
            return
        self._launch_backend_task(self.backend.speak, text, task_name="speak")
        self._set_status("Speaking\u2026", "busy")
        self._set_connection_message(
            "Speech is generated by the configured voice; an online voice sends the "
            "sentence to that service.", "ready")

    def stop_speech(self) -> None:
        if self.backend is None:
            return
        self._launch_backend_task(self.backend.stop_speech, task_name="stop speech")
        self._set_status("Speech stopped", "ready")

    # --------------------------------------------------------------- workers
    def _launch_backend_task(
        self, function: Callable, *args: Any, task_name: str = "backend task",
    ) -> None:
        worker = FunctionThread(function, *args, parent=self)
        worker.setObjectName(task_name)
        worker.failed.connect(self._handle_backend_error)
        worker.finished.connect(lambda: self._speech_finished(worker))
        self._background_threads.append(worker)
        worker.start()

    def _remove_background_thread(self, worker: FunctionThread) -> None:
        if worker in self._background_threads:
            self._background_threads.remove(worker)
        worker.deleteLater()

    def _speech_finished(self, worker: FunctionThread) -> None:
        if worker.objectName() == "speak" and not worker.error_text:
            self._set_status("Ready \u2014 camera off" if (
                self.recognition_thread is None or not self.recognition_thread.isRunning()
            ) else "Recognising \u2014 hold a sign still", "ready")
        self._remove_background_thread(worker)
        self._maybe_finish_close()

    def _recognition_finished(self) -> None:
        if self.recognition_thread is not None:
            self.recognition_thread.deleteLater()
            self.recognition_thread = None
        self.start_button.setEnabled(self.backend is not None)
        self.stop_button.setEnabled(False)
        if getattr(self, 'camera_badge', None) is not None: self.camera_badge.setText("CAMERA OFF")
        self._safe_preview("idle")
        self._maybe_finish_close()

    def _maybe_finish_close(self) -> None:
        if not self._close_pending:
            return
        recognition_running = (
            self.recognition_thread is not None and self.recognition_thread.isRunning()
        )
        background_running = any(worker.isRunning() for worker in self._background_threads)
        if not recognition_running and not background_running:
            self._close_pending = False
            QTimer.singleShot(0, self.close)

    def _handle_backend_error(self, message: str) -> None:
        self._set_status("Backend error", "error")
        self._safe_preview("error")
        self._set_connection_message(message, "error")

    def _update_character_count(self) -> None:
        try:
            count = len(self.sentence_edit.toPlainText())
        except Exception:
            count = 0
        self.word_count_label.setText(f"{count} character{'s' if count != 1 else ''}")

    # ----------------------------------------------------------------- close
    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override name
        worker = self.recognition_thread
        recognition_running = worker is not None and worker.isRunning()
        background_running = [task for task in self._background_threads if task.isRunning()]

        if recognition_running or background_running:
            self._close_pending = True
            event.ignore()

            if recognition_running:
                worker.request_stop()

            # A blocking speak() call runs in a worker. Ask the backend to interrupt
            # it before waiting for the worker, while preserving the existing API.
            speech_running = (
                self.backend is not None
                and any(task.function is self.backend.speak for task in background_running)
            )
            stop_already_running = (
                self.backend is not None
                and any(task.function is self.backend.stop_speech for task in background_running)
            )
            if speech_running and not stop_already_running and not self._shutdown_speech_requested:
                self._shutdown_speech_requested = True
                self._launch_backend_task(self.backend.stop_speech, task_name="shutdown speech")

            self._set_status("Stopping services before exit\u2026", "busy")
            self._maybe_finish_close()
            return

        stage = getattr(self, "avatar_stage", None)
        if stage is not None:
            stage.shutdown()

        geometry = self.saveGeometry()
        if geometry is not None:
            QSettings().setValue("ui/geometry", geometry)
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setOrganizationName("BHASHASETU")

    backend, backend_info = load_backend()
    window = BhashaSetuWindow(backend, backend_info)
    window.show()

    if backend is None:
        # Keep the interface usable for layout inspection while clearly identifying
        # that recognition/sentence/speech actions need the real backend adapter.
        QTimer.singleShot(
            250,
            lambda: QMessageBox.information(
                window,
                "Backend not connected",
                "The BHASHASETU interface has launched, but the recognition backend "
                "is not connected yet.\n\n"
                + backend_info
                + "\n\nSee README.md for the adapter and launch instructions.",
            ),
        )

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
