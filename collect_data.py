"""
collect_data.py - record your own ISL signs to train the model.

How to use
  1. Set SIGNS_TO_RECORD for letters. Add whole-word signs to
     WORDS_TO_RECORD (for example ["HELLO", "HELP"]).
  2. Run this file. Show the sign, then press SPACE. Each sign is recorded
     in the configured number of rounds, after a 3-second countdown:
     normal position, a little closer, then further back and to one side.
     Move your hands slightly while it records.
  3. When you are done, run train_model.py.

New recordings are saved in this project's isl_data_v3 folder, one CSV per sign.
Recording a sign again adds more samples. Press D twice to delete a sign's
samples and start that sign again.

Keys (click the camera window first):
    SPACE   record the sign shown (SPACE again stops)
    N / P   next / previous sign
    D       delete this sign's samples (press twice)
    Q, ESC  quit
"""

import math
import os
import time

import cv2
import pandas as pd

from isl_common import (DATA_DIR, FACE_RAW_COLUMNS, MIRROR_MODEL_INPUT,
                        POSE_RAW_COLUMNS, RAW_COLUMNS, GREEN, GREY, RED, WHITE,
                        YELLOW, HandTracker, darken, draw_hand, fail, fit_display,
                        open_camera, pose_raw_vector, put_text, raw_vector,
                        show_message, draw_pose, draw_face)

# =====================================================================
# SETTINGS
# =====================================================================

SIGNS_TO_RECORD = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"   # alphabet classes to record
WORDS_TO_RECORD = ["HELLO", "THANK YOU", "PLEASE", "SORRY", "YES", "NO", "HELP", "WATER", "FOOD", "I", "YOU", "WANT", "NEED", "GIVE", "MORE", "AGAIN", "WHAT", "WHERE"]                            # e.g. ["HELLO", "HELP", "THANK YOU"]
ROUNDS = 5                   # recordings per sign, from different positions
SAMPLES_PER_ROUND = 60        # frames saved per round (about 2.5 seconds)
COUNTDOWN_SECONDS = 3
ROUND_TIPS = [
    "normal position",
    "come a little closer",
    "move back a little and to one side",
]
WINDOW_NAME = "Record ISL signs"
DATA_COLUMNS = (["label", "round", "width", "height"] + RAW_COLUMNS
                + POSE_RAW_COLUMNS + FACE_RAW_COLUMNS)


def data_file(sign):
    # Class labels are also filenames; keep spaces readable and remove path
    # separators/punctuation that could escape the recordings folder.
    safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in sign).strip()
    return os.path.join(DATA_DIR, f"{safe_name}.csv")


def count_samples(sign):
    if not os.path.exists(data_file(sign)):
        return 0
    with open(data_file(sign)) as file:
        return max(0, sum(1 for _ in file) - 1)


def save_round(sign, rows):
    path = data_file(sign)
    pd.DataFrame(rows, columns=DATA_COLUMNS).to_csv(
        path, mode="a", header=not os.path.exists(path), index=False)


def draw_screen(frame, sign, number, total, saved, state, round_no, progress,
                countdown, hand_count, body_visible, face_visible, message):
    height, width = frame.shape[:2]
    s = width / 1280.0
    top, bottom = int(175 * s), int(75 * s)
    darken(frame, 0, 0, width, top)
    darken(frame, 0, height - bottom, width, height)

    put_text(frame, "RECORD ISL SIGNS", (20 * s, 40 * s), 0.85 * s, WHITE)
    put_text(frame, f"Sign {number} of {total}     Saved for {sign}: {saved} samples",
             (20 * s, 82 * s), 0.7 * s, GREY)
    big_color = WHITE
    if state == "ready":
        line, color = f"Show the sign for {sign}, then press SPACE", YELLOW
    elif state == "countdown":
        tip = ROUND_TIPS[round_no % len(ROUND_TIPS)]
        line, color = f"Round {round_no + 1} of {ROUNDS}: {tip}", YELLOW
    else:
        big_color = GREEN
        if hand_count and body_visible and face_visible:
            line, color = (f"RECORDING round {round_no + 1} of {ROUNDS} - "
                           "keep hands, face and upper body visible"), GREEN
        else:
            line, color = "Show hands, face and upper body - nothing is saved yet", RED
    put_text(frame, line, (20 * s, 125 * s), 0.75 * s, color, max_width=width - 260 * s)
    if state == "recording":
        x0, x1 = 20 * s, 720 * s
        cv2.rectangle(frame, (int(x0), int(142 * s)), (int(x1), int(160 * s)), GREY, 2)
        cv2.rectangle(frame, (int(x0), int(142 * s)),
                      (int(x0 + (x1 - x0) * progress), int(160 * s)), GREEN, -1)
    put_text(frame, sign, (width - 200 * s, 150 * s), 4.0 * s, big_color, 8,
             max_width=180 * s)

    if state == "countdown":                       # beside the letter, not over the hands
        put_text(frame, str(countdown), (width - 340 * s, 150 * s), 3.5 * s, YELLOW, 8)

    status = (f"Hands: {hand_count}   Body: {'OK' if body_visible else '-'}   "
              f"Face: {'OK' if face_visible else '-'}")
    put_text(frame, status, (20 * s, height - 42 * s), 0.8 * s,
             WHITE if hand_count and body_visible and face_visible else RED)
    put_text(frame, "SPACE record  |  N next  |  P previous  |  D delete this sign  |  Q quit",
             (20 * s, height - 12 * s), 0.55 * s, GREY, 1)
    if message:
        show_message(frame, message, bottom)


