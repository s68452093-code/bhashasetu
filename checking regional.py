"""
ISL Alphabet Translator  -  translate3.py
Make Pro Academy | ISL Bridge

Reads Indian Sign Language alphabet and held-word signs from the webcam,
builds sentence text and speaks it. Loads isl_alphabet_model_v3.pkl when trained,
or falls back to the earlier hand-only model for alphabet recognition.
Needs isl_common.py in the same folder.

Install once (Command Prompt):
    py -m pip install mediapipe opencv-python scikit-learn pandas edge-tts playsound==1.2.2

Keys (click the camera window first so it receives them):
    SPACE       add the CONFIRMED letter
    W           add a space between words
    BACKSPACE   delete the last character
    ENTER       show the sentence in English and speak it aloud
    A           auto-add on/off
    M / H       mirror / swap hands (first model only)
    C           clear the sentence
    Q or ESC    quit
"""

import os
import asyncio
import hashlib
import html
import json
import queue
import subprocess
import sys
import threading
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, deque

import cv2
import joblib
import numpy as np
import pandas as pd

from isl_common import (DIM_GREEN, FEATURE_NAMES_V2, FEATURE_NAMES_V3, GREEN, GREY,
                        LIGHT_BLUE, MIRROR_MODEL_INPUT, NEW_MODEL_PATH, OLD_MODEL_PATH,
                        V2_MODEL_PATH, RAW_COLUMNS,
                        SWAP_HANDS, WHITE, YELLOW, HandTracker, darken, draw_hand,
                        draw_face, draw_pose, fail, features_v2, features_v3,
                        fit_display, open_camera, put_text, raw_vector, show_message)

# =====================================================================
# SETTINGS
# =====================================================================

CONFIDENCE_THRESHOLD = 0.50   # a frame votes only when the model is this sure
VOTE_FRAMES = 15              # recent frames that vote (about half a second)
VOTE_SHARE = 0.60             # share of those votes a letter needs
STEADY_SECONDS = 0.5          # ...then held this long, it shows as CONFIRMED

AUTO_ADD = True               # type a sign by holding it (A key toggles)
HOLD_SECONDS = 1.0            # how long to hold a sign for auto-add
RELEASE_SECONDS = 0.5         # pause needed before the same letter is typed again
SPACE_MEMORY_SECONDS = 3.0    # SPACE types the CONFIRMED letter up to this long
                              # after your hands move away

# Keep output in English for now; Enter speaks the recognized sentence aloud.
TARGET_LANGUAGE = "en"
LANGUAGE_NAMES = {
    "en": "English",
    "hi": "Hindi", "pa": "Punjabi", "bn": "Bengali", "gu": "Gujarati",
    "mr": "Marathi", "ta": "Tamil", "te": "Telugu", "kn": "Kannada",
    "ml": "Malayalam", "ur": "Urdu", "as": "Assamese"
}
TARGET_LANGUAGE_NAME = LANGUAGE_NAMES.get(TARGET_LANGUAGE, TARGET_LANGUAGE)

WINDOW_NAME = "ISL Sign Sentence Builder"


# =====================================================================
# ALPHABET MODEL
# =====================================================================

def class_to_letter(value, labels):
    """Turn one class of the model into its saved sign label.

    Works whether the model learned the letters themselves ("A") or numbers
    (0, 1, 2...) with a saved list, dict or LabelEncoder that names them."""
    if isinstance(value, str):
        return value.strip().upper()
    try:
        number = int(value)
    except (TypeError, ValueError):
        return str(value).upper()
    if isinstance(labels, dict):
        for key in (number, str(number)):
            if key in labels:
                return str(labels[key]).strip().upper()
        for name, code in labels.items():           # {"A": 0, "B": 1} style
            if not isinstance(code, str) and code == number:
                return str(name).strip().upper()
    elif hasattr(labels, "classes_"):                # a saved LabelEncoder
        return str(labels.classes_[number]).strip().upper()
    elif labels is not None and 0 <= number < len(labels):
        return str(labels[number]).strip().upper()


def display_sign(label):
    """Hide the training-only prefix used to distinguish word classes."""
    label = str(label or "").strip().upper()
    return label[5:] if label.startswith("WORD_") else label
    return str(value).upper()


