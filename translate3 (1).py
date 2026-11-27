"""
ISL Alphabet Translator  -  translate3.py
Make Pro Academy | ISL Bridge

Reads Indian Sign Language alphabet signs from the webcam, builds a word from
them and speaks it. Loads isl_alphabet_model_v2.pkl (made by train_model.py)
if it exists, otherwise your first model, isl_alphabet_model.pkl.
Needs isl_common.py in the same folder.

Install once (Command Prompt):
    py -m pip install mediapipe opencv-python scikit-learn pandas pyttsx3

Keys (click the camera window first so it receives them):
    SPACE       add the CONFIRMED letter (works after your hands move away)
    BACKSPACE   delete the last letter
    ENTER       speak the word
    A           auto-add on/off (hold a sign steady for a second to type it)
    M           mirror on/off for the model     } only for the first model,
    H           swap left/right hands on/off    } if its letters come out wrong
    C           clear the word
    Q or ESC    quit
"""

import os
import queue
import subprocess
import sys
import threading
import time
from collections import Counter, deque

import cv2
import joblib
import numpy as np
import pandas as pd

from isl_common import (DIM_GREEN, FEATURE_NAMES_V2, GREEN, GREY, LIGHT_BLUE,
                        MIRROR_MODEL_INPUT, NEW_MODEL_PATH, OLD_MODEL_PATH,
                        V2_MODEL_PATH, RAW_COLUMNS,
                        SWAP_HANDS, WHITE, YELLOW, HandTracker, darken, draw_hand,
                        draw_face, draw_pose, fail,
                        features_v2, fit_display, open_camera, put_text, raw_vector,
                        show_message)

# =====================================================================
# SETTINGS
# =====================================================================

CONFIDENCE_THRESHOLD = 0.50   # a frame votes only when the model is this sure
VOTE_FRAMES = 15              # recent frames that vote (about half a second)
VOTE_SHARE = 0.60             # share of those votes a letter needs
STEADY_SECONDS = 0.5          # ...then held this long, it shows as CONFIRMED

AUTO_ADD = True               # type a letter by holding its sign (A key toggles)
HOLD_SECONDS = 1.0            # how long to hold a sign for auto-add
RELEASE_SECONDS = 0.5         # pause needed before the same letter is typed again
SPACE_MEMORY_SECONDS = 3.0    # SPACE types the CONFIRMED letter up to this long
                              # after your hands move away

SPEECH_RATE = 150             # words per minute
WINDOW_NAME = "ISL Alphabet Translator"


# =====================================================================
# ALPHABET MODEL
# =====================================================================

def class_to_letter(value, labels):
    """Turn one class of the model into the letter to show.

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
        names = FEATURE_NAMES_V2 if self.version == 2 else RAW_COLUMNS
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

        kind = "position-independent (v2)" if self.version == 2 else "first model (v1)"
        print(f"Model: {type(self.model).__name__}, {kind}, {len(self.letters)} signs")
        print("Signs:", " ".join(self.letters))
        if accuracy is not None:
            value = float(accuracy)
            print(f"Saved accuracy: {value * 100 if value <= 1 else value:.1f} %")

    def predict(self, hands, width, height):
        """Best guesses for one frame: [(letter, probability), ...], best first."""
        if self.version == 2:
            vector = features_v2(hands, width, height)
        else:
            vector = raw_vector(hands)
        row = vector[self.positions]
        if self.with_names:
            inputs = pd.DataFrame([row], columns=self.columns)
        else:
            inputs = row.reshape(1, -1)
        if not self.has_proba:
            return [(class_to_letter(self.model.predict(inputs)[0], self.labels), 1.0)]
        probabilities = self.model.predict_proba(inputs)[0]
        best = np.argsort(probabilities)[::-1][:3]
        return [(self.letters[i], float(probabilities[i])) for i in best]


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
    """Turns confirmed letters into a word.

    - A letter that stays confirmed for STEADY_SECONDS shows in the CONFIRMED
      box, and SPACE types exactly that letter - even a few seconds after the
      hands move. Two-handed signs need this: one hand leaves the sign to press
      SPACE, and a letter seen only briefly during that movement never
      becomes steady.
    - Auto-add types a letter once it is held for HOLD_SECONDS.
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
        """Call once per frame. Returns the letter typed automatically, if any."""
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
            self.add(confirmed)
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
        """SPACE: type the letter in the CONFIRMED box."""
        letter, _ = self.confirmed_letter(now)
        if letter:
            self.add(letter)
        return letter

    def add(self, letter):
        self.text += letter
        self.typed = letter
        self.steady = None          # SPACE again needs the sign again

    def backspace(self):
        self.text = self.text[:-1]

    def clear(self):
        self.text = ""
        self.steady = None


