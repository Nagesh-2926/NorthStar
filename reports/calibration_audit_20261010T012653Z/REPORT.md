# NorthStar Calibration and Decision-Threshold Audit

| | |
|---|---|
| Audit ID | `calibration_audit_20261010T012653Z` |
| Date (UTC) | 2026-10-10 |
| Scope | The selected supervised early-risk model (`xgboost`, version 1.2.0, feature contract `oulad-early-risk-v2`) and its stored decision threshold |
| Mode | Read-only. No artifacts, data, configuration, or databases were modified. All outputs are in this directory. |
| Environment | Project `.venv`: Python 3.13.15 (same as training), scikit-learn 1.7.2, xgboost 3.1.1, numpy 2.3.4, pandas 2.3.3, scipy 1.18.1 |

Labels used throughout: **[Observed]** means read directly from source or artifacts. **[Calculated]** means computed by this audit (`audit_calibration.py`, outputs in `results.json`). **[Recommendation]** means proposed only; nothing was applied.

---

## 1. Executive summary

| # | Finding | Severity | Evidence |
|---|---|---|---|
| F1 | **The deployed scores are not calibrated probabilities on the later cohort.** On the held-out 2014J presentation, the deployed model's mean score is 0.468 against an observed positive rate of 0.357. ECE is 0.111, the calibration slope is 0.60, and in the top bin it predicts 0.96 where the observed rate is 0.70. | **High** if any consumer reads the score as a probability. Low if it is used only for ranking. | §4.4 (post-freeze, descriptive only) |
| F2 | **On validation, the train-only model's scores are only moderately miscalibrated.** They over-predict by +3.7 pp on average (ECE 0.038, 95% CI 0.029–0.050; slope 0.91). Most of the offset is in the direction expected from `scale_pos_weight = 1.349`. **Calibration does not carry over from 2014B to 2014J:** the calibration-in-the-large shift grows from −0.22 to −0.71 logit while prevalence falls from 44.6% to 35.7%. | Medium | §4.1–4.3 |
| F3 | **The threshold is reused after refitting without validation.** The threshold 0.189824 was chosen on validation scores from a *train-only* model that was never saved. It was then applied unchanged to a model refit on train+validation (`ml/supervised/train.py:96-113`). No validation evidence exists for the deployed model at this threshold. Simulated refits on validation data show the reused cutoff moves alert volume by up to about 7 pp, while F2 changes by at most 0.004. | **Medium** | §2.3, §5.5 |
| F4 | **The F2 objective puts the operating point where most students are flagged.** At 0.1898, the model flags 85.2% of the validation cohort (4,800 of 5,634) and 80.3% of test. Precision is 0.503, against a base rate of 0.446 (lift 1.13). The F2 curve is flat: every threshold from 0.119 to 0.223 is within 0.005 of the maximum F2, which spans flag rates of 80–94%. The exact value 0.1898 is therefore weakly determined by the data. The bootstrap 95% CI for the F2-optimal threshold is 0.138–0.207. | **High (operational)** | §5 |
| F5 | **Every scored cohort is an unseen category of the model feature `code_presentation`.** Unseen categories one-hot-encode to all zeros, a pattern that never occurred in training. On validation, relabelling 2014B as 2013B moves the mean score from 0.483 to 0.522 and the flag rate from 85.2% to 88.2%, with AUC unchanged. This amounts to an arbitrary intercept shift that also affects live predictions. | Medium-low | §5.6 |
| F6 | **Selection bias from reusing validation is small but present.** The nested-CV F2 at the selected threshold is 0.8109 ± 0.007, against 0.8130 in-sample. XGBoost beat Random Forest on validation F2 by only 0.004, inside the bootstrap CI width of about 0.019, so the model choice is not statistically decisive. | Low | §6 |

**Bottom line.**
- **Ranking:** the score ranks students sensibly. It points in the right direction, and AUC is 0.80 on validation and 0.77 on test.
- **Probability interpretation:** not supported. The project's own documentation already says this (`docs/responsible-ai.md:7`, `docs/api-documentation.md:97`, `docs/frontend-architecture.md:36`), and this audit quantifies it.
- **Threshold:** it is the documented validation-F2 optimum of a *different* (pre-refit) model. It has no operational justification beyond the F2 objective, and no capacity constraint is recorded anywhere in the source or docs.
- **Fitting a calibrator for the deployed artifact:** this is **not methodologically supportable with the current split**, because no independent labelled data remains that the deployed model has not trained on, apart from test. See §8 for designs that would support it.

---

## 2. Implementation trace [Observed]

### 2.1 Training-to-inference path