def use_single_thread(estimator):
    """A RandomForest saved with n_jobs=-1 starts a thread pool for every
    prediction, which is slow when predicting one frame at a time."""
    if hasattr(estimator, "n_jobs"):
        try:
            estimator.n_jobs = 1
        except Exception:
            pass
    for step in getattr(estimator, "steps", None) or []:      # Pipeline
        if isinstance(step, tuple) and len(step) == 2:
            use_single_thread(step[1])


class AlphabetModel:
    """The trained scikit-learn model plus what it needs to read one frame."""

    def __init__(self, path):
        print("Loading", path)
        try:
            data = joblib.load(path)
        except Exception as error:
            fail(f"Could not load the model ({type(error).__name__}: {error}).\n"
                 "If it was trained on another computer, install the same "
                 "scikit-learn version here.")

        if isinstance(data, dict):
            self.model = data.get("model")
            saved_columns = data.get("feature_columns")
            self.labels = data.get("labels")
            accuracy = data.get("accuracy")
            self.version = int(data.get("feature_version", 1))
            self.mirror = bool(data.get("mirror", MIRROR_MODEL_INPUT))
            self.swap = bool(data.get("swap", SWAP_HANDS))
        else:
            self.model, saved_columns, self.labels, accuracy = data, None, None, None
            self.version, self.mirror, self.swap = 1, MIRROR_MODEL_INPUT, SWAP_HANDS
        if self.model is None or not hasattr(self.model, "classes_"):
            fail(f"{path} does not hold a trained scikit-learn model.")

        # Version 2 = position-independent inputs (train_model.py),
        # version 1 = raw screen positions (the first model).
        names = (FEATURE_NAMES_V3 if self.version == 3 else
                 FEATURE_NAMES_V2 if self.version == 2 else RAW_COLUMNS)
        position = {name: i for i, name in enumerate(names)}

        # Use the column order the model was fitted with, if it remembers it.
        self.with_names = hasattr(self.model, "feature_names_in_")
        if self.with_names:
            self.columns = [str(c) for c in self.model.feature_names_in_]
        elif saved_columns is not None:
            self.columns = [str(c) for c in saved_columns]
        else:
            self.columns = list(names)
        unknown = [c for c in self.columns if c not in position]
        if unknown:
            fail("The model was trained on inputs this translator does not make, "
                 "for example: " + ", ".join(unknown[:4]))
        expected = getattr(self.model, "n_features_in_", len(self.columns))
        if expected != len(self.columns):
            fail(f"The model expects {expected} inputs, "
                 f"but {len(self.columns)} input names were found.")
        self.positions = np.array([position[c] for c in self.columns])

        use_single_thread(self.model)
        self.has_proba = hasattr(self.model, "predict_proba")
        self.letters = [class_to_letter(c, self.labels) for c in self.model.classes_]

        kind = (f"hand/face/body (v{self.version})" if self.version >= 3 else
                "position-independent (v2)" if self.version == 2 else "first model (v1)")
        print(f"Model: {type(self.model).__name__}, {kind}, {len(self.letters)} signs")
        print("Signs:", " ".join(self.letters))
        if accuracy is not None:
            value = float(accuracy)
            print(f"Saved accuracy: {value * 100 if value <= 1 else value:.1f} %")

    def predict(self, hands, width, height, pose=None, face=None, words_only=False):
        """Best sign guesses for one frame, highest score first."""
        if self.version >= 3:
            vector = features_v3(hands, pose, face, width, height)
        elif self.version == 2:
            vector = features_v2(hands, width, height)
        else:
            vector = raw_vector(hands)
        row = vector[self.positions]
        if self.with_names:
            inputs = pd.DataFrame([row], columns=self.columns)
        else:
            inputs = row.reshape(1, -1)
        def matches_mode(label):
            label = str(label).strip().upper()
            is_word = label.startswith("WORD_") or len(label) != 1
            return is_word if words_only else (len(label) == 1 and "A" <= label <= "Z")

        if not self.has_proba:
            label = class_to_letter(self.model.predict(inputs)[0], self.labels)
            return [(label, 1.0)] if matches_mode(label) else []
        probabilities = self.model.predict_proba(inputs)[0]
        allowed = np.array([matches_mode(label) for label in self.letters])
        if not np.any(allowed):
            return []
        # Preserve raw model scores; mode filtering must not make a weak
        # prediction look more confident by renormalizing the remaining labels.
        best = np.argsort(np.where(allowed, probabilities, -1.0))[::-1][:3]
        return [(self.letters[i], float(probabilities[i])) for i in best if allowed[i]]


