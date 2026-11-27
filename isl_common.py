"""
isl_common.py - shared code for the ISL Bridge scripts
    collect_data.py   record your signs
    train_model.py    train the model from the recordings
    translate3.py     live translator

Keep all four files together in C:\\ISL_Bridge. Recording and translating
find hands and build the model's inputs through this one file, so they
always match.
"""

import os
import sys
import time
import urllib.request
from collections import deque

import cv2
import numpy as np

# =====================================================================
# PATHS
# =====================================================================

# Keep recordings, checkpoints and reports beside this project. This lets the
# project run from any drive instead of silently writing to C:\\ISL_Bridge.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LEGACY_DATA_DIR = os.path.join(BASE_DIR, "isl_data")
DATA_DIR = os.path.join(BASE_DIR, "isl_data_v3")     # face + body + hand recordings
NEW_MODEL_PATH = os.path.join(BASE_DIR, "isl_alphabet_model_v3.pkl")
V2_MODEL_PATH = os.path.join(BASE_DIR, "isl_alphabet_model_v2.pkl")
OLD_MODEL_PATH = os.path.join(BASE_DIR, "isl_alphabet_model.pkl")
_ASSET_DIR = os.path.join(os.path.dirname(BASE_DIR), "ISL_ Translator")


def _asset_path(filename):
    candidates = [os.path.join(BASE_DIR, "models", filename),
                  os.path.join(_ASSET_DIR, filename)]
    return next((p for p in candidates if os.path.isfile(p)), candidates[0])


HAND_MODEL_PATH = _asset_path("hand_landmarker.task")
FACE_MODEL_PATH = _asset_path("face_landmarker.task")
POSE_MODEL_PATH = _asset_path("pose_landmarker_lite.task")
HAND_MODEL_URLS = [
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/1/hand_landmarker.task",
]
FACE_MODEL_URLS = [
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task",
]
POSE_MODEL_URLS = [
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_lite/float16/1/pose_landmarker_lite.task",
]

# =====================================================================
# CAMERA AND HAND DETECTION (the same for recording and translating)
# =====================================================================

CAMERA_INDEX = 0              # use 1 if the wrong camera opens
FRAME_WIDTH = 1280
FRAME_HEIGHT = 720
MIN_HAND_CONFIDENCE = 0.4     # MediaPipe's default is 0.5; a little lower keeps a
                              # partly covered hand (M, N, R) from disappearing
MIRROR_MODEL_INPUT = True     # MediaPipe sees the mirrored (selfie) picture
SWAP_HANDS = False

# =====================================================================
# MODEL INPUTS
# =====================================================================

# Version 1 (translate2.py and your first model): raw screen positions.
# uses_two_hands, left_hand_x_0, left_hand_y_0, left_hand_z_0 ... right_hand_z_20
RAW_COLUMNS = ["uses_two_hands"] + [
    f"{side}_hand_{axis}_{i}"
    for side in ("left", "right")
    for i in range(21)
    for axis in ("x", "y", "z")
]

# Version 2: hand shapes and the position of one hand against the other.
FEATURE_NAMES_V2 = (
    ["two_hands"]
    + [f"main_{axis}_{i}" for i in range(1, 21) for axis in ("x", "y", "z")]
    + [f"other_{axis}_{i}" for i in range(21) for axis in ("x", "y", "z")]
)

# MediaPipe Pose landmarks: nose, eyes, ears, shoulders, elbows, wrists.
POSE_SUBSET = [0, 2, 5, 7, 8, 11, 12, 13, 14, 15, 16]
POSE_RAW_COLUMNS = ["pose_present"] + [
    f"pose_{axis}_{i}" for i in range(len(POSE_SUBSET)) for axis in ("x", "y", "z")
]
FACE_RAW_COLUMNS = ["face_present", "brow_height", "head_tilt", "mouth_open"]
FEATURE_NAMES_V3 = (
    FEATURE_NAMES_V2
    + ["body_present"]
    + [f"body_{axis}_{i}" for i in range(len(POSE_SUBSET)) for axis in ("x", "y", "z")]
    + ["face_present", "brow_height", "head_tilt", "mouth_open"]
)