| Step | Location | What happens |
|---|---|---|
| Feature contract | `ml/features/build_dataset.py:9-20` | `PREDICTION_DAY=56`, `FEATURE_VERSION="oulad-early-risk-v2"`. Features: 12 numeric plus `code_module` and `code_presentation`. Target `early_support_label` = Fail or Withdrawn (`:59`). |
| Split | `ml/features/build_dataset.py:197-229` `_student_disjoint_presentation_split` / `split_by_presentation` | Train = 2013B+2013J. Validation = 2014B with train students purged. Test = 2014J with train and validation students purged. |
| Preprocessing | `ml/supervised/train.py:44-51` `make_preprocessor` | Numeric: median imputation with missing indicators, then `StandardScaler`. Categorical: most-frequent imputation, then `OneHotEncoder(handle_unknown="ignore")`. |
| Class weighting | `train.py:90` and `:70-82` `model_specs` | `scale_pos_weight = neg/pos` on **train only** = 1.3494. No resampling. |
| Stage-1 fit | `train.py:92-95` `train_all` | Pipeline fit on train; `predict_proba(X_valid)[:, 1]`. |
| Threshold selection | `train.py:63-67` `select_threshold`, called at `:96` | Maximises validation F2 over `linspace(0.05, 0.95, 91)` ∪ {every validation score}. Ties go to the higher threshold. |
| Model selection | `train.py:100-101` | Highest validation F2, then recall, then ROC-AUC. |
| **Refit** | `train.py:104-113` | Each model is **refit on train+validation** with the stage-1 `pos_weight`. Test is scored, and the artifact is saved as `{"pipeline": final, "threshold": cutoff, ...}`. **`cutoff` is the stage-1 threshold, reused unchanged.** |
| Reports | `train.py:116-141` | `data/processed/supervised_evaluation.json` (exact threshold) and `ml/saved_models/registry.json` (threshold rounded to 6 dp; `selected: true` for xgboost). |
| Inference | `ml/inference/prediction_service.py:72-98` `load_model` / `predict` | `support_priority_score = pipeline.predict_proba(row)[0][1]`. `priority_band = "review_for_support" if score >= artifact["threshold"]`. No calibration step. |
| Backend loading | `backend/app/ml/model_manager.py:29-49` `_load_supervised` | Reads the registry entry with `selected=True`, `joblib.load`s it, and calls `predict_supervised`. |
| Live features | `backend/app/services/feature_assembly.py:82` | `code_presentation` is passed straight from the enrollment record to the model. |
| Persistence | `backend/app/api/routes/predictions.py:82-83`, `imports.py:234-235`, `models/entities.py:184-197` | The score and threshold are stored per prediction and constrained to [0, 1]. |

### 2.2 Threshold provenance

| Source | Value |
|---|---|
| `xgboost.joblib["threshold"]` (used at inference) | 0.18982425332069397 |
| `supervised_evaluation.json["selected_threshold"]` | 0.18982425332069397 |
| `registry.json` metrics.threshold | 0.189824 (rounded, display only) |
| Selection rule | Maximum validation F2 over the 2014B scores of the **train-only** model |
| Selected before or after the refit? | **Before.** It is reused after the refit without re-validation. |

The threshold is exactly equal to one validation student's score. This is because candidate thresholds include the scores themselves. It is harmless in practice, but it means float32/float64 rounding can flip that single boundary row (see §7.3).

### 2.3 Factors that affect probability interpretation

- **`scale_pos_weight = 1.349`** multiplies the training odds of the positive class, so the raw scores are pushed upward by design.
- **The refit reuses the stage-1 `pos_weight`.** The train+validation ratio would be 9,694 / 7,379 = 1.314. This is a minor inconsistency.
- **Unseen `code_presentation`.** Each new cohort encodes as all-zeros (F5).
- **No oversampling** is used, which this audit confirmed in the code.
- **Positive-class definition** is consistent across training, evaluation, tests, and inference: label 1 = Fail/Withdrawn, `classes_ == [0, 1]`, and the score is `predict_proba[:, 1]`. This is asserted in `tests/test_canonical_integrity.py:136`.

### 2.4 How the validation and test partitions were used

| Partition | Uses found in source |
|---|---|
| Validation 2014B | Threshold selection for each of the 3 models; model selection; **training data for the deployed refit** |
| Test 2014J | Final metrics for all 3 models after selection (`train.py:104-109`). No code path selects anything from test. |

---

## 3. Baseline reproduction [Calculated vs Observed]

The data was loaded exactly as in `tests/test_canonical_integrity.py`: the canonical CSV, with `source_student_id` renamed to `id_student`, passed through `split_by_presentation`.

