# BHASHASETU 1.0 — Scout GUI Integration

## Run the integrated Scout app

From this folder, install the packages once with `py -m pip install -r requirements.txt`,
then launch `py bhashasetu_gui.py`. The **Sign → Text** page uses the Scout v3 model
from this folder. Its **Words only** toggle switches between alphabet labels and whole
word labels. The **Text → Sign** page plays the bundled avatar demo inside the same
window; it does not open another browser window. The avatar currently contains nine
reference clips and they are pending fluent ISL signer review.

If the GUI opens without the camera backend or embedded avatar, install the requirements
above with Python 3.11 and restart the app.

## Backend integration contract

This document is the integration specification for the existing PySide6 GUI. The UI,
recognition model, camera pipeline, sentence state, and speech engine remain separate.
The GUI does not implement recognition, modify weights, or open a second camera.

## 1. Exact public function signatures

The backend module imported by the GUI must expose these eight callables with the stated
positional arguments and behavior:

```python
from typing import Any
import numpy as np


def start_recognition() -> None:
    """Start/initialize the existing recognition pipeline and return promptly."""


def stop_recognition() -> None:
    """Stop the pipeline and release camera resources; safe to call after partial startup."""


def get_latest_prediction() -> dict[str, Any] | None:
    """Return the latest prediction + current camera frame snapshot, or None if unavailable."""


def add_word(word: str) -> None:
    """Append one recognized word to the shared sentence state."""


def get_sentence() -> str:
    """Return the current sentence as a string."""


def clear_sentence() -> None:
    """Clear the shared sentence state."""


def speak(text: str) -> None:
    """Speak text; this function may block until speech completes or is stopped."""


def stop_speech() -> None:
    """Stop current speech; safe to call concurrently with speak()."""
```

The parameter names `word` and `text` should be used as shown. The GUI calls the two
one-argument functions positionally, so the parameter names do not affect invocation,
but matching these signatures keeps the contract clear. The other six functions take
no arguments. Return values other than those documented are ignored by the GUI.

At backend load time, the GUI checks that all eight names are callable and checks the
required positional argument count whenever Python exposes an inspectable signature.
Some extension/decorated callables do not expose signatures; those are still checked for
callability and any mismatch will be reported when invoked. The GUI does not infer or
validate runtime return types beyond parsing the documented prediction/sentence values.

## 2. Canonical prediction dictionary

AI 1 should return this dictionary from `get_latest_prediction()`:

```python
{
    "word": "HELLO",                  # str; None when no sign is currently detected
    "confidence": 0.97,              # float from 0.0 to 1.0; None when word is None
    "frame_rgb": frame_rgb           # optional here; required for live preview
}
```

`frame_rgb` must be a NumPy `ndarray` with:

- `dtype == numpy.uint8`
- shape `(height, width, 3)`
- RGB channel order
- an image representing the current camera frame

For live preview, include the current frame in **each** snapshot returned while the camera
is active, not only when a sign changes. The GUI polls `get_latest_prediction()` roughly
every 60 ms and displays the most recently supplied frame. The GUI also accepts the
existing alias `frame_bgr` for OpenCV BGR arrays; `frame_rgb` is the preferred canonical
key. A `frame` key is interpreted as BGR for backwards compatibility.

Prediction semantics are important:

- `word` is a recognized class/word as a non-empty string.
- Use `word: None` (and `confidence: None`) for a no-sign/neutral/release state. This
  resets the GUI's one-add-per-continuous-detection guard, allowing the same word to be
  signed again after a pause.
- Return `None` only when no snapshot is available yet. It does **not** mean no sign;
  the GUI leaves the previous displayed word and deduplication state unchanged.
- Keep returning a current snapshot while the camera is active so that frames continue
  updating even when the recognized word remains unchanged.
- Confidence should be a probability from 0.0 through 1.0. The GUI converts this to a
  percentage. Values from 0 through 100 are also displayed, but 0–1 is the agreed format.

The GUI retains compatibility with common legacy prediction forms (`label`/`score`,
`word`/`confidence`, tuples, strings, or objects), but AI 1 should implement the canonical
dictionary above so frame and word data travel together unambiguously.

## 3. Threading and lifecycle requirements

The GUI invokes backend functions from these threads:

| Function(s) | Calling thread | Requirement |
|---|---|---|
| `start_recognition()` | Recognition QThread | Initialize/start and return; do not run a permanent loop inside this call |
| `get_latest_prediction()` | Recognition QThread | Fast, thread-safe snapshot read; do not block waiting for a new frame |
| `stop_recognition()` | Recognition QThread, in `finally` | Idempotent; signal/join backend capture work and release camera resources |
| `add_word()`, `get_sentence()`, `clear_sentence()` | GUI thread | Must be short and thread-safe because recognition and UI actions can overlap |
| `speak()` | Speech QThread | May block until speech ends; must not access Qt widgets |
| `stop_speech()` | Separate Speech QThread | Must be safe while `speak()` is executing and should interrupt it promptly |

