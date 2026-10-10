# Weekly engagement LSTM

The sequence input is based on actual OULAD `studentVle` events, not synthetic tabular rows. For each student-module-presentation, eight ordered vectors cover presentation-relative weeks 0–7 (days 0–55), with two observed signals: sum of VLE `sum_click`, and number of unique active dates in the week. Students with no recorded event have genuine all-zero activity sequences. There is no OULAD attendance signal.

Target: end-of-course `Fail` or `Withdrawn` on/after day 56 as in the supervised pipeline; already-withdrawn and unknown-timing withdrawal outcomes are excluded. Chronological groups are train 2013B/2013J, validation 2014B, test 2014J, with repeated student IDs purged from later partitions. Input scaling is fitted using training sequences only. Validation controls early stopping and threshold selection; test is held out. A logistic regression on the same flattened weekly signals is the practical baseline. Reports include the same classification metrics/confusion counts and cohort split diagnostics.

The saved Keras file is `ml/saved_models/lstm_weekly.keras`; the sequence scaler and feature order are in `lstm_preprocessing.joblib`. The sequence length is fixed at eight weeks and inference must provide those exact two channels. Model/baseline outcomes appear in `data/processed/lstm_evaluation.json`.

Eight weeks of clicks are a narrow behavioral view; activity does not establish attention or learning. The LSTM may underperform the tabular models or baseline, and the single later presentation test has substantial uncertainty. No claim of superiority is made. Temporal performance and subgroup stability require further cohorts and review.