def raw_vector(hands):
    """Version 1 inputs, in RAW_COLUMNS order. A missing hand is all zeros.
    Recordings are saved in this form, so new input versions can be made
    from old recordings."""
    vector = np.zeros(len(RAW_COLUMNS), dtype=np.float32)
    left, right = hands.get("Left"), hands.get("Right")
    vector[0] = 1.0 if (left is not None and right is not None) else 0.0
    if left is not None:
        vector[1:64] = left.reshape(-1)
    if right is not None:
        vector[64:127] = right.reshape(-1)
    return vector


def hands_from_raw(values):
    """The opposite of raw_vector(): saved values back into hands."""
    values = np.asarray(values, dtype=np.float32)
    hands = {}
    left, right = values[1:64].reshape(21, 3), values[64:127].reshape(21, 3)
    if np.any(left):
        hands["Left"] = left
    if np.any(right):
        hands["Right"] = right
    return hands


def hand_size(points):
    """Average distance from the wrist to the four knuckles."""
    return float(np.linalg.norm(points[[5, 9, 13, 17]] - points[0], axis=1).mean())


def features_v2(hands, width, height):
    """Version 2 inputs, in FEATURE_NAMES_V2 order.

    Main hand = the right hand, or the only hand when just one is visible.
    Every point of both hands is measured from the main hand's wrist and
    divided by the main hand's size, so moving closer, further or sideways,
    or a camera with another resolution, gives the same numbers. The other
    hand's points also say where it is compared with the main hand - which
    is what tells M, N and R apart (which fingers lie on the other palm)."""
    if len(hands) == 1:
        main, other = next(iter(hands.values())), None
    else:
        main, other = hands["Right"], hands["Left"]
    to_pixels = np.array([width, height, width], dtype=np.float32)
    main = main * to_pixels
    origin = main[0]
    size = hand_size(main) or 1.0
    values = np.zeros(len(FEATURE_NAMES_V2), dtype=np.float32)
    values[1:61] = ((main[1:] - origin) / size).reshape(-1)
    if other is not None:
        values[0] = 1.0
        values[61:124] = ((other * to_pixels - origin) / size).reshape(-1)
    return values


def pose_raw_vector(pose):
    values = np.zeros(1 + len(POSE_SUBSET) * 3, dtype=np.float32)
    if pose is not None:
        values[0] = 1.0
        values[1:] = np.asarray(pose, dtype=np.float32).reshape(-1)
    return values


def features_v3(hands, pose, face, width, height):
    """Hand-shape + normalized upper-body pose + face-expression features."""
    values = np.zeros(len(FEATURE_NAMES_V3), dtype=np.float32)
    values[:len(FEATURE_NAMES_V2)] = features_v2(hands, width, height)
    body_start = len(FEATURE_NAMES_V2)
    if pose is not None:
        points = np.asarray(pose, dtype=np.float32) * np.array(
            [width, height, width], dtype=np.float32)
        origin = (points[5] + points[6]) / 2.0
        scale = float(np.linalg.norm(points[5] - points[6])) or 1.0
        values[body_start] = 1.0
        values[body_start + 1:body_start + 1 + len(POSE_SUBSET) * 3] = (
            (points - origin) / scale).reshape(-1)
    face_start = body_start + 1 + len(POSE_SUBSET) * 3
    face = np.asarray(face if face is not None else np.zeros(4), dtype=np.float32)
    if face.size == 4:
        values[face_start:] = face
    return values


# =====================================================================
# HANDS
# =====================================================================

class HandSorter:
    """Decides which detected hand is "Left" and which is "Right".

    When the hands touch - common in two-handed ISL letters - MediaPipe can
    call both hands the same side. The two hands are then split by position,
    the way MediaPipe placed them on recent frames where it told them apart."""

    def __init__(self):
        self.right_hand_on_right = deque(maxlen=60)

    def sort(self, result, swap=False):
        found = []
        for landmarks, handedness in zip(result.hand_landmarks, result.handedness):
            name = (handedness[0].category_name or handedness[0].display_name
                    or "") if handedness else ""
            side = "Left" if name.lower().startswith("l") else "Right"
            points = np.array([[p.x, p.y, p.z] for p in landmarks], dtype=np.float32)
            found.append([side, points])

        if len(found) == 2:
            (side_a, points_a), (side_b, points_b) = found
            a_is_further_right = points_a[:, 0].mean() > points_b[:, 0].mean()
            if side_a != side_b:
                self.right_hand_on_right.append((side_a == "Right") == a_is_further_right)
            else:
                votes = self.right_hand_on_right
                right_on_right = sum(votes) * 2 >= len(votes)
                found[0][0] = "Right" if a_is_further_right == right_on_right else "Left"
                found[1][0] = "Left" if found[0][0] == "Right" else "Right"

        hands = {}
        for side, points in found:
            if swap:
                side = "Left" if side == "Right" else "Right"
            hands[side] = points
        return hands


