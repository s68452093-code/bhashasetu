"""
train_model.py - train the ISL hand, face and upper-body sign model.

Run it after collect_data.py. It first checks how well every sign is
recognised: each recording round is tested by a model that never saw it,
just like a new session in front of the camera. Then it trains on all
recordings and saves isl_alphabet_model_v3.pkl, which checking regional.py loads
automatically. The report is also saved as training_report.txt.
"""

import glob
import os
import time

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import RandomForestClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

from isl_common import (BASE_DIR, DATA_DIR, FACE_RAW_COLUMNS, FEATURE_NAMES_V3,
                        MIRROR_MODEL_INPUT, NEW_MODEL_PATH, POSE_RAW_COLUMNS,
                        RAW_COLUMNS, SWAP_HANDS, fail, features_v3, hands_from_raw)

MIN_SAMPLES = 100       # signs with fewer samples get a warning
GOOD_ACCURACY = 0.85    # signs below this are listed to record again
REPORT_PATH = os.path.join(BASE_DIR, "training_report.txt")


def candidate_models():
    """Model types to compare; the most accurate one is kept.
    final=True builds the saved version, which must also give probabilities."""
    def svm(final):
        svc = SVC(C=10, gamma="scale", class_weight="balanced")
        return make_pipeline(StandardScaler(),
                             CalibratedClassifierCV(svc, ensemble=False) if final else svc)

    return {
        "Random forest": lambda final: RandomForestClassifier(
            n_estimators=300, class_weight="balanced", n_jobs=-1, random_state=0),
        "SVM": svm,
    }


def load_recordings():
    files = sorted(glob.glob(os.path.join(DATA_DIR, "*.csv")))
    if not files:
        fail(f"No recordings found in {DATA_DIR}\nRun collect_data.py first.")
    parts = []
    for path in files:
        try:
            parts.append(pd.read_csv(path))
        except Exception as error:
            print(f"Skipping {os.path.basename(path)}: {error}")
    if not parts:
        fail("None of the recording files could be read.")
    data = pd.concat(parts, ignore_index=True)
    required = (["label", "round", "width", "height"] + RAW_COLUMNS
                + POSE_RAW_COLUMNS + FACE_RAW_COLUMNS)
    missing = [c for c in required
               if c not in data.columns]
    if missing:
        fail("These recordings need hand, face and body landmarks. Run the updated "
             "collect_data.py to create fresh v3 samples (missing columns such as "
             + ", ".join(missing[:3]) + ").")
    data["label"] = data["label"].astype(str).str.strip().str.upper()
    return data


def build_features(data):
    """Version 3 inputs from hand, pose and face tracking for each frame."""
    raw = data[RAW_COLUMNS].to_numpy(np.float32)
    pose_raw = data[POSE_RAW_COLUMNS].to_numpy(np.float32)
    face_raw = data[FACE_RAW_COLUMNS].to_numpy(np.float32)
    sizes = data[["width", "height"]].to_numpy(np.float32)
    rows, keep = [], []
    for values, pose_values, face_values, (width, height) in zip(
            raw, pose_raw, face_raw, sizes):
        hands = hands_from_raw(values)
        pose = (pose_values[1:].reshape(-1, 3)
                if pose_values[0] > 0.5 else None)
        keep_row = bool(hands) and pose is not None and face_values[0] > 0.5
        keep.append(keep_row)
        if keep_row:
            rows.append(features_v3(hands, pose, face_values, width, height))
    data = data[np.array(keep)].reset_index(drop=True)
    return pd.DataFrame(np.array(rows), columns=FEATURE_NAMES_V3), data


def test_by_round(make_model, features, data):
    """Predict every recording round with a model trained without that round."""
    labels = data["label"].to_numpy()
    round_number = (data.groupby("label")["round"].rank(method="dense")
                    .astype(int).to_numpy() - 1)
    testable = data.groupby("label")["round"].transform("nunique").to_numpy() >= 2
    predicted = np.full(len(data), "", dtype=object)
    for k in range(min(int(round_number.max()) + 1, 5)):
        test = testable & (round_number == k)
        if not test.any():
            continue
        model = make_model(False)
        model.fit(features[~test], labels[~test])
        predicted[test] = model.predict(features[test])
    return predicted, testable