| Item | Recorded | Reproduced | Match |
|---|---|---|---|
| Canonical rows | 26,447 | 26,447 | ✔ |
| Train / validation / test rows | 11,439 / 5,634 / 7,626 | 11,439 / 5,634 / 7,626 | ✔ |
| Train positives (prevalence) | 4,869 | 4,869 (42.56%) | ✔ |
| Validation positives (prevalence) | — | 2,510 (44.55%) | — |
| Test positives (prevalence) | 2,726 (from the confusion matrix) | 2,726 (35.75%) | ✔ |
| **Deployed test metrics @0.189824** | ROC-AUC 0.769775, P 0.42178, R 0.94754, F2 0.75846, TN/FP/FN/TP 1359/3541/143/2583 | identical (difference < 1e-9) | ✔ |
| **Stage-1 (train-only) model, rebuilt in memory with the project's own functions** | val threshold 0.18982425332069397, ROC-AUC 0.800834, F2 0.813005, 737/2387/97/2413 | identical | ✔ |
| Refit rebuilt in memory vs saved `xgboost.joblib` | — | max \|Δscore\| on 2014J features = **0.0** | ✔ |
| Project tests `tests/test_canonical_integrity.py`, `test_inference.py`, `test_features.py` | — | 31 passed (24 before the analysis, 31 after) | ✔ |

**Orientation (validation, stage-1 model).** Mean score is 0.647 for positives and 0.351 for negatives. Decile event rates rise from 0.112 to 0.956, with one non-monotone step between deciles 3 and 4 (0.258 → 0.248, within sampling noise). Higher scores mean higher risk. ✔

Both reproducibility gates passed, so the calibration analysis went ahead.

---

## 4. Calibration assessment

**Why a model had to be rebuilt.** The deployed artifact was trained on 2014B, so its validation scores are in-sample. Brier 0.158, AUC 0.848, and flag rate 85.7% on validation look optimistic for that reason, and **must not** be used. The only valid out-of-sample validation scores come from the stage-1 train-only model. This is the same model whose scores determined the threshold. It was rebuilt in memory, verified bit-for-bit against the recorded validation metrics (§3), and never saved.

**Metric definitions:**
- **Brier** = mean (p − y)².
- **Log loss** = −mean[y·log p + (1−y)·log(1−p)].
- **ECE** = Σ_b (n_b/N)·|mean p_b − observed rate_b|. Reported with 10 equal-width bins and with 10 equal-count (quantile) bins.
- **Calibration slope / intercept**: from a logistic regression of y on logit(p). Ideal values are 1 and 0.
- **Calibration-in-the-large (CITL)**: the logit shift α that makes the mean of sigmoid(logit p + α) equal the prevalence. Ideal is 0; negative means over-prediction.
- **CIs**: 1,000 row-level bootstrap resamples (seed 20261010). Students are almost unique within a partition (5,381 students across 5,634 rows).

### 4.1 Raw scores, validation 2014B (n = 5,634, prevalence 0.4455)

| Metric | Value | 95% bootstrap CI | Reference |
|---|---|---|---|
| Mean predicted | 0.4830 | mean − prev: +0.026 to +0.049 | prevalence 0.4455 |
| Brier | 0.1786 | 0.1733–0.1838 | prevalence-only 0.2470 (skill 0.277) |
| Log loss | 0.5321 | 0.5187–0.5452 | prevalence-only 0.6872 |
| ECE, 10 uniform bins | 0.0377 | 0.0294–0.0502 | — |
| ECE, 10 quantile bins | 0.0384 | 0.0311–0.0510 | — |
| Calibration slope / intercept | 0.906 / −0.230 | — | 1 / 0 |
| CITL logit shift | −0.219 | — | 0 |
| ROC-AUC | 0.8008 | 0.7895–0.8123 | — |

### 4.2 Reliability table, validation, raw, 10 equal-width bins (`validation_reliability_uniform10_raw.csv`, `reliability_validation.svg`)

| Bin | n | Mean predicted | Observed | 95% Wilson CI | Gap |
|---|---|---|---|---|---|
| 0.0–0.1 | 209 | 0.073 | 0.077 | 0.048–0.121 | −0.003 |
| 0.1–0.2 | 705 | 0.152 | 0.139 | 0.115–0.167 | +0.013 |
| 0.2–0.3 | 831 | 0.251 | 0.247 | 0.219–0.277 | +0.004 |
| 0.3–0.4 | 872 | 0.350 | 0.294 | 0.264–0.325 | **+0.057** |
| 0.4–0.5 | 794 | 0.448 | 0.411 | 0.377–0.445 | **+0.037** |
| 0.5–0.6 | 481 | 0.542 | 0.486 | 0.442–0.531 | **+0.055** |
| 0.6–0.7 | 303 | 0.645 | 0.568 | 0.511–0.622 | **+0.078** |
| 0.7–0.8 | 279 | 0.750 | 0.620 | 0.562–0.675 | **+0.130** |
| 0.8–0.9 | 415 | 0.853 | 0.810 | 0.769–0.845 | **+0.043** |
| 0.9–1.0 | 745 | 0.953 | 0.932 | 0.911–0.948 | **+0.022** |