class HandTracker:
    """Tracks hands, face and upper-body pose with MediaPipe Tasks."""

    def __init__(self):
        try:
            import mediapipe as mp
            # Import Tasks symbols from their concrete modules. Some newer
            # MediaPipe builds expose mp.tasks members as lazy-import proxies;
            # calling those proxies can raise "lazy_import object is not
            # callable" during detector startup.
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision

            options = vision.HandLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=HAND_MODEL_PATH),
                running_mode=vision.RunningMode.VIDEO,
                num_hands=2,
                min_hand_detection_confidence=MIN_HAND_CONFIDENCE,
                min_hand_presence_confidence=MIN_HAND_CONFIDENCE,
                min_tracking_confidence=MIN_HAND_CONFIDENCE,
            )
            face_options = vision.FaceLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=FACE_MODEL_PATH),
                running_mode=vision.RunningMode.VIDEO,
                num_faces=1,
                output_face_blendshapes=False,
                output_facial_transformation_matrixes=False,
            )
            pose_options = vision.PoseLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=POSE_MODEL_PATH),
                running_mode=vision.RunningMode.VIDEO,
                num_poses=1,
                output_segmentation_masks=False,
            )
        except (ImportError, AttributeError) as error:
            fail(f"MediaPipe is missing or too old ({error}).\n"
                 "Fix it in Command Prompt:  py -m pip install --upgrade mediapipe")
        ensure_landmarker_models()
        try:
            self.landmarker = vision.HandLandmarker.create_from_options(options)
            self.face_landmarker = vision.FaceLandmarker.create_from_options(face_options)
            self.pose_landmarker = vision.PoseLandmarker.create_from_options(pose_options)
        except Exception as error:
            self.close()
            fail(f"MediaPipe could not load the hand/face/body models: {error}")
        self.mp = mp
        self.sorter = HandSorter()
        self.timestamp_ms = 0

    def detect(self, raw, mirror=MIRROR_MODEL_INPUT, swap=SWAP_HANDS):
        """Return display frame, hands, upper-body landmarks and face features."""
        display = cv2.flip(raw, 1)
        view = display if mirror else raw
        rgb = cv2.cvtColor(view, cv2.COLOR_BGR2RGB)
        image = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb)
        self.timestamp_ms = max(self.timestamp_ms + 1, int(time.monotonic() * 1000))
        hands_result = self.landmarker.detect_for_video(image, self.timestamp_ms)
        face_result = self.face_landmarker.detect_for_video(image, self.timestamp_ms)
        pose_result = self.pose_landmarker.detect_for_video(image, self.timestamp_ms)
        hands = self.sorter.sort(hands_result, swap)

        pose = None
        if pose_result.pose_landmarks:
            landmarks = pose_result.pose_landmarks[0]
            pose = np.array([[landmarks[i].x, landmarks[i].y, landmarks[i].z]
                             for i in POSE_SUBSET], dtype=np.float32)

        face = np.zeros(4, dtype=np.float32)
        face_points = None
        if face_result.face_landmarks:
            landmarks = face_result.face_landmarks[0]
            face_points = np.array([[p.x, p.y, p.z] for p in landmarks],
                                   dtype=np.float32)
            try:
                left_brow_y = np.mean([landmarks[i].y for i in (33, 105, 66, 107)])
                right_brow_y = np.mean([landmarks[i].y for i in (336, 296, 334, 293)])
                left_eye_y = np.mean([landmarks[i].y for i in (159, 145)])
                right_eye_y = np.mean([landmarks[i].y for i in (386, 374)])
                brow = ((left_eye_y - left_brow_y) + (right_eye_y - right_brow_y)) / 2
                brow_height = float(np.clip((brow - 0.012) * 25.0, -1.0, 1.0))
                left_eye, right_eye = landmarks[33], landmarks[263]
                angle = np.arctan2(right_eye.y - left_eye.y,
                                   right_eye.x - left_eye.x)
                head_tilt = float(np.clip(angle / (np.pi / 4), -1.0, 1.0))
                upper = np.mean([landmarks[i].y for i in (13, 14)])
                lower = np.mean([landmarks[i].y for i in (16, 17)])
                mouth_open = float(np.clip((lower - upper - 0.02) * 20.0, 0.0, 1.0))
                face[:] = (1.0, brow_height, head_tilt, mouth_open)
            except (IndexError, AttributeError, TypeError):
                pass
        return display, hands, pose, face, face_points

    def close(self):
        for name in ("landmarker", "face_landmarker", "pose_landmarker"):
            task = getattr(self, name, None)
            if task is not None:
                try:
                    task.close()
                except Exception:
                    pass


