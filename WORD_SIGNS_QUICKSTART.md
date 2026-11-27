# Add whole-word signs to the Scout translator

The Scout v3 recognizer uses MediaPipe hand, face, and upper-body pose tracking
in one classifier for alphabet signs and **held word signs**. Alphabet labels
remain `A` through `Z`; word labels are stored with an
internal `WORD_` prefix so a word such as `I` can remain distinct from the
letter I. The translator hides that prefix and inserts spaces around each
recognized word.

## Record a starter vocabulary

1. Open `collect_data.py`. The new version needs fresh face and body data, so
   keep all letters in `SIGNS_TO_RECORD` and set `WORDS_TO_RECORD`, for example:

   ```python
   WORDS_TO_RECORD = ["HELLO", "HELP", "THANK YOU"]
   ```

   Choose signs your team can demonstrate consistently. This classifier
   recognizes a held pose and includes upper-body position and simple facial
   features. Signs that rely on a movement over time still need a sequence
   model.

2. Run `collect_data.py`. Record every alphabet and word sign again for the
   configured rounds, with hands, face and upper body visible. The new v3 data
   goes into `isl_data_v3`; the older hand-only samples remain in `isl_data`.
3. Run `train_model.py` to train one classifier over the alphabet and word
   labels. It saves `isl_alphabet_model_v3.pkl` beside the project.
4. Run `checking regional.py`. Hold a sign for auto-add, or turn auto-add off
   and press SPACE when the sign is confirmed. Letters append as characters;
   word signs append with spaces. Press ENTER to translate and speak the text.

The current training report measures held-out recording rounds for individual
classes. It does not measure sentence translation quality. The English words
recognized by this prototype also need to exist in the selected translation
service or Bhasha Setu dictionary to receive a useful regional-language result.

## Use the same Scout model in Bhasha Setu 2.0

When Bhasha Setu 2.0 has no `models/sign_model.pt`, its Translate screen can
load `isl_alphabet_model_v3.pkl` from the sibling `SCOUT FILE IMAGES` folder.
Both folders must be kept together. If they are elsewhere, set the
`SCOUT_PROJECT_DIR` environment variable to the Scout Files folder before
starting Bhasha Setu. The app continues to use its shared camera and GUI.