Bold marks bins where the mean prediction falls outside the 95% CI of the observed rate. Scores below 0.3 are well calibrated. Above 0.3, the model over-predicts consistently by 2–13 pp. The smallest bin has n = 209, so no bin is sparse enough to make its estimate unreliable. Classes are close to balanced (44.6% positive), so imbalance does not distort the binning. Equal-width ECE is a biased estimator and depends on the bin count. It is reported next to the quantile version, and the two agree.

**By module (validation, CITL only)** — mean raw score vs observed rate (Wilson CI):

| Module | Mean raw score | Observed rate (CI) |
|---|---|---|
| BBB | 0.427 | 0.401 (0.374–0.429) |
| CCC | **0.628** | 0.512 (0.480–0.543) |
| DDD | 0.507 | 0.486 (0.454–0.519) |
| EEE | 0.363 | 0.384 (0.345–0.424) |
| FFF | 0.486 | 0.468 (0.440–0.496) |
| GGG | 0.443 | 0.395 (0.362–0.430) |

CCC is over-predicted by about 12 pp. GGG also has the lowest AUC (0.699). These are single-presentation subgroup estimates and should be treated as exploratory.

### 4.3 Candidate calibrators (validation only, repeated stratified 5-fold × 20, pooled out-of-fold)

Each calibrator was fitted on 4/5 of validation and scored on the held-out 1/5. Values are the mean across the 20 repeats; the SD across repeats is ≤ 0.002 for every metric.

| Method | Parameters | Brier | Log loss | ECE (uniform) | ECE (quantile) | Slope | AUC |
|---|---|---|---|---|---|---|---|
| Raw | — | 0.1786 | 0.5321 | 0.0377 | 0.0384 | 0.906 | 0.8008 |
| Undo `scale_pos_weight`, p/(p + 1.349·(1−p)) | 0 (analytic, not fitted) | 0.1771 | 0.5285 | 0.0253 | 0.0273 | 0.906 | 0.8008 |
| Platt (logistic on logit p) | 2 | **0.1767** | **0.5272** | **0.0098** | 0.0177 | 0.998 | 0.8007 |
| Isotonic | step function (109 levels on full fit) | 0.1769 | 0.5333 | 0.0100 | **0.0087** | 0.937 | 0.7981 |

What the table shows:
- Undoing the class weight alone removes most of the average offset; mean predicted goes from 0.483 to 0.432, so it slightly over-corrects. The class weighting therefore explains the *direction and most of the size* of the bias, but not the slope.
- Platt scaling gives the best log loss and Brier while preserving ranking.
- Isotonic matches Platt on ECE but has worse log loss and loses AUC (0.801 → 0.798) through ties. With only one presentation of about 5.6k rows, Platt is the safer family.
- The absolute gains are **small**: Brier improves by 1.1% and log loss by 0.9%.

**Limitation:** these calibrators are fitted to the *stage-1* model's scores. They cannot be applied to the deployed refit model, which has a different score distribution and was trained on these very rows.

### 4.4 Post-freeze descriptive check: deployed raw scores on test 2014J

The validation results above were written and hashed **before** test labels were read (`results_validation_frozen.json`, sha256 `a529b5b7…ea787`). On test, the audit evaluated only the deployed raw scores. No calibrator or threshold was fitted, selected, or compared there.

| Metric | Value |
|---|---|
| n / positives / prevalence | 7,626 / 2,726 / 0.3575 |
| Mean predicted | **0.4681** (+11.1 pp) |
| Brier (prevalence baseline) | 0.2014 (0.2297), skill 0.123 |
| Log loss (prevalence baseline) | 0.6182 (0.6519) |
| ECE, uniform and quantile | **0.1106** |
| Calibration slope / intercept | **0.596** / −0.661 |
| CITL logit shift | **−0.709** |

Reliability on test (`test_reliability_uniform10_deployed_raw_POSTFREEZE.csv`, `reliability_test_postfreeze.svg`): the model over-predicts in every bin except 0–0.1. The worst gaps are in the top two bins: 0.849 predicted vs 0.571 observed (n = 543), and 0.959 vs 0.697 (n = 1,035).

**How to read this.** Test calibration is much worse than validation calibration. Contributing factors are a drop in prevalence (44.6% → 35.7%), temporal shift between presentations, and refit effects. The model differs between the two checks (stage-1 on validation, refit on test), so this comparison cannot separate those causes. In either case, a calibration map learned on one presentation would not have been reliable on the next. That is the central argument against treating these scores as probabilities without ongoing recalibration.

---

## 5. Threshold comparison (validation 2014B only, stage-1 out-of-sample scores)

Definitions: precision = TP/(TP+FP); recall = TP/(TP+FN); specificity = TN/(TN+FP); FPR = 1 − specificity; FNR = 1 − recall; F_β = (1+β²)PR/(β²P+R); flag rate = (TP+FP)/N. N = 5,634.