# =====================================================================
# FILES AND CAMERA
# =====================================================================

def fail(message):
    """Stop with a short, readable message instead of a long traceback."""
    print("\nERROR: " + message + "\n", file=sys.stderr)
    sys.exit(1)


def ensure_landmarker_models():
    """Make sure all three MediaPipe Tasks models are available."""
    assets = ((HAND_MODEL_PATH, HAND_MODEL_URLS),
              (FACE_MODEL_PATH, FACE_MODEL_URLS),
              (POSE_MODEL_PATH, POSE_MODEL_URLS))
    for path, urls in assets:
        if os.path.isfile(path):
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        part_file = path + ".part"
        print(os.path.basename(path), "not found - downloading it once...")
        for url in urls:
            try:
                urllib.request.urlretrieve(url, part_file)
                os.replace(part_file, path)
                print("Saved", path)
                break
            except Exception as error:
                print("  could not download from", url, "-", error)
        if not os.path.isfile(path):
            fail(f"Download the MediaPipe model from\n  {urls[0]}\nand save it as\n  {path}")


def open_camera(index=CAMERA_INDEX):
    """Open the webcam, trying other drivers and camera numbers if needed."""
    if sys.platform == "win32":
        drivers = [cv2.CAP_DSHOW, cv2.CAP_MSMF]   # DirectShow opens much faster
    else:
        drivers = [cv2.CAP_ANY]
    for number in [index] + [n for n in (0, 1, 2) if n != index]:
        for driver in drivers:
            camera = cv2.VideoCapture(number, driver)
            if camera.isOpened():
                # MJPG keeps a full frame rate at 1280x720 on most webcams
                camera.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
                camera.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
                camera.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
                for _ in range(10):                # the first frames can be empty
                    ok, frame = camera.read()
                    if ok and frame is not None:
                        height, width = frame.shape[:2]
                        print(f"Camera {number} opened at {width}x{height}")
                        return camera
                    time.sleep(0.05)
            camera.release()
    fail("Could not open the webcam.\nClose other apps that use it (Camera, Zoom, "
         "Teams, a browser tab) and check CAMERA_INDEX in isl_common.py.")


# =====================================================================
# DRAWING
# =====================================================================

HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),            # thumb
    (0, 5), (5, 6), (6, 7), (7, 8),            # index finger
    (5, 9), (9, 10), (10, 11), (11, 12),       # middle finger
    (9, 13), (13, 14), (14, 15), (15, 16),     # ring finger
    (13, 17), (17, 18), (18, 19), (19, 20),    # little finger
    (0, 17),                                   # edge of the palm
]
POSE_CONNECTIONS = [
    (0, 1), (0, 2), (1, 3), (2, 4), (0, 5), (0, 6), (5, 6),
    (5, 7), (7, 9), (6, 8), (8, 10),
]
FACE_CONNECTIONS = [
    (33, 105), (105, 66), (66, 107), (336, 296), (296, 334), (334, 293),
    (159, 145), (386, 374), (33, 263), (1, 4), (4, 5),
    (13, 14), (14, 17), (17, 16), (16, 13), (61, 13), (13, 291),
]

FONT = cv2.FONT_HERSHEY_SIMPLEX
WHITE = (255, 255, 255)
GREY = (175, 175, 175)
YELLOW = (0, 230, 255)
GREEN = (80, 220, 80)
DIM_GREEN = (60, 140, 60)
RED = (60, 60, 255)
LIGHT_BLUE = (255, 210, 120)
LEFT_COLOR = (255, 150, 40)      # blue (OpenCV colours are Blue, Green, Red)
RIGHT_COLOR = (40, 150, 255)     # orange
BODY_COLOR = (80, 230, 120)
FACE_COLOR = (230, 130, 255)


def fit_display(frame):
    """Enlarge small camera pictures so the on-screen text stays readable."""
    if frame.shape[1] < 1280:
        zoom = 1280 / frame.shape[1]
        frame = cv2.resize(frame, None, fx=zoom, fy=zoom)
    return frame