def score_signs(labels, predicted, testable):
    """{sign: (share recognised, (most common wrong letter, its share) or None)}"""
    scores = {}
    for sign in sorted(set(labels)):
        mask = testable & (labels == sign)
        if not mask.any():
            continue
        guesses = predicted[mask]
        wrong = pd.Series(guesses[guesses != sign]).value_counts()
        mix_up = (wrong.index[0], wrong.iloc[0] / mask.sum()) if len(wrong) else None
        scores[sign] = (float(np.mean(guesses == sign)), mix_up)
    return scores


def main():
    started = time.time()
    lines = []

    def report(text=""):
        print(text)
        lines.append(text)

    data = load_recordings()
    features, data = build_features(data)
    labels = data["label"].to_numpy()
    signs = sorted(set(labels))
    if len(signs) < 2:
        fail("Record at least two different signs before training.")

    report(f"ISL MODEL TRAINING - {time.strftime('%Y-%m-%d %H:%M')}")
    report(f"Recordings: {len(signs)} signs, {len(data)} samples")
    counts = data.groupby("label").agg(samples=("round", "size"), rounds=("round", "nunique"))
    report("  " + "   ".join(f"{sign} {row.samples} ({row.rounds} rounds)"
                            for sign, row in counts.iterrows()))
    few = [sign for sign, row in counts.iterrows() if row.samples < MIN_SAMPLES]
    single = [sign for sign, row in counts.iterrows() if row.rounds < 2]
    if few:
        report(f"Few samples (under {MIN_SAMPLES}): {' '.join(few)} - record more rounds.")
    if single:
        report(f"Only one round, so they cannot be tested: {' '.join(single)}")

    models = candidate_models()
    results = {}
    if len(single) < len(signs):
        report("\nTesting each recording round with a model that never saw it:")
        for name, make_model in models.items():
            predicted, testable = test_by_round(make_model, features, data)
            scores = score_signs(labels, predicted, testable)
            overall = float(np.mean([right for right, _ in scores.values()]))
            results[name] = (overall, scores)
            report(f"  {name:<14} {overall * 100:5.1f} %")
        best = max(results, key=lambda name: results[name][0])
        overall, scores = results[best]
        report(f"Keeping: {best}")

        report("\nSigns, weakest first:")
        for sign, (right, mix_up) in sorted(scores.items(), key=lambda item: item[1][0]):
            note = f"   mixed up with {mix_up[0]} ({mix_up[1] * 100:.0f} %)" if mix_up else ""
            report(f"  {sign:<3} {right * 100:5.1f} %{note}")
        weak = [sign for sign, (right, _) in scores.items() if right < GOOD_ACCURACY]
        if weak:
            weak_letters = [sign for sign in weak if len(sign) == 1 and sign.isalpha()]
            weak_words = [sign[5:] for sign in weak if sign.startswith("WORD_")]
            report("\nTo improve the weaker classes, record them again in collect_data.py:")
            if weak_letters:
                report(f'  SIGNS_TO_RECORD = "{"".join(weak_letters)}"')
            if weak_words:
                report(f"  WORDS_TO_RECORD = {weak_words!r}")
            report("Keep hands, face and upper body visible, then run train_model.py again.")
        else:
            report("\nAll signs are above "
                   f"{GOOD_ACCURACY * 100:.0f} % - ready for checking regional.py.")
    else:
        best, overall, scores = "Random forest", None, {}
        report("\nNo sign has two rounds yet, so accuracy cannot be tested.")

    model = models[best](True)
    model.fit(features, labels)
    joblib.dump({
        "model": model,
        "feature_columns": FEATURE_NAMES_V3,
        "labels": signs,
        "accuracy": overall,
        "feature_version": 3,
        "mirror": MIRROR_MODEL_INPUT,
        "swap": SWAP_HANDS,
        "model_type": best,
        "sign_accuracy": {sign: right for sign, (right, _) in scores.items()},
        "trained": time.strftime("%Y-%m-%d %H:%M"),
    }, NEW_MODEL_PATH)
    report(f"\nSaved {NEW_MODEL_PATH}  ({time.time() - started:.0f} s)")
    report("Run checking regional.py to use it.")
    with open(REPORT_PATH, "w") as file:
        file.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