### 5.1 Grid (`validation_threshold_grid.csv`; 0.05–0.95 in steps of 0.05, plus the current value)

| Threshold | Flagged (rate) | Precision | Recall | F1 | F2 | Specificity | FPR | FNR | TN / FP / FN / TP |
|---|---|---|---|---|---|---|---|---|---|
| 0.10 | 5,425 (96.3%) | 0.460 | 0.994 | 0.629 | 0.806 | 0.062 | 0.938 | 0.006 | 193 / 2,931 / 16 / 2,494 |
| 0.15 | 5,086 (90.3%) | 0.482 | 0.977 | 0.645 | 0.810 | 0.157 | 0.844 | 0.024 | 489 / 2,635 / 59 / 2,451 |
| **0.1898 (current)** | **4,800 (85.2%)** | **0.503** | **0.961** | **0.660** | **0.813** | **0.236** | **0.764** | **0.039** | **737 / 2,387 / 97 / 2,413** |
| 0.20 | 4,720 (83.8%) | 0.508 | 0.955 | 0.663 | 0.812 | 0.256 | 0.744 | 0.045 | 800 / 2,324 / 114 / 2,396 |
| 0.25 | 4,311 (76.5%) | 0.535 | 0.918 | 0.676 | 0.803 | 0.358 | 0.642 | 0.082 | 1,118 / 2,006 / 205 / 2,305 |
| 0.30 | 3,889 (69.0%) | 0.563 | 0.873 | 0.685 | 0.787 | 0.457 | 0.544 | 0.127 | 1,426 / 1,698 / 319 / 2,191 |
| 0.35 | 3,451 (61.3%) | 0.605 | 0.832 | 0.701 | 0.774 | 0.564 | 0.436 | 0.168 | 1,762 / 1,362 / 421 / 2,089 |
| 0.40 | 3,017 (53.6%) | 0.641 | 0.771 | 0.700 | 0.741 | 0.654 | 0.346 | 0.229 | 2,042 / 1,082 / 575 / 1,935 |
| 0.45 | 2,606 (46.3%) | 0.682 | 0.708 | 0.695 | 0.703 | 0.735 | 0.265 | 0.292 | 2,295 / 829 / 733 / 1,777 |
| 0.50 | 2,223 (39.5%) | 0.724 | 0.641 | 0.680 | 0.656 | 0.804 | 0.197 | 0.359 | 2,510 / 614 / 901 / 1,609 |
| 0.60 | 1,742 (30.9%) | 0.789 | 0.548 | 0.647 | 0.584 | 0.883 | 0.118 | 0.452 | 2,757 / 367 / 1,135 / 1,375 |
| 0.70 | 1,439 (25.5%) | 0.836 | 0.479 | 0.609 | 0.524 | 0.925 | 0.076 | 0.521 | 2,888 / 236 / 1,307 / 1,203 |
| 0.80 | 1,160 (20.6%) | 0.888 | 0.410 | 0.561 | 0.460 | 0.958 | 0.042 | 0.590 | 2,994 / 130 / 1,480 / 1,030 |
| 0.90 | 745 (13.2%) | 0.932 | 0.277 | 0.426 | 0.322 | 0.984 | 0.016 | 0.724 | 3,073 / 51 / 1,816 / 694 |

The full 20-row grid is in the CSV.

### 5.2 Objective-driven scenarios (`validation_threshold_scenarios.csv`)

The capacity and recall constraints below are **hypothetical scenarios**. No such requirement exists in the source code or documentation.

| Objective | Threshold | Flagged (rate) | Precision | Recall | F2 | FP | FN |
|---|---|---|---|---|---|---|---|
| Max F2 (**current, documented objective**) | 0.1898 | 4,800 (85.2%) | 0.503 | 0.961 | 0.813 | 2,387 | 97 |
| Highest threshold with recall ≥ 0.95 | 0.2076 | 4,675 (83.0%) | 0.510 | 0.950 | 0.810 | 2,290 | 125 |
| Highest threshold with recall ≥ 0.90 | 0.2734 | 4,127 (73.3%) | 0.547 | 0.900 | 0.797 | 1,868 | 251 |
| Highest threshold with recall ≥ 0.80 | 0.3757 | 3,235 (57.4%) | 0.621 | 0.800 | 0.756 | 1,227 | 502 |
| Max F1 | 0.4300 | 2,764 (49.1%) | 0.672 | 0.739 | 0.725 | 908 | 654 |
| Max Youden J | 0.4676 | 2,450 (43.5%) | 0.703 | 0.686 | 0.689 | 728 | 788 |
| Alerts ≤ 50% of cohort, max recall | 0.4241 | 2,814 (49.9%) | 0.665 | 0.745 | 0.727 | 944 | 640 |
| Alerts ≤ 40% of cohort, max recall | 0.4947 | 2,253 (40.0%) | 0.720 | 0.647 | 0.660 | 630 | 887 |
| Alerts ≤ 30% of cohort, max recall | 0.6134 | 1,690 (30.0%) | 0.796 | 0.536 | 0.574 | 344 | 1,164 |
| Fixed 0.5 | 0.5000 | 2,223 (39.5%) | 0.724 | 0.641 | 0.656 | 614 | 901 |

