# NorthStar Audit (Follow-up): Saved XGBoost Artifact on Validation

| | |
|---|---|
| Audit ID | `calibration_audit_20261010T014038Z_saved_artifact_validation` |
| Builds on | `reports/calibration_audit_20261010T012653Z/REPORT.md`, the first audit, cited below as "A1" |
| Mode | Read-only. Test labels are **not** read by this follow-up's script. No training entry point was run. |
| Environment | Project `.venv`, Python 3.13.15, scikit-learn 1.7.2, xgboost 3.1.1 |

Tags: **[Observed]** means taken from source or artifacts. **[Calculated]** means produced by `audit_saved_artifact_validation.py` (see `results.json`). **[Recommendation]** means not applied.

---

## 1. Findings

| # | Finding | Basis |
|---|---|---|
| 1 | **The saved `xgboost.joblib` was trained on the validation partition (2014B).** Its validation scores are in-sample. They are not unbiased validation evidence for calibration, ranking, or threshold choice. | [Calculated] The fitted one-hot encoder's `code_presentation` categories are `["2013B","2013J","2014B"]`. The fitted median imputer equals the train+validation medians and does not equal the train-only medians. [Observed] `ml/supervised/train.py:106-107`: `final.fit(X_all, y_all)`, where `X_all = concat(train, valid)`. |
| 2 | **The in-sample numbers look optimistic.** Against the out-of-sample train-only model on the same 5,634 rows: AUC 0.848 vs 0.801, Brier 0.158 vs 0.179, log loss 0.478 vs 0.532, and F2 at 0.1898 is 0.826 vs 0.813. The bootstrap 95% CIs do not overlap for AUC, Brier, or log loss. | §3 |
| 3 | **In-sample calibration is not evidence either way.** The in-sample curve sits closer to the diagonal above 0.8, an artefact of training on these rows. It over-predicts by 4–9 percentage points below 0.6, so ECE is *higher* than out-of-sample (0.051 vs 0.038). | §3.2 |
| 4 | **In-sample scores would point to a different threshold.** In-sample F2 at 0.25 is 0.827, slightly above the 0.826 at 0.1898. Choosing a threshold from these scores would be a leakage-driven choice. | §4 |
| 5 | **The stored threshold has never been evaluated out-of-sample on the deployed model's development data.** It came from the train-only model (A1 §2.2). The only out-of-sample labels left for the deployed model are test, which must not be used for selection. | §5 |
| 6 | **The tests do not guard threshold provenance or calibration.** The existing tests check that classes are `[0,1]` (`tests/test_canonical_integrity.py:136`), that scores lie in `[0,1]` (`tests/test_inference.py:48,59`, `backend/tests/test_ml_endpoints.py:165`), and that recorded metrics reproduce. None checks that the stored threshold was validated on the stored pipeline, or that score semantics are recorded. | [Observed] |

**What this does not show.** This audit does not show that the model is calibrated, and it does not justify any new threshold. No threshold change is recommended from these measurements.

---

## 2. Training-to-inference path [Observed]

| Stage | Location | Note |
|---|---|---|
| Split | `ml/features/build_dataset.py:197-229` | train 2013B/2013J (11,439 rows) · validation 2014B (5,634) · test 2014J (7,626); students purged across partitions |
| Stage-1 fit and threshold selection | `ml/supervised/train.py:92-98`, `select_threshold` `:63-67` | Fit on train only. Threshold = argmax of validation F2 → 0.18982425332069397 |
| Model selection | `train.py:100-101` | validation F2, then recall, then AUC |
| **Refit and save** | `train.py:104-113` | Fit on **train + validation**; the stage-1 threshold is stored unchanged in the artifact |
| Inference | `ml/inference/prediction_service.py:85-93` `predict` | `support_priority_score = predict_proba[:,1]`; `review_for_support` if score ≥ `artifact["threshold"]`; no calibration step |
| Serving | `backend/app/ml/model_manager.py:29-49` | loads the registry entry with `selected=True` |
| Tests reviewed | `tests/test_inference.py`, `tests/test_canonical_integrity.py`, `backend/tests/test_ml_endpoints.py` | see Finding 6 |

---

## 3. Calibration on validation 2014B (n = 5,634, positives 2,510, prevalence 0.4455)

> **Disclosure.** Validation 2014B was already used to select the model and the threshold, and it is part of the saved model's training data. Column A below is **in-sample**. Column B comes from the train-only stage-1 model: it was rebuilt in memory, verified to reproduce the recorded validation confusion matrix 737/2387/97/2413 and AUC 0.800834 exactly, and never saved. Column B is out-of-sample for model fitting but **not** independent of the selection decisions, so it carries mild selection bias (≈0.002 F2 optimism per A1 §5.4).

### 3.1 Summary metrics (95% CI from 1,000 bootstrap resamples)