# =====================================================================
# STEADY LETTERS AND THE WORD
# =====================================================================

class LetterVoter:
    """Majority vote over the last few frames.

    Each frame votes for its letter, or None when the model is unsure or no
    hand is visible. One shaky frame no longer wipes out the history."""

    def __init__(self, frames, share):
        self.votes = deque(maxlen=frames)
        self.needed = max(1, round(frames * share))

    def add(self, letter):
        self.votes.append(letter)
        counts = Counter(vote for vote in self.votes if vote is not None)
        if counts:
            best, count = counts.most_common(1)[0]
            if count >= self.needed:
                return best
        return None

    def reset(self):
        self.votes.clear()


class WordBuilder:
    """Turns confirmed alphabet or whole-word signs into sentence text.

    - A letter that stays confirmed for STEADY_SECONDS shows in the CONFIRMED
      box, and SPACE types exactly that letter - even a few seconds after the
      hands move. Two-handed signs need this: one hand leaves the sign to press
      SPACE, and a letter seen only briefly during that movement never
      becomes steady.
    - Alphabet classes append one character; WORD_ classes append a whole
      word with separators. Auto-add still adds a held class only once.
    - Holding a sign never repeats it; for a double letter, lower your hands
      briefly or show another sign in between."""

    def __init__(self):
        self.text = ""
        self.holding = None         # confirmed letter being held right now
        self.hold_start = 0.0
        self.gap_start = None       # when the confirmed letter disappeared
        self.typed = None           # letter already typed during this hold
        self.steady = None          # letter in the CONFIRMED box (what SPACE types)
        self.steady_time = 0.0      # last time it was seen

    def update(self, confirmed, now, auto_add):
        """Call once per frame. Returns the sign label added automatically."""
        if confirmed is None:
            if self.gap_start is None:
                self.gap_start = now
            if now - self.gap_start >= RELEASE_SECONDS:
                self.holding = None
                self.typed = None
            return None

        self.gap_start = None
        if confirmed != self.holding:
            self.holding, self.hold_start = confirmed, now
        held = now - self.hold_start
        if held >= STEADY_SECONDS:
            self.steady, self.steady_time = confirmed, now
        if auto_add and confirmed != self.typed and held >= HOLD_SECONDS:
            self.add_sign(confirmed)
            return confirmed
        return None

    def confirmed_letter(self, now):
        """(letter in the CONFIRMED box or None, is it being signed right now?)"""
        if self.steady and now - self.steady_time <= SPACE_MEMORY_SECONDS:
            live = self.steady == self.holding and self.gap_start is None
            return self.steady, live
        return None, False

    def progress(self, now):
        """How far the current hold is towards auto-add, from 0 to 1."""
        if self.holding is None or self.gap_start is not None or self.holding == self.typed:
            return 0.0
        return min(1.0, (now - self.hold_start) / HOLD_SECONDS)

    def add_confirmed(self, now):
        """SPACE: add the alphabet or word sign in the CONFIRMED box."""
        sign, _ = self.confirmed_letter(now)
        if sign:
            self.add_sign(sign)
        return sign

    def add_sign(self, sign):
        """Append a single letter, or a whole WORD_ class, to the sentence."""
        sign = str(sign).strip().upper()
        if sign.startswith("WORD_"):
            token = sign[5:].strip()
            if not token:
                return
            if self.text and not self.text.endswith(" "):
                self.text += " "
            self.text += token + " "
        else:
            self.text += sign
        self.typed = sign
        self.steady = None

    def add(self, letter):
        # Retained as a compatibility alias for older callers.
        self.add_sign(letter)

    def add_space(self):
        """Insert one word separator and allow the next sign to be typed."""
        if self.text and not self.text.endswith(" "):
            self.text += " "
        self.holding = None
        self.hold_start = 0.0
        self.gap_start = None
        self.typed = None
        self.steady = None

    def backspace(self):
        self.text = self.text[:-1]
        self.typed = None
        self.steady = None

    def clear(self):
        self.text = ""
        self.holding = None
        self.hold_start = 0.0
        self.gap_start = None
        self.typed = None
        self.steady = None