### 5.3 Uncertainty at the current threshold (1,000 bootstrap resamples)

| Metric | 95% CI |
|---|---|
| Precision | 0.488–0.517 |
| Recall | 0.954–0.969 |
| F2 | 0.804–0.822 |
| Specificity | 0.220–0.251 |
| Flag rate | 0.843–0.862 |

### 5.4 Stability of the F2-optimal threshold

- **Flatness:** thresholds from 0.1186 to 0.2230 all reach within 0.005 of the maximum F2 (0.8130). That range corresponds to flag rates of 80.4% to 94.3%.
- **Bootstrap** of the F2-argmax: median 0.1898, IQR 0.173–0.195, 95% CI 0.138–0.207. That CI corresponds to flag rates of 83.1% to 91.9%.
- **Nested CV** (threshold chosen on 4/5 of validation, evaluated on the held-out 1/5, 100 folds): chosen threshold 0.188 ± 0.007; held-out F2 0.8109 ± 0.007, recall 0.960, precision 0.500, flag rate 0.855. The in-sample F2 is 0.8130, so the **optimism bias is about 0.002**.

### 5.5 Does reusing the threshold after a refit hold up? (validation-only simulation, plus a label-free check)

**Simulation.** Model A was trained on a subset of the train partition, and its F2 threshold t_A was selected on validation. Model B was then refit on the full train partition, mirroring `train.py`'s reuse of the stage-1 `pos_weight`. Both models are scored on validation.

| Scenario | t_A | B's own F2 threshold | B @ t_A: flag rate / recall / F2 | B @ own threshold: flag rate / recall / F2 |
|---|---|---|---|---|
| A = 2013B only → B = 2013B+2013J | 0.107 | 0.157 | 93.2% / 0.986 / 0.8095 | 86.1% / 0.965 / 0.8131 |
| A = 2013J only → B = 2013B+2013J | 0.208 | 0.203 | 84.4% / 0.959 / 0.8135 | 85.2% / 0.963 / 0.8140 |
| A = random 67%, seeds 0–4 | 0.152–0.209 | 0.181–0.197 | 82.4–89.8% / 0.947–0.976 / 0.809–0.813 | 83.6–85.9% / 0.955–0.965 / 0.813–0.814 |

**Label-free check on the real refit.** This used 2014J features only, with no labels; nothing was fitted or selected from it.
- At 0.1898, the stage-1 model flags 77.9% of 2014J and the deployed model flags 80.3%. That is +2.4 pp, about 182 more students out of 7,626.
- The deployed-model threshold that would preserve stage-1's flag rate is 0.2047.
- The Spearman rank correlation between the two models' scores is 0.965.

**What this shows.** Because the F2 curve is flat, reusing the threshold costs at most about 0.004 F2. However, it shifts **alert volume** unpredictably, by −2.4 to +7.1 pp in the simulations. Alert volume is the quantity coordinators actually experience. The current pipeline does not measure or record that shift.

### 5.6 `code_presentation` sensitivity (validation, stage-1 model)

| Encoding of the 2014B rows | Mean score | Flag rate @0.1898 | AUC | Brier |
|---|---|---|---|---|
| 2014B (actual; unseen, so encoded as all zeros) | 0.483 | 85.2% | 0.8008 | 0.1786 |
| Relabelled 2013B | 0.522 | 88.2% | 0.8005 | 0.1842 |
| Relabelled 2013J | 0.479 | 84.7% | 0.8007 | 0.1783 |

In the deployed model, the one-hot columns for `code_presentation` rank 14th (2013J), 23rd, and 24th by split importance. Every live cohort is likewise an unseen category, so this encoding contributes a level shift that cannot be validated.

---

## 6. Methodology and leakage review