# =====================================================================
# SPEECH
# =====================================================================

class Speaker:
    """Speaks words on one background thread so the video never freezes.

    A new speech engine on a new thread for every word makes Windows speech
    work once and then fail. Here one thread owns the voice for the whole run."""

    def __init__(self, words_per_minute):
        self.words_per_minute = words_per_minute
        self.jobs = queue.Queue()
        threading.Thread(target=self._work, daemon=True).start()

    def say(self, text):
        self.jobs.put(text)

    def _work(self):
        if sys.platform == "win32":
            voice = self._windows_voice()
            methods = ([voice.Speak] if voice is not None else []) + [self._speak_powershell]
        else:
            methods = [self._speak_pyttsx3]
        while True:
            text = self.jobs.get()
            for speak in methods:
                try:
                    speak(text)
                    break
                except Exception as error:
                    print("Speech error:", error)

    def _windows_voice(self):
        """Windows' own SAPI voice - the engine pyttsx3 uses - driven directly."""
        try:
            import comtypes
            import comtypes.client
            comtypes.CoInitialize()               # COM has to start in this thread
            voice = comtypes.client.CreateObject("SAPI.SpVoice")
        except Exception:
            try:
                import pythoncom
                import win32com.client
                pythoncom.CoInitialize()
                voice = win32com.client.Dispatch("SAPI.SpVoice")
            except Exception:
                return None
        try:
            voice.Rate = max(-10, min(10, round((self.words_per_minute - 150) / 20)))
        except Exception:
            pass
        return voice

    @staticmethod
    def _speak_powershell(text):
        """Fallback that needs no Python packages: PowerShell's speech engine."""
        safe = "".join(ch for ch in text if ch.isalnum() or ch == " ")
        command = ("Add-Type -AssemblyName System.Speech; "
                   "(New-Object System.Speech.Synthesis.SpeechSynthesizer)"
                   f".Speak('{safe}')")
        subprocess.run(["powershell", "-NoProfile", "-Command", command],
                       check=True, timeout=60,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def _speak_pyttsx3(self, text):
        import pyttsx3
        engine = pyttsx3.init()                   # a fresh engine for every word
        engine.setProperty("rate", self.words_per_minute)
        engine.say(text)
        engine.runAndWait()
        engine.stop()


# =====================================================================
# DRAWING
# =====================================================================

def draw_overlay(frame, guesses, confirmed, progress, hand_count, fps,
                 word, auto_add, mirror, swap, version, message):
    height, width = frame.shape[:2]
    s = width / 1280.0                             # scale with the frame size
    top, bottom = int(150 * s), int(125 * s)
    darken(frame, 0, 0, width, top)
    darken(frame, 0, height - bottom, width, height)

    # Top left: what the model sees in this frame
    put_text(frame, "ISL ALPHABET TRANSLATOR", (20 * s, 38 * s), 0.85 * s, WHITE)
    if guesses:
        letter, probability = guesses[0]
        sure = probability >= CONFIDENCE_THRESHOLD
        put_text(frame, f"Sign: {letter}   {probability * 100:.0f}%", (20 * s, 90 * s),
                 1.2 * s, YELLOW if sure else GREY, 3)
        others = [f"{l} {p * 100:.0f}%" for l, p in guesses[1:] if p >= 0.01]
        if others:
            put_text(frame, "Next guesses:  " + "    ".join(others),
                     (20 * s, 132 * s), 0.65 * s, GREY)
    else:
        put_text(frame, "Sign: -", (20 * s, 90 * s), 1.2 * s, GREY, 3)
        put_text(frame, "Show your hand(s) to the camera", (20 * s, 132 * s), 0.65 * s, GREY)

    # Top right: confirmed letter and the hold bar
    x0 = width - 360 * s
    bar_x0, bar_x1 = x0 + 120 * s, width - 25 * s
    room = bar_x1 - bar_x0
    box_letter, live = confirmed                # dim green = remembered for SPACE
    put_text(frame, "CONFIRMED", (x0, 38 * s), 0.7 * s, WHITE)
    put_text(frame, box_letter or "-", (x0, 128 * s), 2.6 * s,
             GREEN if live else DIM_GREEN if box_letter else GREY, 5, max_width=110 * s)
    put_text(frame, f"Hands: {hand_count}    FPS: {fps:.0f}", (bar_x0, 70 * s), 0.6 * s,
             WHITE, max_width=room)
    cv2.rectangle(frame, (int(bar_x0), int(85 * s)), (int(bar_x1), int(105 * s)), GREY, 2)
    if progress > 0:
        fill_x = bar_x0 + (bar_x1 - bar_x0) * progress
        cv2.rectangle(frame, (int(bar_x0), int(85 * s)), (int(fill_x), int(105 * s)), GREEN, -1)
    hint = "hold the sign to type it" if auto_add else "press SPACE to type it"
    put_text(frame, hint, (bar_x0, 132 * s), 0.55 * s, GREY, max_width=room)

    # Bottom: the word, the modes and the keys
    put_text(frame, "WORD: " + word + "_", (20 * s, height - 78 * s), 1.3 * s, WHITE, 3,
             max_width=width - 40 * s)
    if version == 2:
        modes = f"Auto-add (A): {'ON' if auto_add else 'OFF'}      Model: trained by you (v2)"
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
    print("\nISL ALPHABET TRANSLATOR")
    print("-" * 50)
    print("Click the camera window first, then use these keys:")
    print("  SPACE      add the CONFIRMED letter")
    print("  BACKSPACE  delete the last letter")
    print("  ENTER      speak the word")
    print("  A          auto-add on/off (hold a sign to type it)")
    print("  M / H      mirror / swap hands (first model only)")
    print("  C          clear the word")
    print("  Q or ESC   quit")
    print("  W          add a space between words")
    print("-" * 50)


# =====================================================================
# MAIN LOOP
# =====================================================================

def main():
    if os.path.exists(NEW_MODEL_PATH):
        fail("This older translator cannot use the new face/body model. "
             "Run checking regional.py instead.")
    elif os.path.exists(V2_MODEL_PATH):
        alphabet = AlphabetModel(V2_MODEL_PATH)
    elif os.path.exists(OLD_MODEL_PATH):
        alphabet = AlphabetModel(OLD_MODEL_PATH)
    else:
        fail("No model found. Record signs with collect_data.py, then run train_model.py.")

    tracker = HandTracker()
    camera = open_camera()
    speaker = Speaker(SPEECH_RATE)
    voter = LetterVoter(VOTE_FRAMES, VOTE_SHARE)
    word = WordBuilder()

    auto_add, mirror_input, swap_hands = AUTO_ADD, alphabet.mirror, alphabet.swap
    message, message_until = "", 0.0
    fps, previous = 0.0, time.monotonic()
    failed_reads, window_sized = 0, False

    def show(text):
        nonlocal message, message_until
        message, message_until = text, time.monotonic() + 1.5
        print(text)

    print_controls()
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)

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
            display, hands, pose, _face, face_points = tracker.detect(
                raw, mirror_input, swap_hands)
            height, width = raw.shape[:2]

            # ---------- PREDICT AND STABILIZE
            guesses = alphabet.predict(hands, width, height) if hands else []
            vote = guesses[0][0] if guesses and guesses[0][1] >= CONFIDENCE_THRESHOLD else None
            confirmed = voter.add(vote)

            now = time.monotonic()
            typed = word.update(confirmed, now, auto_add)
            if typed:
                show("Added " + typed)
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
                         len(hands), fps, word.text, auto_add, mirror_input,
                         swap_hands, alphabet.version, message)
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
                show("Added " + letter if letter else "No letter confirmed yet")
            elif key in (8, 127):                                   # BACKSPACE
                word.backspace()
            elif key in (13, 10):                                   # ENTER
                if word.text:
                    speaker.say(word.text)
                    show("Speaking: " + word.text)
            elif key in (ord("w"), ord("W")):
                word.text += " "
                word.typed = None
                word.steady = None
                show("Space added")

            elif key in (ord("c"), ord("C")):
                word.clear()
                show("Word cleared")
            elif key in (ord("a"), ord("A")):
                auto_add = not auto_add
                show("Auto-add " + ("ON" if auto_add else "OFF"))
            elif key in (ord("m"), ord("M"), ord("h"), ord("H")):
                if alphabet.version == 2:
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
