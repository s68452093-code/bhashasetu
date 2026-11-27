# BHASHASETU 1.0 — Integration Compatibility Report

**Scope:** Existing PySide6 GUI ↔ AI 1 recognition backend  
**Contract:** Original eight function names retained  
**GUI redesign:** None

## Compatibility verdict

The GUI is structurally compatible with the agreed function contract, provided AI 1 implements the signatures and lifecycle rules in `README.md`. The actual AI 1 module was not supplied in this review, so its real function signatures, module paths, return payload, and camera shutdown behavior cannot yet be verified against implementation.

## Eight expected backend functions

```python
def start_recognition() -> None: ...
def stop_recognition() -> None: ...
def get_latest_prediction() -> dict[str, Any] | None: ...
def add_word(word: str) -> None: ...
def get_sentence() -> str: ...
def clear_sentence() -> None: ...
def speak(text: str) -> None: ...
def stop_speech() -> None: ...
```

The GUI invokes `start_recognition`, `get_latest_prediction`, and `stop_recognition` in its recognition QThread; sentence functions are called from the GUI thread and must be fast/thread-safe; speech functions run in background QThreads.

## Canonical prediction contract

```python
{
    "word": "HELLO",       # str or None for neutral/no-sign
    "confidence": 0.97,    # float probability 0.0–1.0 or None
    "frame_rgb": frame     # NumPy uint8 array (H, W, 3), RGB order
}
```

For continuous live preview, include the current frame in every snapshot while the camera is active. Return `{"word": None, "confidence": None, "frame_rgb": frame}` for neutral/no-sign. Bare `None` means no snapshot is currently available and does not reset the word deduplication guard.

## Corrections made

1. Added a detached copy of dictionary image buffers before crossing the recognition-to-GUI thread boundary.
2. Ensured `stop_recognition()` is attempted even when `start_recognition()` partially initializes and then raises.
3. Avoided reporting the camera as active when a stop was requested during startup.
4. Added coordinated close handling: camera shutdown is requested, active speech is interrupted using the existing `stop_speech()` function, and the window waits for worker completion.
5. Tightened the `BackendAPI` type annotations and added import-time positional-arity checks for inspectable backend callables.
6. Updated the live-preview waiting message and the README integration specification.

No recognition logic, model code, model weights, camera pipeline code, sentence implementation, speech implementation, or GUI layout was changed.

## AI 1 items still required

- Supply the actual existing module path(s) that export the eight functions. No AI 1 module names were assumed.
- Make `start_recognition()` return after initialization/start rather than running a permanent loop in the call.
- Make `get_latest_prediction()` a fast, non-blocking snapshot read.
- Make `stop_recognition()` idempotent and safe after partial startup; it must release the camera.
- Include a current `frame_rgb` NumPy array in each active prediction snapshot.
- Make sentence-state functions thread-safe.
- Make `stop_speech()` safe concurrently with and capable of interrupting `speak()`.

The GUI's default import name `bhashasetu_backend` is only its existing adapter hook, not a guessed AI 1 recognition module name. Set `BHASHASETU_BACKEND_MODULE` to AI 1's real importable module name, or have the integrator make a thin adapter after AI 1 supplies its actual module paths.

## Validation performed

- Python source compiled with `py_compile`: **PASS**
- Python AST parse: **PASS**
- Backend signature validation logic reviewed (requires 0 positional args for six functions and 1 for `add_word`/`speak`): **PASS**
- ZIP contents checked: **PASS**
- Live PySide6 runtime, camera, model, and speech integration: **NOT RUN** — PySide6 and AI 1 backend modules are not present in this environment.
