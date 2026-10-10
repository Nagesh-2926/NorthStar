# ML pipeline

## Scope and reproducibility

`python -m ml.supervised.train` runs the complete Phase 2 pipeline. Random seeds are fixed at 42 for model algorithms; scikit-learn preprocessing and threshold selection are trained on training/validation groups as documented. `studentVle.csv` is streamed in 500,000-row chunks; the other OULAD tables are small enough to load directly. Inputs are raw CSVs and remain read-only. Processed student features and sequences are generated under `data/processed/`.

## Label, window, and split

The target is end-of-course `Fail` or `Withdrawn` on/after day 56 versus `Pass` or `Distinction`, from `studentInfo.final_result`. Withdrawals before day 56 (6,053 rows in this snapshot) and withdrawals with unknown unregistration timing (93 rows) are excluded because those outcomes are not reliably future at scoring time. `date_unregistration` is only used for this cohort-eligibility filter and never enters model inputs. Features are censored at the start of relative course day 56: assessment schedule/submission and VLE activity are restricted to days 0–55. This gives an eight-week early support signal for a later outcome. The label is not a dropout diagnosis.

Use a temporal split: train on 2013B/2013J, choose model and threshold on 2014B, and report final test on 2014J. To prevent the same learner appearing in both training and later folds, purge training IDs from validation; purge training and retained validation IDs from test. The raw dataset contains repeat students across presentations, so this removes their later rows. This is a small historical cohort check, not broad external validation.

## Processing and features

The tabular feature contract is `oulad-early-risk-v2` in `docs/feature-contract.md`. The unchanged weekly model uses the independent `oulad-weekly-sequence-v1` contract. Student course records join to registration by module/presentation/student; assessment submissions join to assessment metadata and courses; activity maps from studentVle to vle site metadata. Cardinality is checked for key joins. Sensitive demographics and direct identifiers are excluded. `date_unregistration` is never a feature; future scores, future submissions, and future activity are excluded. No attendance measure is fabricated.

For supervised learning, missing numerical data is median-imputed with missing indicators, categoricals use most-frequent imputation and one-hot encoding. These fitted transformations stay in each serialized sklearn Pipeline, ensuring inference applies the training feature order and transformations.

## Algorithms and model selection

Logistic Regression, Random Forest, and XGBoost are all fitted on the training period. No oversampling is used; training-fold class weights account for prevalence. Each model's threshold is selected only against validation F2 to give false negatives greater weight. The final estimator is refit on training plus validation and evaluated once on the later 2014J test. Selection uses validation F2, then recall, then ROC-AUC as tie breakers. Metrics are retained at the selected validation threshold. Per-fold sample sizes and repeated-student rows excluded are saved in the evaluation report.

The final audit found student-ID overlap in the previous temporal folds and target outcomes recorded before the day-56 prediction boundary. The training builder now excludes already-withdrawn/unknown-time withdrawal outcomes and purges repeat IDs between temporal partitions. Supervised, clustering, and LSTM reports/artifacts are regenerated under this policy; the prior metrics must not be used.

Artifacts and registry: `ml/saved_models/`; evaluation results: `data/processed/`. No API request performs training. `ml/inference/prediction_service.py` only loads serialized models and scores validated input features.

## Limitations

This label is an end-of-course result, not necessarily the institution's live intervention definition. OULAD is historical and observational, with no attendance, student intent, or causal effects. Score and activity associations are not explanations of why a student may need support. Thresholds need calibration and governance for a deployment population. The phase 2 holdout has only one later presentation.