def put_text(frame, text, origin, scale, color, thickness=2, max_width=None):
    """Draw text, shrinking it if it would be wider than max_width."""
    if max_width:
        width = cv2.getTextSize(text, FONT, scale, thickness)[0][0]
        if width > max_width:
            scale *= max_width / width
    origin = (int(origin[0]), int(origin[1]))
    cv2.putText(frame, text, origin, FONT, scale, color, thickness, cv2.LINE_AA)


def darken(frame, x0, y0, x1, y1, amount=0.6):
    """See-through dark panel behind text."""
    height, width = frame.shape[:2]
    x0, x1 = max(0, int(x0)), min(width, int(x1))
    y0, y1 = max(0, int(y0)), min(height, int(y1))
    area = frame[y0:y1, x0:x1]
    area[:] = (area * (1 - amount)).astype(np.uint8)


def draw_hand(frame, points, side, flip_x):
    """Hand skeleton, coloured by the side it is given to the model as."""
    height, width = frame.shape[:2]
    xs = 1.0 - points[:, 0] if flip_x else points[:, 0]
    pixels = np.column_stack([xs * width, points[:, 1] * height]).astype(int).tolist()
    color = LEFT_COLOR if side == "Left" else RIGHT_COLOR
    for a, b in HAND_CONNECTIONS:
        cv2.line(frame, tuple(pixels[a]), tuple(pixels[b]), color, 3, cv2.LINE_AA)
    for x, y in pixels:
        cv2.circle(frame, (x, y), 4, WHITE, -1, cv2.LINE_AA)
    (text_w, text_h), _ = cv2.getTextSize(side, FONT, 0.8, 2)
    x, y = pixels[0][0] - text_w // 2, pixels[0][1] + 40
    darken(frame, x - 6, y - text_h - 8, x + text_w + 6, y + 8, 0.6)
    put_text(frame, side, (x, y), 0.8, color)


def draw_pose(frame, pose, flip_x=False):
    """Draw tracked nose, shoulders, elbows and wrists as a green skeleton."""
    if pose is None:
        return
    height, width = frame.shape[:2]
    points = np.asarray(pose, dtype=np.float32)
    xs = 1.0 - points[:, 0] if flip_x else points[:, 0]
    pixels = np.column_stack([xs * width, points[:, 1] * height]).astype(int)
    for a, b in POSE_CONNECTIONS:
        cv2.line(frame, tuple(pixels[a]), tuple(pixels[b]), BODY_COLOR, 2, cv2.LINE_AA)
    for x, y in pixels:
        cv2.circle(frame, (x, y), 5, BODY_COLOR, -1, cv2.LINE_AA)


def draw_face(frame, face_points, flip_x=False):
    """Draw face-mesh dots plus eyebrow, eye and mouth guide lines."""
    if face_points is None:
        return
    height, width = frame.shape[:2]
    points = np.asarray(face_points, dtype=np.float32)
    xs = 1.0 - points[:, 0] if flip_x else points[:, 0]
    pixels = np.column_stack([xs * width, points[:, 1] * height]).astype(int)
    radius = max(1, round(width / 900))
    for x, y in pixels:
        if 0 <= x < width and 0 <= y < height:
            cv2.circle(frame, (x, y), radius, FACE_COLOR, -1, cv2.LINE_AA)
    for a, b in FACE_CONNECTIONS:
        if a < len(pixels) and b < len(pixels):
            cv2.line(frame, tuple(pixels[a]), tuple(pixels[b]),
                     FACE_COLOR, max(1, radius), cv2.LINE_AA)


def show_message(frame, message, bottom_panel_height):
    """Short notice above the bottom panel, e.g. "Added A"."""
    height, width = frame.shape[:2]
    s = width / 1280.0
    scale = 1.1 * s
    (text_w, text_h), _ = cv2.getTextSize(message, FONT, scale, 3)
    if text_w > width - 60:
        scale *= (width - 60) / text_w
        (text_w, text_h), _ = cv2.getTextSize(message, FONT, scale, 3)
    x = (width - text_w) // 2
    y = height - bottom_panel_height - 30 * s
    darken(frame, x - 15 * s, y - text_h - 15 * s, x + text_w + 15 * s, y + 15 * s, 0.7)
    put_text(frame, message, (x, y), scale, YELLOW, 3)