# =====================================================================
# SPEECH
# =====================================================================

class Speaker:
    """Translate English text with MyMemory and speak it with Microsoft Edge TTS.

    This avoids the unofficial Google Translate endpoint and Google gTTS,
    which were returning rate-limit/server errors.
    Translation and speech are handled by separate services.
    """

    MIN_TRANSLATION_INTERVAL = 1.3
    MAX_TRANSLATION_ATTEMPTS = 3
    TRANSLATION_URL = "https://api.mymemory.translated.net/get"

    # Known reliable Microsoft neural voice for Hindi. Other supported codes
    # are resolved from Edge TTS's live voice list when first needed.
    FIXED_VOICES = {
        "en": "en-US-AriaNeural",
        "hi": "hi-IN-SwaraNeural",
        "gu": "gu-IN-DhwaniNeural",
        "mr": "mr-IN-AarohiNeural",
        "ta": "ta-IN-PallaviNeural",
        "te": "te-IN-ShrutiNeural",
        "kn": "kn-IN-SapnaNeural",
        "ml": "ml-IN-SobhanaNeural",
        "ur": "ur-IN-GulNeural",
    }
    LOCALES = {
        "en": "en-US",
        "hi": "hi-IN", "pa": "pa-IN", "bn": "bn-IN", "gu": "gu-IN",
        "mr": "mr-IN", "ta": "ta-IN", "te": "te-IN", "kn": "kn-IN",
        "ml": "ml-IN", "ur": "ur-IN", "as": "as-IN",
    }

    def __init__(self, language_code):
        self.language_code = language_code
        self.language_name = LANGUAGE_NAMES.get(language_code, language_code)
        self.jobs = queue.Queue()
        self.pending = set()
        self.last_enqueued = {}
        self.lock = threading.Lock()
        self.last_translation_request = 0.0
        self.last_translation = ""
        self.voice_name = None

        self.cache_dir = os.path.join(tempfile.gettempdir(), "isl_translator_cache")
        self.audio_cache_dir = os.path.join(self.cache_dir, "audio")
        os.makedirs(self.audio_cache_dir, exist_ok=True)
        self.translation_cache_file = os.path.join(self.cache_dir, "translations.json")
        try:
            with open(self.translation_cache_file, "r", encoding="utf-8") as cache_file:
                self.translation_cache = json.load(cache_file)
            if not isinstance(self.translation_cache, dict):
                self.translation_cache = {}
        except (OSError, ValueError, TypeError):
            self.translation_cache = {}

        threading.Thread(target=self._work, daemon=True).start()

    def say(self, text):
        """Queue one sentence; ignore repeated ENTER presses for that sentence."""
        text = " ".join(str(text).split())
        if not text:
            print("Nothing to translate. Sign or spell some text first.")
            return False

        now = time.monotonic()
        with self.lock:
            if text in self.pending:
                print("This sentence is already being translated. Please wait.")
                return False
            if now - self.last_enqueued.get(text, -999.0) < 2.0:
                print("Duplicate request ignored. Please wait.")
                return False
            self.pending.add(text)
            self.last_enqueued[text] = now

        self.jobs.put(text)
        print(f"Queued for {self.language_name}: {text}")
        return True

    def _work(self):
        while True:
            text = self.jobs.get()
            try:
                self._translate_and_speak(text)
            except Exception as error:
                print("\nTRANSLATION/SPEECH FAILED:", repr(error))
                print("Check internet access and run the install command shown at the top of this file.")
                print("You can press ENTER once more after fixing the problem.")
            finally:
                with self.lock:
                    self.pending.discard(text)
                self.jobs.task_done()

    def _save_translation_cache(self):
        try:
            temporary_cache = self.translation_cache_file + ".tmp"
            with open(temporary_cache, "w", encoding="utf-8") as cache_file:
                json.dump(self.translation_cache, cache_file, ensure_ascii=False, indent=2)
            os.replace(temporary_cache, self.translation_cache_file)
        except OSError as error:
            print("Warning: could not save translation cache:", error)

    def _translate_one(self, text):
        """MyMemory requires an explicit source language; signs spell English."""
        params = {
            "q": text,
            "langpair": f"en|{self.language_code}",
            "mt": "1",
        }
        url = self.TRANSLATION_URL + "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 ISL-Bridge/1.0",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=25) as response:
            payload = json.loads(response.read().decode("utf-8"))

        status = int(payload.get("responseStatus", 0) or 0)
        if status != 200:
            details = payload.get("responseDetails") or payload.get("quotaFinished") or "Unknown API error"
            raise RuntimeError(f"MyMemory translation API returned {status}: {details}")

        translated = payload.get("responseData", {}).get("translatedText", "")
        translated = html.unescape(str(translated)).strip()
        if not translated:
            raise RuntimeError("The translation service returned an empty result.")
        return translated

    @staticmethod
    def _split_for_api(text, max_bytes=450):
        """Keep each MyMemory query below its documented 500-byte limit."""
        words = text.split()
        chunks, current = [], ""
        for word in words:
            candidate = word if not current else current + " " + word
            if len(candidate.encode("utf-8")) <= max_bytes:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                if len(word.encode("utf-8")) > max_bytes:
                    raise ValueError("A single word is too long for the translation API.")
                current = word
        if current:
            chunks.append(current)
        return chunks or [text]

    def _cached_translation(self, text):
        if self.language_code == "en":
            return text
        cache_key = self.language_code + "|" + text.casefold()
        cached = self.translation_cache.get(cache_key)
        if isinstance(cached, str) and cached.strip():
            print("Using saved translation (no translation request needed).")
            return cached

        pieces = self._split_for_api(text)
        translated_pieces = []
        for piece in pieces:
            last_error = None
            for attempt in range(self.MAX_TRANSLATION_ATTEMPTS):
                elapsed = time.monotonic() - self.last_translation_request
                if elapsed < self.MIN_TRANSLATION_INTERVAL:
                    time.sleep(self.MIN_TRANSLATION_INTERVAL - elapsed)
                self.last_translation_request = time.monotonic()
                try:
                    translated_pieces.append(self._translate_one(piece))
                    last_error = None
                    break
                except Exception as error:
                    last_error = error
                    if attempt + 1 < self.MAX_TRANSLATION_ATTEMPTS:
                        delay = 2 * (attempt + 1)
                        print(f"Translation service problem: {error}. Retrying in {delay}s...")
                        time.sleep(delay)
            if last_error is not None:
                raise RuntimeError(f"Could not translate '{piece}': {last_error}")

        translated = " ".join(translated_pieces).strip()
        self.translation_cache[cache_key] = translated
        self._save_translation_cache()
        return translated

    async def _resolve_voice(self):
        if self.voice_name:
            return self.voice_name
        if self.language_code in self.FIXED_VOICES:
            self.voice_name = self.FIXED_VOICES[self.language_code]
            return self.voice_name

        # Discover a matching Microsoft voice for languages not in FIXED_VOICES.
        import edge_tts
        locale = self.LOCALES.get(self.language_code)
        voices = await edge_tts.list_voices()
        candidates = [v for v in voices if locale and v.get("Locale", "").lower() == locale.lower()]
        if not candidates:
            raise RuntimeError(
                f"Microsoft Edge TTS has no voice listed for language '{self.language_name}'."
            )
        candidates.sort(key=lambda v: (v.get("Gender") != "Female", v.get("ShortName", "")))
        self.voice_name = candidates[0]["ShortName"]
        return self.voice_name

    async def _generate_audio(self, text, path):
        import edge_tts
        voice = await self._resolve_voice()
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(path)

    def _cached_audio_path(self, translated):
        cache_key = (self.language_code + "|" + translated).encode("utf-8")
        filename = hashlib.sha256(cache_key).hexdigest() + ".mp3"
        return os.path.join(self.audio_cache_dir, filename)

    def _translate_and_speak(self, text):
        translated = self._cached_translation(text)
        self.last_translation = translated
        print(f"\nEnglish: {text}")
        print(f"{self.language_name}: {translated}")

        if self.language_code == "en" and os.name == "nt":
            # Use Windows' built-in SAPI voice for English. This avoids the
            # Edge TTS download and MP3-player dependencies for this mode.
            escaped_text = translated.replace("'", "''")
            powershell = (
                "Add-Type -AssemblyName System.Speech; "
                "$voice = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                f"$voice.Speak('{escaped_text}'); $voice.Dispose()"
            )
            print("Speaking in English using the Windows voice...")
            startup_info = subprocess.STARTUPINFO()
            startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup_info.wShowWindow = subprocess.SW_HIDE
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", powershell],
                capture_output=True, text=True, timeout=120,
                startupinfo=startup_info,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if result.returncode != 0:
                details = (result.stderr or result.stdout or "Windows speech failed").strip()
                raise RuntimeError(details)
            print("Speech finished.")
            return

        audio_path = self._cached_audio_path(translated)
        if not os.path.isfile(audio_path) or os.path.getsize(audio_path) == 0:
            temporary_audio = audio_path + ".tmp.mp3"
            try:
                asyncio.run(self._generate_audio(translated, temporary_audio))
                if not os.path.isfile(temporary_audio) or os.path.getsize(temporary_audio) < 100:
                    raise RuntimeError("Microsoft Edge TTS did not create a valid audio file.")
                os.replace(temporary_audio, audio_path)
            finally:
                if os.path.exists(temporary_audio):
                    try:
                        os.remove(temporary_audio)
                    except OSError:
                        pass

        from playsound import playsound
        print("Playing translated speech...")
        playsound(audio_path, block=True)
        print("Speech finished.")