| Metric | A: saved artifact (IN-SAMPLE) | B: stage-1 (out-of-sample) | Prevalence-only baseline |
|---|---|---|---|
| Mean score | 0.494 | 0.483 | 0.4455 |
| Brier | 0.1582 (0.1535–0.1629) | 0.1786 (0.1733–0.1838) | 0.2470 |
| Log loss | 0.4784 (0.4669–0.4899) | 0.5321 (0.5187–0.5452) | 0.6872 |
| ROC-AUC | 0.8483 (0.8381–0.8583) | 0.8008 (0.7895–0.8123) | 0.5 |
| ECE, 10 equal-width bins | 0.051 | 0.038 | — |

Definitions:
- **Brier** = mean (p − y)².
- **Log loss** = −mean[y log p + (1 − y) log(1 − p)], with p clipped to [1e-15, 1 − 1e-15].
- **ECE** = Σ (n_bin/N)·|mean p − observed rate|. It depends on the binning and is reported as a descriptive summary only.

### 3.2 Reliability table: saved artifact, IN-SAMPLE

Source: `reliability_validation_saved_artifact_IN_SAMPLE.csv`. The diagram `reliability_validation.svg` overlays A and B.

| Bin | n | Mean score | Observed | 95% Wilson CI | Gap |
|---|---|---|---|---|---|
| 0.0–0.1 | 184 | 0.075 | 0.011 | 0.003–0.039 | +0.064 |
| 0.1–0.2 | 683 | 0.150 | 0.095 | 0.075–0.119 | +0.055 |
| 0.2–0.3 | 784 | 0.251 | 0.165 | 0.140–0.192 | +0.086 |
| 0.3–0.4 | 844 | 0.348 | 0.263 | 0.234–0.294 | +0.085 |
| 0.4–0.5 | 720 | 0.448 | 0.403 | 0.368–0.439 | +0.045 |
| 0.5–0.6 | 578 | 0.547 | 0.500 | 0.459–0.541 | +0.047 |
| 0.6–0.7 | 408 | 0.645 | 0.610 | 0.562–0.656 | +0.035 |
| 0.7–0.8 | 285 | 0.747 | 0.684 | 0.628–0.735 | +0.063 |
| 0.8–0.9 | 387 | 0.851 | 0.853 | 0.814–0.885 | −0.002 |
| 0.9–1.0 | 761 | 0.963 | 0.971 | 0.957–0.981 | −0.008 |

The out-of-sample stage-1 table (`reliability_validation_stage1_OUT_OF_SAMPLE.csv`; also in A1 §4.2) has a different shape. It is close to the diagonal below 0.3, over-predicts by 2–13 pp above 0.3, and shows +0.130 in the 0.7–0.8 bin. The two curves differ because the saved model has fitted these labels.

### 3.3 Context from A1, not re-run here

- On held-out test, the deployed raw scores over-predict substantially: mean 0.468 vs 0.357 observed, ECE 0.111, slope 0.60. A1 computed this after freezing its validation results; nothing was fitted or selected on it.
- Neither validation view supports reading the score as a calibrated probability.

---

## 4. Threshold evaluation on validation (both score sets)

Grid: 0.05–0.95 in steps of 0.05, plus the current 0.18982425. Full table: `validation_threshold_grid.csv`, which also includes FPR, FNR, and accuracy.

### 4.1 At the current threshold 0.18982425

| Scores | Flagged (rate) | Precision | Recall | F1 | F2 | Specificity | FPR | FNR | TN / FP / FN / TP |
|---|---|---|---|---|---|---|---|---|---|
| A: saved, IN-SAMPLE | 4,831 (85.7%) | 0.508 | 0.978 | 0.669 | 0.826 | 0.240 | 0.760 | 0.022 | 749 / 2,375 / 54 / 2,456 |
| B: stage-1, out-of-sample | 4,800 (85.2%) | 0.503 | 0.961 | 0.660 | 0.813 | 0.236 | 0.764 | 0.039 | 737 / 2,387 / 97 / 2,413 |

Bootstrap 95% CIs:

| Metric | A | B |
|---|---|---|
| Precision | 0.493–0.523 | 0.488–0.517 |
| Recall | 0.973–0.984 | 0.954–0.969 |
| F2 | 0.816–0.834 | 0.804–0.822 |
| Flag rate | 0.849–0.867 | 0.843–0.862 |

The in-sample model misses 54 at-risk students against 97 out-of-sample. That gap is an optimism artefact of training on these rows.

### 4.2 Candidate thresholds, saved artifact (IN-SAMPLE, for transparency only)

