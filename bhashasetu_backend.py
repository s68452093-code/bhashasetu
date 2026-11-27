"""Scout model and camera adapter for bhashasetu_gui.py."""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import threading
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
_module_spec = importlib.util.spec_from_file_location(
    "scout_sign_translator", ROOT / "checking regional.py")
if _module_spec is None or _module_spec.loader is None:
    raise ImportError("Could not load checking regional.py")
_scout = importlib.util.module_from_spec(_module_spec)
sys.modules[_module_spec.name] = _scout
_module_spec.loader.exec_module(_scout)

_lock = threading.RLock()
_stop_event = threading.Event()
_worker: threading.Thread | None = None
_camera = None
_tracker = None
_model = None
_voter = None
_latest: dict | None = None
_latest_generation = 0
_delivered_generation = 0
_sentence = ""
_mode = "alphabet"
_error: Exception | None = None
INFERENCE_FPS = 15.0


def set_mode(mode: str) -> None:
    global _mode, _latest
    if mode not in ("alphabet", "word"):
        raise ValueError("mode must be 'alphabet' or 'word'")
    with _lock:
        _mode = mode
        if _voter is not None:
            _voter.reset()
        _latest = None


def start_recognition() -> None:
    global _worker, _camera, _tracker, _model, _voter, _latest, _error
    global _latest_generation, _delivered_generation
    with _lock:
        if _worker is not None and _worker.is_alive():
            return
        _stop_event.clear()
        _latest = None
        _error = None
    model_path = (ROOT / "isl_alphabet_model_v3.pkl" if
                  (ROOT / "isl_alphabet_model_v3.pkl").is_file() else
                  ROOT / "isl_alphabet_model_v2.pkl" if
                  (ROOT / "isl_alphabet_model_v2.pkl").is_file() else
                  ROOT / "isl_alphabet_model.pkl")
    if not model_path.is_file():
        raise FileNotFoundError("No trained Scout sign model was found in this folder.")
    _model = _scout.AlphabetModel(model_path)
    _tracker = _scout.HandTracker()
    _camera = _scout.open_camera()
    # Lower resolution is enough for landmark recognition and reduces the
    # work required by hand, face, and pose tracking on each frame.
    try:
        import cv2
        _camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        _camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        _camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:
        pass
    _voter = _scout.LetterVoter(_scout.VOTE_FRAMES, _scout.VOTE_SHARE)
    with _lock:
        _latest_generation += 1
        _delivered_generation = _latest_generation
    _worker = threading.Thread(target=_capture_loop, name="scout-camera", daemon=True)
    _worker.start()


def _capture_loop() -> None:
    global _latest, _error, _latest_generation
    inference_interval = 1.0 / INFERENCE_FPS
    last_inference = 0.0
    try:
        while not _stop_event.is_set():
            ok, raw = _camera.read()
            if not ok or raw is None:
                time.sleep(0.02)
                continue
            now = time.perf_counter()
            if now - last_inference < inference_interval:
                continue
            last_inference = now
            display, hands, pose, face, _face_points = _tracker.detect(
                raw, _model.mirror, _model.swap)
            height, width = raw.shape[:2]
            ready = bool(hands) and (_model.version < 3 or
                                     (pose is not None and face[0] > 0))
            guesses = (_model.predict(hands, width, height, pose, face,
                                      words_only=_mode == "word") if ready else [])
            label = guesses[0][0] if guesses and guesses[0][1] >= _scout.CONFIDENCE_THRESHOLD else None
            if label is None:
                _voter.reset()
                confirmed = None
            else:
                confirmed = _voter.add(label)
            confidence = guesses[0][1] if confirmed and guesses else None
            word = _scout.display_sign(confirmed) if confirmed else None
            error = None
            if hands and not ready:
                error = "Keep your hands, face, and upper body visible to the camera."
            elif hands and not guesses:
                error = "No sign from this mode is available in the trained model."
            elif hands and guesses and guesses[0][1] < _scout.CONFIDENCE_THRESHOLD:
                error = "Not recognized confidently. Try again or train this sign first."
            elif hands and confirmed is None:
                error = "Hold the sign steady so the model can confirm it."
            payload = {"word": word, "confidence": confidence,
                       "frame": display, "error": error}
            with _lock:
                _latest = payload
                _latest_generation += 1
    except Exception as exc:
        with _lock:
            _error = exc
        _stop_event.set()


def get_latest_prediction():
    global _error, _delivered_generation
    with _lock:
        if _error is not None:
            error = _error
            # Report the failure once so the GUI worker can stop cleanly.
            _error = None
            raise RuntimeError(str(error))
        if _latest is None or _latest_generation == _delivered_generation:
            return None
        _delivered_generation = _latest_generation
        return dict(_latest)


def stop_recognition() -> None:
    global _camera, _tracker, _worker, _latest
    _stop_event.set()
    worker = _worker
    if worker is not None and worker.is_alive():
        worker.join(timeout=3.0)
    if _camera is not None:
        try:
            _camera.release()
        except Exception:
            pass
    if _tracker is not None:
        try:
            _tracker.close()
        except Exception:
            pass
    with _lock:
        _camera = _tracker = _worker = None
        _latest = None


def add_word(word: str) -> None:
    global _sentence
    value = str(word or "").strip().upper()
    if not value:
        return
    with _lock:
        if _mode == "word":
            if _sentence and not _sentence.endswith(" "):
                _sentence += " "
            _sentence += value + " "
        else:
            _sentence += value


def get_sentence() -> str:
    with _lock:
        return _sentence


def clear_sentence() -> None:
    global _sentence
    with _lock:
        _sentence = ""


def set_sentence(text: str) -> None:
    global _sentence
    with _lock:
        _sentence = str(text or "")


def speak(text: str) -> None:
    value = " ".join(str(text).split()).replace("'", "''")
    if not value:
        return
    if os.name != "nt":
        raise RuntimeError("English speech playback uses the Windows built-in voice.")
    command = (
        "Add-Type -AssemblyName System.Speech; "
        "$voice = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$voice.Speak('{value}'); $voice.Dispose()"
    )
    startup_info = subprocess.STARTUPINFO()
    startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup_info.wShowWindow = subprocess.SW_HIDE
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, text=True, timeout=120,
        startupinfo=startup_info,
        creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or "Windows speech failed").strip())


def stop_speech() -> None:
    # Speech runs in the GUI's worker thread; the Windows synthesizer completes
    # the current short sentence without holding up camera or window updates.
    return None