def main():
    # Keep the original compact alphabet setting. Word classes are explicit
    # entries so multi-word labels never get split into individual letters.
    alphabet = list(dict.fromkeys(c for c in SIGNS_TO_RECORD.upper() if c.isalnum()))
    words = ["WORD_" + " ".join(str(w).strip().upper().split())
             for w in WORDS_TO_RECORD if str(w).strip()]
    signs = list(dict.fromkeys(alphabet + words))
    if not signs:
        fail("SIGNS_TO_RECORD is empty.")
    os.makedirs(DATA_DIR, exist_ok=True)
    tracker = HandTracker()
    camera = open_camera()
    counts = {sign: count_samples(sign) for sign in signs}

    index, state = 0, "ready"              # ready -> countdown -> recording -> ...
    round_no, round_id, rows = 0, 0, []
    state_start, delete_until = 0.0, 0.0
    message, message_until = "", 0.0
    failed_reads = 0

    def show(text, seconds=2.5):
        nonlocal message, message_until
        message, message_until = text, time.monotonic() + seconds
        print(text)

    print("\nRECORD ISL SIGNS - saving to", DATA_DIR)
    print("Click the camera window, show the sign, press SPACE.")
    print("Keys: SPACE record | N next | P previous | D delete sign | Q quit\n")
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    window_sized = False

    try:
        while True:
            ok, raw = camera.read()
            if not ok or raw is None:
                failed_reads += 1
                if failed_reads > 30:
                    print("The camera stopped sending pictures.")
                    break
                time.sleep(0.01)
                continue
            failed_reads = 0
            display, hands, pose, face, face_points = tracker.detect(raw)
            height, width = raw.shape[:2]
            now = time.monotonic()
            sign = signs[index]

            # ---------- RECORDING STEPS
            if state == "countdown" and now - state_start >= COUNTDOWN_SECONDS:
                state, rows, round_id = "recording", [], int(time.time() * 1000)
            elif state == "recording" and hands and pose is not None and face[0] > 0:
                rows.append([sign, round_id, width, height]
                            + raw_vector(hands).tolist()
                            + pose_raw_vector(pose).tolist()
                            + face.tolist())
                if len(rows) >= SAMPLES_PER_ROUND:
                    save_round(sign, rows)
                    counts[sign] += len(rows)
                    round_no += 1
                    if round_no < ROUNDS:
                        state, state_start = "countdown", now
                    else:
                        state = "ready"
                        if index < len(signs) - 1:
                            index += 1
                            show(f"{sign} saved - next sign: {signs[index]}")
                        else:
                            show("All signs recorded - now run train_model.py", 8)
            if now > message_until:
                message = ""

            # ---------- DISPLAY
            display = fit_display(display)
            for side, points in hands.items():
                draw_hand(display, points, side, flip_x=not MIRROR_MODEL_INPUT)
            draw_pose(display, pose, flip_x=not MIRROR_MODEL_INPUT)
            draw_face(display, face_points, flip_x=not MIRROR_MODEL_INPUT)
            countdown = max(1, math.ceil(COUNTDOWN_SECONDS - (now - state_start)))
            draw_screen(display, signs[index], index + 1, len(signs), counts[signs[index]],
                        state, round_no, len(rows) / SAMPLES_PER_ROUND, countdown,
                        len(hands), pose is not None, face[0] > 0, message)
            cv2.imshow(WINDOW_NAME, display)
            if not window_sized:
                cv2.resizeWindow(WINDOW_NAME, display.shape[1], display.shape[0])
                window_sized = True

            # ---------- KEYS
            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q"), ord("Q")):
                break
            if state != "ready":
                if key == 32:                              # SPACE stops recording
                    state = "ready"
                    show(f"Stopped - finished rounds of {sign} are kept")
            elif key == 32:
                state, state_start, round_no = "countdown", now, 0
            elif key in (ord("n"), ord("N")):
                index = (index + 1) % len(signs)
            elif key in (ord("p"), ord("P")):
                index = (index - 1) % len(signs)
            elif key in (ord("d"), ord("D")):
                if now < delete_until:
                    if os.path.exists(data_file(sign)):
                        os.remove(data_file(sign))
                    counts[sign], delete_until = 0, 0.0
                    show(f"Deleted all samples of {sign}")
                else:
                    delete_until = now + 3
                    show(f"Press D again to delete all samples of {sign}", 3)

            if cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        camera.release()
        tracker.close()
        cv2.destroyAllWindows()
        print("\nSamples saved per sign:")
        print("  " + "   ".join(f"{sign}: {counts[sign]}" for sign in signs))
        print("Next: run train_model.py")


if __name__ == "__main__":
    main()