| Check | Result |
|---|---|
| Student-disjoint chronological split | ✔ Enforced in code (`build_dataset.py:212-213`) and tested (`test_canonical_integrity.py:105`) |
| Preprocessing fitted without test rows | ✔ Tested (`test_canonical_integrity.py:111-118`) |
| Threshold chosen on validation only | ✔ For the **stage-1** model |
| Threshold valid for the **deployed** model | ✘ **Not validated.** The refit used validation as training data, so no validation evidence exists for the deployed model (F3). |
| Model selection on validation only | ✔ |
| Selection bias on validation | Present but small: threshold optimism ≈ 0.002 F2 (nested CV). Model choice rests on a 0.004 F2 margin, inside the CI. Validation metrics are **not** an unbiased final estimate. |
| Test-set influence on decisions | No code path selects anything from test. **Risk:** test has been evaluated repeatedly across pipeline versions (`docs/ml-pipeline.md:23` records regenerated folds after an earlier audit), and `docs/model-evaluation.md:23` discusses test-set rankings. Repeated viewing weakens test 2014J as a pristine holdout. This audit added one more descriptive use (§4.4), recorded and run after the freeze. |
| Labels, positive class, and score column consistent | ✔ (§2.3) |
| Calibration evaluable on independent data for the deployed artifact | ✘ Only test is out-of-sample for it, and test must not be used for fitting. |

---

## 7. Operational implications

### 7.1 Alert volume

At the deployed threshold:
- **Validation:** 4,800 of 5,634 students flagged (85%). About 2 alerts per true positive: 2,387 unnecessary alerts and 97 missed students.
- **Test (recorded):** 6,124 of 7,626 flagged (80%), with 3,541 false positives and 143 false negatives.

A flag at this level carries little information. It lifts the positive rate only from 44.6% to 50.3% on validation, and from 35.7% to 42.2% on test.

### 7.2 The trade-off

Raising the threshold to 0.27 keeps recall at 0.90 on validation:

| | Current (0.1898) | 0.27 |
|---|---|---|
| Students flagged | 4,800 | 4,127 (−673) |
| False positives | 2,387 | 1,868 (−519) |
| Missed at-risk students | 97 | 251 (+154) |

Under a 40% alert cap (0.495), about 35% of at-risk students would be missed.

Which point is right depends on coordinator capacity and on the relative harm of each error type. A false negative is a missed support chance. A false positive means needless contact, stigma, or workload (`docs/responsible-ai.md:8`). The data cannot answer that question; it is a governance decision.

### 7.3 Boundary tie

Because the threshold equals an observed score, any re-serialisation that changes float precision can flip that student's flag. This is a single row.

### 7.4 Effect of calibration on alerts

Platt scaling is strictly monotone, so it **does not change rankings or alert sets** as long as the threshold is mapped with it. The current 0.1898 corresponds to:
- ≈ 0.176 after Platt scaling,
- ≈ 0.148 after undoing the class weight,
- ≈ 0.167 after isotonic calibration.

The single-row mismatch in the automated check is the float32/float64 boundary tie from §7.3; in float64 there are zero mismatches.

Re-selecting F2 on calibrated out-of-fold scores gives F2 0.8129 for Platt and 0.8113 for isotonic, against 0.8130 raw, so there is **no measured gain**.

The danger is applying calibration while keeping a fixed probability cutoff. For example, at 0.5 the alert count drops from 2,223 (raw) to 1,864 (Platt). Calibration changes how scores are interpreted. It only changes alerts if the threshold policy is defined in probability terms.

---

## 8. Recommendations (not applied)

| Priority | Recommendation | Rationale |
|---|---|---|
| **P1** | Keep presenting `support_priority_score` as a ranking signal, not a probability, in the API, UI, and exports. Add an explicit `score_semantics: "uncalibrated_rank_score"` field to the registry and artifact metadata. | F1. The docs already say this; make it machine-readable. |
| **P1** | Agree an explicit operating objective with stakeholders: a maximum alert rate (capacity) and/or a minimum recall, plus a cost ratio for FN vs FP. Encode the selection **rule** (for example, "highest threshold with validation recall ≥ R and flag rate ≤ C") and its target flag rate in metadata, not only the resulting number. | F4. The F2 optimum flags 80–85% of students, and no capacity requirement exists in source or docs. |
| **P2** | Fix the threshold-after-refit gap. Choose one: **(a)** deploy the validated stage-1 model and threshold without refitting; **(b)** refit, then pick the threshold from cross-fitted out-of-fold scores on train+validation (leave-one-presentation-out); or **(c)** refit and carry over the validated *flag-rate quantile* rather than the raw cutoff, then monitor. Record `threshold_source_model_sha256` and the validation flag rate alongside the threshold. | F3. Reuse shifted alert volume by up to 7 pp in simulation. |
| **P2** | Add a regression test that fails if the stored threshold was not derived from the same pipeline it is stored with, or if the rule metadata is missing. | Keeps the policy intact across future refits. |
| **P3** | If probability interpretation is ever needed, use an evaluation design with an independent calibration set. For example: train on 2013B/J → calibrate on 2014B with **Platt** (2 parameters, preserves ranking) → **do not refit** → evaluate once on a fresh presentation. Alternatively, cross-fit the calibrator with leave-one-presentation-out. Prefer Platt over isotonic given a single presentation of about 5.6k rows. | F2 and §4.3. Also: the validation-to-test shift (CITL −0.22 → −0.71) means any static calibrator needs monitoring of calibration-in-the-large per new presentation, with intercept recalibration when prevalence moves. |
| **P3** | Remove `code_presentation` as a feature, or replace it with a season indicator (B/J) that is seen in training, and re-validate. | F5. Unseen category leads to an unvalidated level shift. |
| **P4** | Review module-level calibration (CCC is over-predicted by about 12 pp on validation) and run the planned subgroup error-rate review. | §4.2. Exploratory only. |
| **P4** | Treat 2014J as partially used for calibration claims. Do not tune anything from §4.4. Reserve a future presentation, or the live-deployment cohort with prospective labels, as the next clean holdout. | §6 |

