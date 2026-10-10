# Model evaluation and selection

## Evaluation protocol

The target is end-of-course `Fail` or `Withdrawn` versus `Pass` or `Distinction` for students who remain eligible at the day-56 scoring boundary. Withdrawals already recorded before day 56, and withdrawals with unknown timing, are excluded. The cohort has 26,447 of 32,593 source records after excluding 6,053 early withdrawals and 93 with unknown timing.

The split follows presentation chronology: train on 2013B/2013J, select the model and threshold on 2014B, then evaluate once on 2014J. Repeated `id_student` values are purged from validation if present in train, and from test if present in either earlier fold. This leaves train 11,439 rows/11,334 unique students, validation 5,634/5,381, and test 7,626/7,334. The test is a single later presentation, so it is a limited temporal check rather than external validation.

Each candidate threshold is selected on validation F2. F2 weights recall more than precision because a false negative can miss an opportunity to offer support. False positives can burden coordinators or lead to unwanted contact, so the operating threshold must also reflect human review capacity. Accuracy alone is insufficient. Reports include accuracy, precision, recall, F1, F2, ROC-AUC, and TN/FP/FN/TP. Preprocessing is fitted inside each model pipeline using training data; final candidates are refit on train plus validation before the held-out test evaluation.

## Class balance

After eligibility filtering, 11,062 of 26,447 records (41.8%) have a positive label and 15,385 (58.2%) have a negative label. The train fold has 4,869 positive and 6,570 negative records. No resampling is applied. Class weighting is used for Logistic Regression and Random Forest, and `scale_pos_weight` for XGBoost; no validation/test rows are resampled.

## Held-out supervised results

The operating thresholds below were selected on the 2014B validation presentation. Results are from the student-disjoint 2014J test presentation.

| Model | Threshold | Accuracy | Precision | Recall | F1 | F2 | ROC-AUC | TN / FP / FN / TP |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Logistic Regression | 0.0587 | 0.364 | 0.360 | **0.999** | 0.529 | 0.737 | 0.764 | 52 / 4,848 / 4 / 2,722 |
| Random Forest | 0.2385 | 0.554 | 0.441 | 0.923 | 0.597 | 0.757 | **0.778** | 1,713 / 3,187 / 211 / 2,515 |
| XGBoost | 0.1898 | 0.517 | 0.422 | 0.948 | 0.584 | **0.758** | 0.770 | 1,359 / 3,541 / 143 / 2,583 |

XGBoost was selected because it had the highest validation F2 (0.813; Random Forest 0.809). The validation difference is small. On test it also has the highest F2 (narrowly over Random Forest); Logistic Regression has the highest recall only by flagging almost every record, and Random Forest has the highest accuracy, precision, F1, and ROC-AUC. This does not establish a universally best model. At the selected XGBoost threshold, 3,541 negative cases are flagged for 143 missed positive cases; that volume may exceed coordinator capacity. Scores are not calibrated probabilities, and no flag must not be interpreted as evidence that a student does not need help.

These figures are the feature-contract `oulad-early-risk-v2` results recorded at training time and reproduced from the saved artifacts by `tests/test_canonical_integrity.py`. Full precision metrics, validation results, cohort/split counts, and confusion matrices are in `data/processed/supervised_evaluation.json`. The registry records the validation-selected model and saved artifact versions. The threshold is a research operating point, not an intervention policy.

## Numeric final-exam score model

The raw OULAD `studentAssessment.csv` has numeric assessment scores. A defined end-of-course target is available only for the `Exam` assessment in modules CCC and DDD: 4,959 submitted exam scores from 4,633 unique students. The target is the observed final exam score on a 0-100 scale, predicted from the same features available through course-relative day 55. This is not an overall course grade. Students who did not submit an exam have no numeric label and are outside this model's target population.

The regressor uses the early-risk feature contract with a `RandomForestRegressor` (120 trees, minimum leaf size 5). It trains on 2013B/2013J, validates on student-disjoint 2014B, and reports held-out metrics on student-disjoint 2014J. The deployed artifact is refit on train plus validation only after the held-out evaluation. Held-out MAE is 14.744 points, RMSE 17.815, and R² 0.306; the training-mean baseline is MAE 18.270, RMSE 21.752, and R² -0.034. Validation MAE is 16.432, RMSE 19.697, and R² 0.111. These results show signal in one historical cohort, not reliable individual grading or external validity. Only CCC and DDD are supported by this source release. Full counts and metrics are in `data/processed/grade_score_evaluation.json`.

The separate `/api/predictions/{student_id}/grade-score` endpoint persists numeric score predictions to `grade_predictions`; these records are distinct from the binary support-priority score. The endpoint uses the existing day-56 assembled feature inputs and rejects unsupported modules. Run Alembic migration `a58f9d632e10` before enabling the endpoint in an existing database.

## Email notifications

Optional SMTP notifications are dispatched after a student support intervention is created or its status changes, and after a study plan is saved. SMTP is disabled unless `SMTP_HOST` and `SMTP_FROM_EMAIL` are configured. Credentials are read only from environment settings. SMTP errors are logged without recipient/message details and do not undo the saved intervention or study plan. Automated tests use a mocked SMTP client; no real email delivery has been verified.

## Other model families

K-Means selected k=2 from candidates 2–6 using training-only silhouette (0.488). One cluster's median profile has 420 clicks across 23 active days and 8 weeks; the other has 31 clicks, 3 active days, and 2 weeks, with no recorded early assessment. These are observed cohort medians, not judgments about a student. The preprocessing and centers are fit on training rows only. Candidate scores and profiles are in `data/processed/clustering_evaluation.json`; details are in [clustering.md](clustering.md).

The LSTM consumes eight chronological weekly pairs of VLE clicks and active days from days 0–55, with a scaler fitted only on the training fold. On the same test, it reached ROC-AUC 0.721 and F2 0.743 (threshold 0.1937; 50 false negatives and 4,428 false positives). Logistic regression on the same flattened sequence reached ROC-AUC 0.716 and F2 0.739 (threshold 0.1413; 9 false negatives and 4,771 false positives). This small difference does not outweigh the tabular XGBoost's higher ROC-AUC (0.770) and F2 (0.758); the LSTM is not selected as the primary model. See `data/processed/lstm_evaluation.json` and [lstm-pipeline.md](lstm-pipeline.md) for the full metrics and limitations.

## Interpretation and limitations

The positive class represents an observed course outcome, not a prediction of intent, a diagnosis, or a claim that any individual will fail or leave. False negatives and false positives have different costs that require input from students and educators. Before operational use, evaluate probability calibration, error rates across relevant subgroups, repeat-cohort stability, staffing capacity, and the effect of interventions. OULAD is historical and observational; predictive associations do not show causes or prove that an intervention will help.