Additional rules for AI 1:

1. `start_recognition()` must not contain the full camera loop. Start the existing camera/
   inference worker and return. Otherwise Stop Camera cannot be processed until the call
   returns.
2. `get_latest_prediction()` must return promptly (ideally a snapshot immediately
   available under a short lock). A blocking camera read here delays Stop Camera because
   the GUI worker cannot check its stop event until the call returns.
3. Do not mutate or reuse the returned frame buffer after returning it. The corrected GUI
   makes a frame copy before emitting it across the Qt thread boundary, but the backend
   should still publish a valid frame snapshot.
4. `stop_recognition()` must be safe after a partial/failed start, signal the capture loop
   to stop, release the camera, and return only after cleanup is complete. It is called
   from the recognition worker's `finally` block even if startup raises.
5. `add_word`, `get_sentence`, and `clear_sentence` must share one sentence state and use
   a lock (or equivalent synchronization) around shared state.
6. `stop_speech()` must be safe to call concurrently with a blocking `speak()` call. The
   GUI also calls it during shutdown if speech is still running.

## 4. Live-frame transport — no extra function required

The agreed eight-function contract is unchanged. The camera frame is carried as the
`frame_rgb` field in the dictionary returned by `get_latest_prediction()`. This avoids a
second camera handle and does not require a new `get_latest_frame()` function or signal.

The corrected recognition worker snapshots/copies image values that provide `.copy()`
(e.g. NumPy arrays and QImages) before sending the payload to the GUI thread. The GUI then
converts the array to a detached `QImage` and scales it into the existing preview widget.
Invalid or missing frames do not stop word recognition; the preview remains in its
waiting state.

## 5. Backend module connection — no guessed AI 1 module names

The GUI has an import hook with default adapter name `bhashasetu_backend`. This is the
GUI-side adapter name only; it is **not** an assumed name for AI 1's recognition module.
Do not rename or replace AI 1 modules to match it.

If AI 1 already exposes all eight functions from one importable module, set
`BHASHASETU_BACKEND_MODULE` to that module's actual Python import name before launching.
If the functions are split across existing modules, the project integrator should create
one thin adapter named `bhashasetu_backend.py` in the project root and re-export the eight
existing callables. The actual import paths must be supplied by AI 1; this GUI does not
invent them or add placeholder imports to the project.

## 6. Error and shutdown behavior in the corrected GUI

- Missing functions and incompatible inspectable positional signatures are reported
  before camera startup.
- Exceptions from start, prediction polling, and stop are caught and shown as backend
  errors.
- `stop_recognition()` is attempted even if `start_recognition()` raises partway through
  initialization, enabling safe cleanup.
- The returned frame is copied before it crosses from the worker thread to the GUI thread
  to avoid display races with a reused camera buffer.
- Closing the window requests camera shutdown and waits for the recognition worker to end.
- If `speak()` is still running on close, the GUI calls `stop_speech()` in a separate
  worker and waits for outstanding workers before destroying the window.

A backend call that never returns cannot be forcibly interrupted by Python's GUI thread.
Therefore the prompt-return and thread-safe requirements above are essential.

## 7. Dependencies

The GUI runtime dependency is pinned in `requirements.txt`:

```bat
python -m pip install -r requirements.txt
```

The canonical live-frame format uses NumPy arrays. Install the NumPy version compatible
with AI 1's existing OpenCV/inference dependencies in the same Python environment. Do
not independently upgrade/downgrade AI 1's OpenCV, ML, CUDA, or model packages as part of
this GUI integration.

## 8. Launch

From the project root with the project's Python 3.11 environment activated:

```bat
python bhashasetu_gui.py
```

If the actual backend module exports all eight functions under a different import name:

```bat
set BHASHASETU_BACKEND_MODULE=<actual_module_import_name>
python bhashasetu_gui.py
```

The angle-bracketed value above is a placeholder to be replaced with the real module
name confirmed by AI 1. Do not type the brackets literally.

## 9. AI 1 handoff checklist

- [ ] Confirm the real module path(s) that expose the eight functions.
- [ ] Match all eight signatures and thread/lifecycle behavior in Sections 1 and 3.
- [ ] Return the canonical dictionary in Section 2.
- [ ] Include a current `frame_rgb` array in every active snapshot for live preview.
- [ ] Return `word: None` for neutral/no-sign frames; reserve bare `None` for no snapshot.
- [ ] Verify stop releases the camera after normal stop and after a startup exception.
- [ ] Verify `stop_speech()` interrupts an active `speak()` call.
- [ ] Test the integrated GUI with the actual camera, model, and installed dependencies.

No recognition engine, model, weights, training script, or AI 1 module is changed by this GUI.