---

## 9. Safety verification [Calculated]

| Resource | Check | Result |
|---|---|---|
| 135 files: `ml/saved_models/*` (all model artifacts, `registry.json`, LSTM/K-Means), `data/processed/*` (canonical CSV, evaluation JSONs, manifests, registries), `data/raw/oulad/*.csv` (7 raw files), `data/templates`, `docs/*`, `database/demo_database.dump`, `ml/**/*.py`, `backend/app/**`, `tests/*`, `scripts/*`, `.env`, `.env.example`, `README.md`, `docker-compose.yml`, `student_support.db`, requirements files | SHA-256 before (`pre_audit_hashes.sha256`) vs after (`sha256sum -c`) | **All 135 unchanged** |
| Same directories | Files with mtime newer than the pre-audit snapshot (excluding `__pycache__`) | **None** |
| Canonical dataset | sha256 `8b489a28…b13f`, 26,447 rows | Unchanged |
| Threshold metadata | artifact 0.18982425332069397 = evaluation JSON; registry 0.189824 | Unchanged |
| Application behaviour | `tests/test_canonical_integrity.py`, `tests/test_inference.py`, `tests/test_features.py` | **31 passed** after the audit |
| Databases | No database client, connection, or ORM session was created. The audit imports only `ml.features.build_dataset` and `ml.supervised.train` (whose `main()` is guarded and was not called). Port 5432 and port 5433 were never contacted. | DB records were **not directly inspected** (by design). `.env` and `student_support.db` hashes are unchanged. |
| Models | Stage-1 and refit models were rebuilt **in memory only**; nothing was persisted. `PYTHONDONTWRITEBYTECODE=1` was set. | — |
| Packages | Nothing installed. matplotlib is absent from `.venv`, so plots are hand-written SVG. | — |

---

## 10. Reproduction instructions

From the project root, in PowerShell. Both commands are read-only with respect to the project, except that the audit script writes into **its own directory**.

```powershell
# 1. Project reproduction tests (read-only)
.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q tests\test_canonical_integrity.py tests\test_inference.py tests\test_features.py

# 2. Re-run the audit. To avoid overwriting these outputs, copy the script into a new
#    timestamped directory first, because the script writes next to itself.
$d = "reports\calibration_audit_$((Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ'))"
New-Item -ItemType Directory $d | Out-Null
Copy-Item reports\calibration_audit_20261010T012653Z\audit_calibration.py $d
$env:PYTHONDONTWRITEBYTECODE = "1"
.venv\Scripts\python.exe "$d\audit_calibration.py"     # ~30 s; aborts if either reproducibility gate fails

# 3. Verify nothing protected changed (Git Bash)
sha256sum -c --quiet reports/calibration_audit_20261010T012653Z/pre_audit_hashes.sha256
```

The run is deterministic: seed 20261010, XGBoost `random_state=42`, and the recorded validation and test metrics reproduce exactly.

### Files in this directory

| File | Content |
|---|---|
| `REPORT.md` | This report |
| `audit_calibration.py` | Complete audit code |
| `results_validation_frozen.json` | All validation-stage results, frozen before any test labels were read |
| `results.json` | Frozen results plus the post-freeze test descriptive block |
| `validation_reliability_*.csv` | Reliability tables: raw, Platt OOF, isotonic OOF, weight-undo; uniform and quantile bins |
| `validation_threshold_grid.csv`, `validation_threshold_scenarios.csv` | Threshold tables |
| `test_reliability_uniform10_deployed_raw_POSTFREEZE.csv` | Descriptive test reliability table |
| `reliability_validation.svg`, `reliability_test_postfreeze.svg` | Reliability diagrams |
| `pre_audit_hashes.sha256` | Integrity baseline |

### Out of scope

The LSTM model (not selected) and the grade-score regressor were not audited. One observation from the source: the LSTM is **not** refit, so its saved threshold belongs to the same saved network (`ml/timeseries/train_lstm.py:38-42,68`). However, it uses the validation fold both for Keras early stopping (`validation_data=`) and for F2 threshold selection, so its validation metrics carry a double selection bias.