| Threshold | Flagged (rate) | Precision | Recall | F1 | F2 | Specificity | FPR | FNR | TN / FP / FN / TP |
|---|---|---|---|---|---|---|---|---|---|
| 0.10 | 5,450 (96.7%) | 0.460 | 0.999 | 0.630 | 0.810 | 0.058 | 0.942 | 0.001 | 182 / 2,942 / 2 / 2,508 |
| 0.15 | 5,110 (90.7%) | 0.486 | 0.990 | 0.652 | 0.820 | 0.160 | 0.840 | 0.010 | 499 / 2,625 / 25 / 2,485 |
| **0.1898** | **4,831 (85.7%)** | **0.508** | **0.978** | **0.669** | **0.826** | **0.240** | **0.760** | **0.022** | **749 / 2,375 / 54 / 2,456** |
| 0.25 | 4,386 (77.9%) | 0.544 | 0.951 | 0.692 | 0.827 | 0.360 | 0.640 | 0.049 | 1,125 / 1,999 / 123 / 2,387 |
| 0.30 | 3,983 (70.7%) | 0.581 | 0.922 | 0.713 | 0.825 | 0.466 | 0.534 | 0.078 | 1,455 / 1,669 / 196 / 2,314 |
| 0.40 | 3,139 (55.7%) | 0.667 | 0.834 | 0.741 | 0.794 | 0.665 | 0.335 | 0.167 | 2,077 / 1,047 / 418 / 2,092 |
| 0.50 | 2,419 (42.9%) | 0.745 | 0.718 | 0.731 | 0.723 | 0.803 | 0.198 | 0.282 | 2,507 / 617 / 708 / 1,802 |
| 0.60 | 1,841 (32.7%) | 0.822 | 0.603 | 0.696 | 0.637 | 0.895 | 0.105 | 0.397 | 2,796 / 328 / 997 / 1,513 |
| 0.70 | 1,433 (25.4%) | 0.882 | 0.504 | 0.641 | 0.551 | 0.946 | 0.054 | 0.496 | 2,955 / 169 / 1,246 / 1,264 |
| 0.80 | 1,148 (20.4%) | 0.931 | 0.426 | 0.585 | 0.478 | 0.975 | 0.025 | 0.574 | 3,045 / 79 / 1,441 / 1,069 |
| 0.90 | 761 (13.5%) | 0.971 | 0.294 | 0.452 | 0.342 | 0.993 | 0.007 | 0.706 | 3,102 / 22 / 1,771 / 739 |

The corresponding **out-of-sample** stage-1 grid is in the same CSV and in A1 §5.1. A1 §5.2 also gives scenario thresholds for recall floors and alert caps; those are hypothetical constraints, not documented requirements.

**Trade-off.** Every step down in threshold buys recall at the cost of a large increase in alert volume. At the current point, about 2 students are flagged per true positive, and about 2,400 of the 3,124 negative students (≈76%) receive an unnecessary alert. Which point is acceptable depends on coordinator capacity and on the relative harm of a missed student versus an unneeded contact. Neither is defined in the project source or docs. `docs/model-evaluation.md` calls the threshold "a research operating point, not an intervention policy".

---

## 5. Ranking quality, calibration, and threshold choice

These are three separate questions, and a model can do well on one and badly on another.

| Concept | Question it answers | Measured by | Affected by monotone recalibration? | Status here |
|---|---|---|---|---|
| **Ranking (discrimination)** | Do at-risk students tend to score higher than others? | ROC-AUC: the probability that a random positive outranks a random negative | No. Any strictly increasing transform leaves AUC unchanged. | Reasonable: 0.80 on validation (out-of-sample), 0.77 on test |
| **Calibration** | When the model says 0.30, do about 30% of such students actually have the outcome? | Brier, log loss, reliability table, ECE, calibration slope and intercept | Yes. This is exactly what Platt or isotonic scaling change. | **Not established.** Moderate over-prediction on validation; marked over-prediction on test (A1) |
| **Operating threshold** | Above which score should coordinators review a student? | Precision, recall, F-scores, FPR, FNR, flag volume at a cutoff, under an explicit objective | The flagged set is unchanged if the threshold is mapped through the same monotone transform. It changes if a fixed probability cutoff such as 0.5 is kept. | Chosen by validation F2 on a **different** (pre-refit) model; no capacity objective |

Consequences:
- A high AUC does not make the scores probabilities.
- A well-calibrated model can still have a poor threshold if the objective is wrong.
- Calibrating does not by itself change who gets flagged; only the threshold policy does. A1 §7.4 measured this: Platt-calibrated out-of-fold scores re-optimised for F2 gave 0.8129 vs 0.8130 raw.

---

## 6. Can a valid calibration experiment be run with the current partitions?

**For the saved artifact: no.**
- Every labelled row it was not trained on belongs to test 2014J. Fitting a calibrator there, or choosing a threshold there, is prohibited and would leave no unbiased estimate.
- Validation 2014B is training data for this model (Finding 1).
- Cross-validating a calibrator inside 2014B against the saved model's scores would still be calibrating in-sample scores.