# =====================================================================
# DRAWING
# =====================================================================

def draw_overlay(frame, guesses, confirmed, progress, hand_count, body_visible,
                 face_visible, fps,
                 word, auto_add, mirror, swap, version, message, words_only,
                 toggle_rect):
    height, width = frame.shape[:2]
    s = width / 1280.0                             # scale with the frame size
    top, bottom = int(150 * s), int(125 * s)
    darken(frame, 0, 0, width, top)
    darken(frame, 0, height - bottom, width, height)

    # Top left: what the model sees in this frame
    put_text(frame, "ISL SIGN SENTENCE BUILDER", (20 * s, 38 * s), 0.85 * s, WHITE)
    button_w, button_h = int(250 * s), int(42 * s)
    bx1, by1 = width // 2 + button_w // 2, int(18 * s)
    bx0, by0 = bx1 - button_w, by1 + button_h
    toggle_rect[:] = [bx0, by1, bx1, by0]
    cv2.rectangle(frame, (bx0, by1), (bx1, by0), GREEN if words_only else GREY, -1)
    button_text = "WORDS ONLY: ON" if words_only else "WORDS ONLY: OFF"
    put_text(frame, button_text, (bx0 + 10 * s, by1 + 29 * s), 0.62 * s, WHITE, 2)
    if guesses:
        letter, probability = guesses[0]
        sure = probability >= CONFIDENCE_THRESHOLD
        put_text(frame, f"Sign: {display_sign(letter)}   {probability * 100:.0f}%", (20 * s, 90 * s),
                 1.2 * s, YELLOW if sure else GREY, 3)
        others = [f"{display_sign(l)} {p * 100:.0f}%" for l, p in guesses[1:] if p >= 0.01]
        if others:
            put_text(frame, "Next guesses:  " + "    ".join(others),
                     (20 * s, 132 * s), 0.65 * s, GREY)
    else:
        put_text(frame, "Sign: -", (20 * s, 90 * s), 1.2 * s, GREY, 3)
        put_text(frame, "Show hands, face and upper body to the camera",
                 (20 * s, 132 * s), 0.65 * s, GREY)

    # Top right: confirmed letter and the hold bar
    x0 = width - 360 * s
    bar_x0, bar_x1 = x0 + 120 * s, width - 25 * s
    room = bar_x1 - bar_x0
    box_letter, live = confirmed                # dim green = remembered for SPACE
    put_text(frame, "CONFIRMED", (x0, 38 * s), 0.7 * s, WHITE)
    put_text(frame, display_sign(box_letter) or "-", (x0, 128 * s), 2.6 * s,
             GREEN if live else DIM_GREEN if box_letter else GREY, 5, max_width=110 * s)
    tracking = (f"Hands: {hand_count}  Face: {'yes' if face_visible else 'no'}  "
                f"Body: {'yes' if body_visible else 'no'}  FPS: {fps:.0f}")
    put_text(frame, tracking, (bar_x0, 70 * s), 0.6 * s,
             WHITE, max_width=room)
    cv2.rectangle(frame, (int(bar_x0), int(85 * s)), (int(bar_x1), int(105 * s)), GREY, 2)
    if progress > 0:
        fill_x = bar_x0 + (bar_x1 - bar_x0) * progress
        cv2.rectangle(frame, (int(bar_x0), int(85 * s)), (int(fill_x), int(105 * s)), GREEN, -1)
    hint = "hold the sign to type it" if auto_add else "press SPACE to type it"
    put_text(frame, hint, (bar_x0, 132 * s), 0.55 * s, GREY, max_width=room)

    # Bottom: the word, the modes and the keys
    put_text(frame, "TEXT: " + word + "_", (20 * s, height - 78 * s), 1.3 * s, WHITE, 3,
             max_width=width - 40 * s)
    if version >= 2:
        modes = f"Auto-add (A): {'ON' if auto_add else 'OFF'}      Model: trained by you (v{version})"
    else:
        modes = (f"Auto-add (A): {'ON' if auto_add else 'OFF'}      "
                 f"Mirror (M): {'ON' if mirror else 'OFF'}      "
                 f"Swap hands (H): {'ON' if swap else 'OFF'}")
    put_text(frame, modes, (20 * s, height - 42 * s), 0.6 * s, LIGHT_BLUE)
    put_text(frame, "SPACE add  |  BACKSPACE delete  |  ENTER speak  |  C clear  |  Q quit",
             (20 * s, height - 12 * s), 0.55 * s, GREY, 1)
    if message:
        show_message(frame, message, bottom)