**For the train-only stage-1 model: a limited proxy is possible**, and A1 ran it.
- Method: a calibrator fitted with repeated 5-fold CV *within* 2014B.
- Result: Platt scaling reduced ECE from 0.038 to 0.010, but Brier improved only from 0.1786 to 0.1767.
- Limitation 1: this model is not the deployed one.
- Limitation 2: it relies on a single presentation.
- Limitation 3: the validation-to-test calibration shift in A1 (calibration-in-the-large −0.22 → −0.71 logit, prevalence 44.6% → 35.7%) suggests a calibrator learned from one presentation may not transfer.

### Proposed future designs [Recommendation]

1. **Hold out a calibration presentation and do not refit.** Train on 2013B/2013J. Choose the threshold and fit a calibrator (Platt preferred; 2 parameters) on 2014B, both with cross-fitting inside 2014B. Deploy *that* model together with its calibrator and threshold. Evaluate once on 2014J. This makes the stored threshold and calibrator belong to the stored model.
2. **Refit with presentation-grouped cross-fitting.** On train+validation (3 presentations), produce leave-one-presentation-out out-of-fold scores. Fit the calibrator and select the threshold rule on those pooled OOF scores. Refit on all three presentations, apply the calibrator and rule, and evaluate once on 2014J. Purge repeat students across folds, as the current split does.
3. **In either design:**
   - Store the threshold **rule** (for example, a recall floor and/or maximum flag rate), the source-model hash, and the validation flag rate as metadata.
   - Monitor calibration-in-the-large on each new presentation as labels arrive.
   - Reserve a future presentation, or prospectively labelled live data, as the next untouched test set. 2014J has now been evaluated repeatedly.

---

## 7. Other recommendations [Recommendation; none applied]

- Add tests that assert the stored threshold's provenance: the same pipeline hash it was validated on, plus the selection-rule metadata. Also record `score_semantics: "uncalibrated"` in the registry.
- Do not use the saved artifact's validation scores, or the registry/evaluation metrics derived from them, as evidence for threshold or calibration decisions.
- Define the operating objective (capacity and FN/FP harm) with stakeholders before re-selecting any threshold. See A1 §8.

---

## 8. Limitations

- Column B (stage-1) comes from the same validation set that was used for model and threshold selection, so it is mildly optimistic. It is still the least-biased validation view available.
- Single presentation (2014B). Row-level bootstrap CIs ignore any clustering by module.
- Equal-width bins are sparse at the extremes (smallest n = 184). ECE is binning-dependent.
- Database contents were not inspected. No connection to either database was made.

---

## 9. Safety verification

| Check | Result |
|---|---|
| SHA-256 of 164 files before vs after: all `ml/saved_models/*`, `data/processed/*`, raw `data/raw/oulad/*.csv`, `docs/*`, `ml/**`, `backend/app/**`, `backend/tests/**`, `tests/*`, `scripts/*`, `database/*`, `.env`, `.env.example`, `README.md`, `docker-compose.yml`, `student_support.db`, requirements files, and all files of the prior audit A1 | See the final line of this section |
| Training entry point (`python -m ml.supervised.train`) | **Not run.** The only models fitted were the stage-1 reconstruction, in memory and never saved. |
| Test labels | Not used by this follow-up's script (`_test_unused` is deleted immediately after the split) |
| Database | No connection to port 5432 or 5433 |
| Packages | None installed |

**Verification result** (`post_audit_verification.txt`, 2026-10-10T01:42:57Z):
- All **164 protected files have unchanged SHA-256 hashes**.
- **No** protected file has a newer modification time than the baseline.
- `tests/test_canonical_integrity.py`, `tests/test_inference.py`, and `tests/test_features.py`: **31 passed**.

---

## 10. Reproduction

From the project root, in PowerShell. The script writes next to itself, so copy it into a new directory to avoid overwriting these outputs.

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
.venv\Scripts\python.exe reports\calibration_audit_20261010T014038Z_saved_artifact_validation\audit_saved_artifact_validation.py
.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q tests\test_canonical_integrity.py tests\test_inference.py tests\test_features.py
# Git Bash:
sha256sum -c --quiet reports/calibration_audit_20261010T014038Z_saved_artifact_validation/pre_audit_hashes.sha256
```

### Outputs

| File | Content |
|---|---|
| `results.json` | All computed values |
| `reliability_validation_saved_artifact_IN_SAMPLE.csv`, `reliability_validation_stage1_OUT_OF_SAMPLE.csv`, `reliability_validation.svg` | Reliability tables and diagram |
| `validation_threshold_grid.csv` | Threshold grid for both score sets |
| `pre_audit_hashes.sha256`, `post_audit_verification.txt` | Integrity baseline and result |