def print_controls():
    print("\nISL SIGN SENTENCE BUILDER")
    print("-" * 50)
    print("Click the camera window first, then use these keys:")
    print("  SPACE      add the CONFIRMED letter or word")
    print("  W          add a space between words")
    print("  BACKSPACE  delete the last character")
    print("  ENTER      translate and speak the sentence")
    print("  T          test translation and speech using HELLO")
    print("  A          auto-add on/off (hold a sign to add it)")
    print("  Click WORDS ONLY button to switch between word and alphabet signs")
    print("  M / H      mirror / swap hands (first model only)")
    print("  C          clear the word")
    print("  Q or ESC   quit")
    print("-" * 50)


# =====================================================================
# MAIN LOOP
# =====================================================================

def main():
    if os.path.exists(NEW_MODEL_PATH):
        alphabet = AlphabetModel(NEW_MODEL_PATH)
    elif os.path.exists(V2_MODEL_PATH):
        alphabet = AlphabetModel(V2_MODEL_PATH)
    elif os.path.exists(OLD_MODEL_PATH):
        alphabet = AlphabetModel(OLD_MODEL_PATH)
    else:
        fail("No model found. Record signs with collect_data.py, then run train_model.py.")

    tracker = HandTracker()
    camera = open_camera()
    speaker = Speaker(TARGET_LANGUAGE)
    print(f"Translation and speech language: {TARGET_LANGUAGE_NAME} ({TARGET_LANGUAGE})")
    voter = LetterVoter(VOTE_FRAMES, VOTE_SHARE)
    word = WordBuilder()

    auto_add, mirror_input, swap_hands = AUTO_ADD, alphabet.mirror, alphabet.swap
    words_only = False
    toggle_rect = [0, 0, 0, 0]
    message, message_until = "", 0.0
    fps, previous = 0.0, time.monotonic()
    failed_reads, window_sized = 0, False
    last_enter_time = 0.0

    def show(text):
        nonlocal message, message_until
        message, message_until = text, time.monotonic() + 1.5
        print(text)

    print_controls()
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)

    def on_mouse(event, x, y, _flags, _param):
        nonlocal words_only
        if event == cv2.EVENT_LBUTTONDOWN:
            x0, y0, x1, y1 = toggle_rect
            if x0 <= x <= x1 and y0 <= y <= y1:
                words_only = not words_only
                voter.reset()
                show("Word-only mode " + ("ON" if words_only else "OFF - alphabet mode"))

    cv2.setMouseCallback(WINDOW_NAME, on_mouse)

    try:
        while True:
            # ---------- CAPTURE AND DETECT HANDS
            ok, raw = camera.read()
            if not ok or raw is None:
                failed_reads += 1
                if failed_reads > 30:
                    print("The camera stopped sending pictures.")
                    break
                time.sleep(0.01)
                continue
            failed_reads = 0
            display, hands, pose, face, face_points = tracker.detect(
                raw, mirror_input, swap_hands)
            height, width = raw.shape[:2]

            # ---------- PREDICT AND STABILIZE
            ready_for_model = (bool(hands) and
                               (alphabet.version < 3 or
                                (pose is not None and face[0] > 0)))
            guesses = (alphabet.predict(hands, width, height, pose, face, words_only)
                       if ready_for_model else [])
            vote = guesses[0][0] if guesses and guesses[0][1] >= CONFIDENCE_THRESHOLD else None
            confirmed = voter.add(vote)

            now = time.monotonic()
            typed = word.update(confirmed, now, auto_add)
            if typed:
                show("Added " + display_sign(typed))
            if now - previous > 0:
                current = 1.0 / (now - previous)
                fps = current if fps == 0 else 0.9 * fps + 0.1 * current
            previous = now
            if now > message_until:
                message = ""

            # ---------- DISPLAY
            display = fit_display(display)
            for side, points in hands.items():
                draw_hand(display, points, side, flip_x=not mirror_input)
            draw_pose(display, pose, flip_x=not mirror_input)
            draw_face(display, face_points, flip_x=not mirror_input)
            progress = word.progress(now) if auto_add else 0.0
            draw_overlay(display, guesses, word.confirmed_letter(now), progress,
                         len(hands), pose is not None, bool(face[0]), fps, word.text,
                         auto_add, mirror_input,
                         swap_hands, alphabet.version, message, words_only,
                         toggle_rect)
            cv2.imshow(WINDOW_NAME, display)
            if not window_sized:
                cv2.resizeWindow(WINDOW_NAME, display.shape[1], display.shape[0])
                window_sized = True

            # ---------- KEYBOARD
            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q"), ord("Q")):
                break
            elif key == 32:                                         # SPACE
                letter = word.add_confirmed(now)
                show("Added " + display_sign(letter) if letter else "No sign confirmed yet")
            elif key in (ord("w"), ord("W")):                     # WORD SPACE
                word.add_space()
                show("Word space added")
            elif key in (8, 127):                                   # BACKSPACE
                word.backspace()
            elif key in (13, 10):                                   # ENTER
                # OpenCV can repeat a held key. Ignore rapid ENTER repeats.
                if now - last_enter_time >= 1.5:
                    last_enter_time = now
                    sentence = word.text.strip()
                    if sentence:
                        if speaker.say(sentence):
                            show(f"Translating and speaking in {TARGET_LANGUAGE_NAME}")
            elif key in (ord("t"), ord("T")):
                if speaker.say("Hello"):
                    show(f"Testing {TARGET_LANGUAGE_NAME} translation and speech")
            elif key in (ord("c"), ord("C")):
                word.clear()
                show("Text cleared")
            elif key in (ord("a"), ord("A")):
                auto_add = not auto_add
                show("Auto-add " + ("ON" if auto_add else "OFF"))
            elif key in (ord("m"), ord("M"), ord("h"), ord("H")):
                if alphabet.version >= 2:
                    show("Not needed - your new model already matches the camera")
                elif key in (ord("m"), ord("M")):
                    mirror_input = not mirror_input
                    voter.reset()
                    show("Mirror for model " + ("ON" if mirror_input else "OFF"))
                else:
                    swap_hands = not swap_hands
                    voter.reset()
                    show("Swap hands " + ("ON" if swap_hands else "OFF"))

            if cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1:
                break                                       # closed with the X button
    finally:
        camera.release()
        tracker.close()
        cv2.destroyAllWindows()
        print("\nTranslator closed.")


if __name__ == "__main__":
    main()
