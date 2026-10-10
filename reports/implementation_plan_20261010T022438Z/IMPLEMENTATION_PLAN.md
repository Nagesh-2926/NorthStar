# NorthStar: Calibration and Threshold Implementation Plan

| | |
|---|---|
| Document type | **Plan only.** Nothing described here has been implemented, trained, calibrated, migrated, or deployed. |
| Created (UTC) | 2026-10-10T02:24:38Z |
| Primary input | `reports/design_calibration_threshold_protocol_20261010T014934Z/DESIGN.md` ("DESIGN") |
| Supporting evidence | `reports/calibration_audit_20261010T012653Z/REPORT.md` ("A1"), `reports/calibration_audit_20261010T014038Z_saved_artifact_validation/REPORT.md` ("A2") |
| Model in scope | Selected supervised early-risk classifier `xgboost` v1.2.0, feature contract `oulad-early-risk-v2` |

**Labels used throughout**

| Label | Meaning |
|---|---|
| **[Fact]** | Verified against repository files for this plan, or re-read from a file whose hash is unchanged |
| **[Prior]** | A measurement from A1/A2 that was not recomputed for this plan |
| **[Rec]** | Recommendation |
| **[Assumption]** | Stated assumption |
| **[Open]** | Unresolved question |
| **[DECISION]** | Requires stakeholder approval; no value is assumed |

---

## 1. Executive summary

**Problem.** The deployed early-risk model and its alert threshold were never validated together.
- The threshold 0.18982425 came from validation F2 on a **train-only** model.
- The saved model was then **refit on train + validation** and kept that threshold.
- The saved model's validation results are therefore in-sample.
- Its scores have never been shown to be calibrated probabilities.

**Data constraints.**
- The only labelled data the saved model has not trained on is the 2014J presentation. 2014J has been inspected repeatedly and is not a pristine holdout.
- OULAD has only four presentations, and module coverage is uneven.

**Plan.** Eight stages, from Stage 0 to Stage 7, each with an approval gate:

| Stage | Name |
|---|---|
| 0 | Baseline inventory |
| 1 | Evaluation protocol |
| 2 | Calibration evaluation |
| 3 | Threshold and alert capacity |
| 4 | Matched model + calibrator + threshold |
| 5 | Tests |
| 6 | Shadow evaluation and monitoring |
| 7 | Go/no-go |

- Stages 0–5 can be carried out on historical data and code without changing what users see.
- Stage 6 depends on prerequisites the project **does not currently meet**: outcome collection for live enrollments, prediction-linked intervention logging, and access to a future cohort.
- **No stage can establish production readiness** without the prospective evidence from Stage 6.

**Recommended path** [Rec], consistent with DESIGN:
- Produce a *matched* candidate (train-only model + calibrator + threshold, all derived from 2014B with student-grouped cross-fitting, **no refit**).
- Run cross-fitting only as a sensitivity analysis.
- Evaluate once on 2014J as **exploratory, repeatedly-viewed** evidence.
- Make any operational decision depend on frozen prospective (shadow) evaluation.

**Decisions outstanding** (Stage 7): alert capacity, recall and missed-risk costs, whether calibrated probabilities are needed at all, the versioning scheme, the status of 2014J, access to future cohorts, minimum metrics, and monitoring ownership.

---

## 2. Verified current-state findings

| # | Finding | Evidence |
|---|---|---|
| F-1 | **[Fact]** Split: train = 2013B+2013J (11,439 rows), validation = 2014B (5,634), test = 2014J (7,626). Students are purged forward across partitions. | `ml/features/build_dataset.py:197-234` (`_student_disjoint_presentation_split`, `split_by_presentation`, `split_diagnostics`); `data/processed/supervised_evaluation.json` `split`, `student_independence` |
| F-2 | **[Fact]** The threshold is selected by maximising validation F2 using a model fitted on train only. | `ml/supervised/train.py:92-96` (`train_all`), `select_threshold` `:63-67` |
| F-3 | **[Fact]** Each model is refit on train + validation, and the stage-1 threshold is saved with the refit pipeline. | `train.py:104-113` (comment at `:105`: "Refit after model/threshold selection using train + validation only") |
| F-4 | **[Fact]** The saved artifact holds threshold 0.18982425332069397, feature version `oulad-early-risk-v2`, prediction day 56, and classes `[0, 1]`. Its one-hot encoder knows presentations `2013B, 2013J, 2014B` and modules `AAA…GGG`, including CCC. It was therefore trained on 2014B. Artifact sha256 is `466c1cf2…6cc61aef`. | Read-only load of `ml/saved_models/xgboost.joblib` for this plan |
| F-5 | **[Fact]** The registry entry has `name, version, training_date_utc, dataset_version, feature_version, metrics, selected, path`. It has **no** fields for artifact hash, threshold provenance, calibrator, or score semantics. | `ml/saved_models/registry.json` |
| F-6 | **[Fact]** Inference returns `support_priority_score = predict_proba[...][1]` and `priority_band = "review_for_support"` if score ≥ threshold, else `"no_flag_from_model"`. There is no calibration step. | `ml/inference/prediction_service.py` `load_model`, `predict`; served via `backend/app/ml/model_manager.py` `_load_supervised` |
| F-7 | **[Fact]** Persisted predictions store model name/version, feature version, score, threshold, band, and observed signals. A CHECK constraint keeps score and threshold in [0, 1]. There is no artifact hash, calibrator ID, or score-semantics field. | `backend/app/models/entities.py:182-200` (`Prediction`); `backend/app/schemas/common.py` `PredictionRead`, `LatestPredictionSummary` |
| F-8 | **[Fact]** The frontend depends on the band strings `review_for_support` / `no_flag_from_model`. | `frontend/src/components/Primitives.jsx:38-56`, `frontend/src/pages/CoordinatorPages.jsx:23-128` |
| F-9 | **[Fact]** The `Enrollment` table has **no outcome field** (no final result), so live outcomes are not collected. | `backend/app/models/entities.py:94-123` |
| F-10 | **[Fact]** `Intervention` records link to `enrollment_id` with status and timestamps, but **not** to a prediction or model version. | `backend/app/models/entities.py:240-256` |
| F-11 | **[Fact]** The docs disclose the refit and state that scores are not calibrated. | `docs/model-evaluation.md:9`, `docs/ml-pipeline.md:21`, `docs/responsible-ai.md:7`, `docs/api-documentation.md:97` |
| F-12 | **[Fact]** OULAD has four presentations. Module coverage per presentation is uneven: CCC is absent from 2013B/2013J, AAA is absent from 2014B, and 2013B holds only BBB/DDD/FFF. 578 rows belong to students with more than one module in the same presentation. | DESIGN §2.2 (read-only dataset query) |
| F-13 | **[Fact]** 2014J has been inspected repeatedly. All three models' test results are recorded and discussed, reports were regenerated after an earlier audit, and A1 added a descriptive test-calibration look. | `data/processed/supervised_evaluation.json` `test_results`; `docs/model-evaluation.md`; `docs/ml-pipeline.md`; A1 §4.4 |
| F-14 | **[Prior]** Train-only model on 2014B (out-of-sample): AUC 0.801, Brier 0.179, log loss 0.532, flag rate 85.2% at the current threshold. The saved model on 2014B (in-sample) shows AUC 0.848. On 2014J the saved model's mean score is 0.468 against observed prevalence 0.357 (ECE 0.111). | A2 `results.json`; A1 `results.json` |
| F-15 | **[Fact]** Existing tests check class order, score range, metric reproduction, and the feature contract. **No** test covers threshold provenance, calibration, or score semantics. | `tests/test_canonical_integrity.py`, `tests/test_inference.py`, `backend/tests/test_ml_endpoints.py` |

**[Open] Ambiguities.**
- No repository file defines coordinator review capacity, the relative costs of false negatives and false positives, or a required recall.
- No file states whether any consumer needs probability semantics.
- The deploying institution's future data feed, label timing, and presentation codes are not documented.

---

## 3. Staged implementation plan

Every stage requires written approval before the next begins (§8). No stage modifies the deployed artifact, registry, live inference, or databases unless that stage says so explicitly **and** its approval names that change.

### Stage 0: Baseline and artifact inventory

| | |
|---|---|
| **Purpose** | Record an immutable snapshot of the current system, so every later result can be compared against it and the system can be rolled back. |
| **Prerequisites** | Approval to begin. Read-only access to the repository. |
| **Proposed actions** | 1. Hash every artifact in `ml/saved_models/`, plus `registry.json`, `data/processed/*` (including `student_training_dataset.csv`, `supervised_evaluation.json`, `source_manifest.json`), and the raw OULAD files.<br>2. Record the current threshold (exact float and source), feature contract and order (`FEATURES`), `PREDICTION_DAY`, class order, library versions, and band strings.<br>3. Record the score semantics as **"uncalibrated ranking score; threshold validated on a different (train-only) model"**.<br>4. Record the inference path (F-6), persistence fields (F-7), and frontend dependencies (F-8).<br>5. Index the report paths (A1, A2, DESIGN, this plan).<br>6. Re-run only the existing read-only reproduction tests, and record the outcome as observed. |
| **Deliverables** | `reports/<new>/BASELINE_INVENTORY.md` + `baseline_hashes.sha256` + test log |
| **Acceptance criteria** | Hashes and recorded values reproduce on a second independent run. Test outcomes are recorded as observed, not assumed. |
| **Risks and mitigations** | Accidental writes (mitigate with a hash check before and after, and `PYTHONDONTWRITEBYTECODE`). Drift between inventory and live DB rows: DB contents are out of scope unless separately approved, and a read-only DB query needs its own approval. |
| **Approval before proceeding** | Project owner accepts the inventory as the rollback baseline. |

### Stage 1: Evaluation protocol (pre-registration)

| | |
|---|---|
| **Purpose** | Fix data roles, leakage controls, metrics, and analysis code **before** any result is seen. |
| **Prerequisites** | Stage 0 approved. The Stage 7 decisions D1–D3 and D5 are at least provisionally answered, because the threshold objective must exist before any search. |
| **Proposed actions** | 1. Adopt the data roles in §4.<br>2. Specify the grouping (`id_student`) and stratification (`code_module`) rules.<br>3. Fix the metric definitions (§5), bin edges, bootstrap method, seeds, and candidate threshold grid.<br>4. Document module and presentation limitations: CCC is unseen by a train-only model, AAA is absent from 2014B, there is a single presentation per role, and prevalence differs by presentation.<br>5. Write the "freeze then hash" rule: no 2014J labels are read until all candidate components and the analysis code are hashed.<br>6. Specify reproducibility requirements: pinned environment (the existing `.venv` versions), fixed seeds, deterministic output, and an output directory isolated under `reports/`. |
| **Deliverables** | `PREREGISTRATION.md`, signed |
| **Acceptance criteria** | Every data role, metric, grid, and go/no-go placeholder is defined. A reviewer can reproduce the role assignment from the document alone. |
| **Risks and mitigations** | Pre-registration written after peeking (mitigate by timestamping and hashing the document before Stage 2). Objective not yet decided (block Stage 3 until it is). |
| **Approval before proceeding** | Owner and ML reviewer sign the pre-registration. |

### Stage 2: Calibration evaluation

| | |
|---|---|
| **Purpose** | Decide **whether** calibration is needed and, only if so, which candidate method is justified. |
| **Prerequisites** | Stage 1 signed. D3 answered (are probabilities needed?). If D3 = "not needed", Stage 2 shrinks to a descriptive report of raw-score reliability, and no calibrator is fitted. |
| **Proposed actions** | 1. Fit the train-only model M (current `model_specs` xgboost, unchanged) on train, as an isolated new artifact outside `ml/saved_models/`.<br>2. Score 2014B and report raw-score Brier, log loss, calibration-in-the-large, slope, a fixed-bin reliability table and diagram (10 equal-width and 10 equal-count bins, Wilson CIs), and ECE with both binning schemes.<br>3. Report per-module tables. AAA has no 2014B rows, so it is marked "not assessable".<br>4. **Only if** raw miscalibration exceeds the pre-registered tolerance [DECISION] **and** D3 requires probabilities: compare Platt and isotonic **within 2014B by repeated StratifiedGroupKFold (group = `id_student`)**. Each calibrator is fitted on K−1 folds and assessed only on the held-out fold; the out-of-fold predictions are pooled.<br>5. Apply the pre-registered selection rule, with Platt as default unless isotonic beats it by a pre-set margin [DECISION].<br>6. Fit the final calibrator on all of 2014B. **Its performance is never reported on 2014B**; the out-of-fold estimate stands in for it. |
| **Deliverables** | `CALIBRATION_REPORT.md`, reliability tables and diagrams, frozen calibrator candidate (isolated path), hashes |
| **Acceptance criteria** | No observation is used both to fit and to assess the same calibrator. Student-grouped folds are verified (no `id_student` in two folds). Bootstrap CIs are cluster-resampled by student. Limitations stated: one presentation, isotonic small-sample risk, and the prevalence shift between presentations. |
| **Risks and mitigations** | Isotonic over-fitting on about 5.6k rows (prefer Platt). Calibration that does not transfer across cohorts (A1: calibration-in-the-large −0.22 → −0.71 logit); plan Stage 6 monitoring and intercept recalibration. Unseen CCC (report separately). |
| **Approval before proceeding** | ML reviewer accepts the calibration decision, which may be "no calibrator". |

### Stage 3: Threshold and alert-capacity evaluation

| | |
|---|---|
| **Purpose** | Choose a threshold **rule** that reflects stakeholder priorities, and estimate its consequences. The current threshold is **not** assumed to be optimal. |
| **Prerequisites** | Stage 2 approved. D1 (capacity / false-positive burden) and D2 (recall / missed-risk cost) answered. If F-beta is used, β is justified in writing. |
| **Proposed actions** | 1. Encode the approved objective as one of:<br>&nbsp;&nbsp;• maximise recall subject to flag rate ≤ C<br>&nbsp;&nbsp;• highest threshold with recall ≥ R<br>&nbsp;&nbsp;• minimise c_FN·FN + c_FP·FP (on calibrated scores, cutoff c_FP/(c_FP+c_FN))<br>&nbsp;&nbsp;• F-beta with an approved β<br>2. Search the pre-registered grid on **2014B out-of-fold** (calibrated, if Stage 2 produced a calibrator) scores, using nested cross-fitting to estimate performance at the chosen threshold.<br>3. Report, for the selected threshold, the current 0.18982425 (re-evaluated on M, for reference only), and stakeholder scenario values: precision, recall, F1, F2, specificity, FPR, FNR, TN/FP/FN/TP, flagged count and rate, alerts per true positive, and per-module flag rate and recall, with cluster-bootstrap CIs.<br>4. Store the threshold on the raw-score scale of M and its calibrated equivalent. |
| **Deliverables** | `THRESHOLD_REPORT.md`, scenario table, frozen threshold record with rule, source-model hash, and out-of-fold flag rate |
| **Acceptance criteria** | The objective was signed before the search. The threshold is derived only from 2014B. Its stated source-model hash equals M's hash. No threshold is called "optimal" without naming the objective. |
| **Risks and mitigations** | A flat F2 surface makes the threshold unstable (A1: 95% bootstrap CI 0.138–0.207 under F2); report a stability interval. Capacity measured per cohort but applied per week: the time unit of C must be specified [DECISION]. |
| **Approval before proceeding** | Owner and coordinator lead approve the rule and the observed trade-off. **This does not approve deployment.** |

### Stage 4: Matched model + calibrator + threshold

| | |
|---|---|
| **Purpose** | Assemble a candidate whose components were validated on the same score-generating model, and evaluate it once on 2014J. |
| **Prerequisites** | Stages 2–3 approved. D4 (versioning) and D6 (status of 2014J) answered. |
| **Proposed actions** | 1. Compare the options in the table below and record the chosen option.<br>2. Freeze and hash M, the calibrator, the threshold record, and the evaluation code.<br>3. Evaluate **once** on 2014J using pre-registered metrics only. Label the results **exploratory** (F-13).<br>4. If any result prompts a change, 2014J is declared spent, and the change must be validated in Stage 6.<br>5. Run cross-fitting sensitivity analyses: forward-chaining (2013B→2013J, 2013B+2013J→2014B) and leave-one-presentation-out (labelled non-chronological), to estimate between-presentation variability and refit sensitivity. |
| **Deliverables** | `MATCHED_CANDIDATE_REPORT.md`, frozen bundle (isolated path, new version identifier), sensitivity report |
| **Acceptance criteria** | Bundle hashes recorded before 2014J labels are read. The threshold source hash equals the model hash. Calibrator fit-data ID = 2014B. 2014J results are reported with their exploratory status. |
| **Risks and mitigations** | See the options table. |
| **Approval before proceeding** | Owner decides whether the candidate may enter Stage 6 shadow evaluation. **No production swap.** |

**Options compared (Stage 4)**

| Option | What it means | Benefits | Risks |
|---|---|---|---|
| **K: keep the current refit model** | Calibrate and threshold the existing `xgboost.joblib` | No model change; it has seen CCC and 2014B | **No eligible independent labels remain.** Its only unseen labelled data is 2014J, and fitting a calibrator or threshold there would remove the last historical check. The only defensible route is prospective data (Stage 6). Not feasible retrospectively without re-designating 2014J [DECISION D6]. |
| **A′: train-only model, no refit** (recommended retrospective candidate) | M fitted on 2013B+2013J; calibrator and threshold from 2014B | Genuinely matched; chronological; reproducible (A1 reproduced the stage-1 model bit-for-bit) | Fewer training rows (11.4k vs 17.1k). CCC is an unseen module (about 13–16% of later cohorts). Single calibration presentation. |
| **R: retrain on more data** | Refit on train + 2014B (or more) | More data; sees CCC | Needs **new** calibration and threshold evidence. No independent historical data remains to provide it, so it depends on Stage 6. |
| **X: cross-fitting** | Out-of-fold scores across presentations | Variability estimates | Fold models differ from any final model. Leave-one-presentation-out breaks chronology. **Sensitivity only.** |
| **P: prospective** | Frozen bundle scored on a future cohort | Strongest evidence, from the real population | Needs prerequisites the project does not currently meet (Stage 6). |

**Why calibrators and thresholds do not survive a refit** [Fact + Prior]:
- A calibrator is a map from one model's score distribution to observed frequencies.
- A threshold is a cut point on that same distribution.
- Refitting changes the distribution, because it changes tree structure, the data seen, which categories are known (for example, CCC and 2014B become "seen"), and the class-weight context.
- The same student can then receive a different score, so both the map and the cut point no longer apply.
- A1 measured this. Reusing a threshold after refit changed flag rates by −2.4 to +7 pp in validation simulations. On 2014J features, the stage-1 model and the refit model flag 77.9% and 80.3% respectively at the same cutoff (Spearman 0.965).

### Stage 5: Testing and regression protection (proposed tests; none executed)

| | |
|---|---|
| **Purpose** | Prevent silent re-occurrence of the issues above, and protect existing app behaviour. |
| **Prerequisites** | Stage 4 option chosen. Approval to add **new** test files; existing tests stay untouched unless separately approved. |
| **Proposed actions** | Add the tests listed below, run them in CI against isolated fixtures, and record their results. |
| **Deliverables** | New test modules plus a CI run log |
| **Acceptance criteria** | All new and existing tests pass on the frozen candidate **and** on the current baseline. Frontend band strings are unchanged. |
| **Risks and mitigations** | Tests coupled to OULAD data (use fixtures plus a skip-if-absent pattern, as existing tests do). False confidence: tests prove consistency, not validity. |
| **Approval before proceeding** | Code review approval. |

**Proposed tests**

| Area | Test |
|---|---|
| Prediction API compatibility | `PredictionRead` and `LatestPredictionSummary` fields are unchanged. `priority_band` ∈ {`review_for_support`, `no_flag_from_model`}. Response shape is the same with or without a calibrator. Persisted `Prediction` rows satisfy the score and threshold CHECKs. |
| Score range and class ordering | `classes_ == [0, 1]`; the score is column 1; scores lie in [0, 1]; scores are monotone under the calibrator (Platt). |
| Calibrator/model compatibility | The bundle's `calibrator.source_model_sha256` equals the model artifact hash. Feature version matches. Loading a mismatched pair raises an error. |
| Threshold provenance and configuration | `threshold.source_model_sha256 == model_artifact_sha256`. The selection rule and approval reference are present. The threshold scale is declared (raw or calibrated). Inference uses the bundle's threshold, not a hard-coded value. |
| Missing or malformed inputs | Existing `validate_features` behaviour is preserved: nulls allowed where they are today; out-of-range, non-integer, and missing or extra keys rejected. Unseen module or presentation categories are scored and also **logged**. |
| Regression of app behaviour | Existing `tests/` and `backend/tests/` suites pass. The coordinator overview counts by band are computed identically for the baseline artifact. |
| Reproducibility and versioning | Re-running the evaluation harness from frozen inputs reproduces the hashed results. The registry entry carries the §5 metadata. The rollback version resolves to a loadable artifact. |

### Stage 6: Shadow evaluation and monitoring

| | |
|---|---|
| **Purpose** | Obtain **prospective** evidence on a future cohort without changing student-facing decisions. |
| **Prerequisites (NOT currently met)** | **P6-a.** A source of future-cohort data with features computed to the `oulad-early-risk-v2` contract. Its existence and access are unconfirmed [Open].<br>**P6-b.** Collection of end-of-course outcomes per enrollment. No such field exists (F-9), so a schema change and migration would need separate approval.<br>**P6-c.** Intervention records linked to the prediction and model version that preceded them. Today they link only to the enrollment (F-10).<br>**P6-d.** Storage for shadow scores that is **not** shown to users. Today predictions are persisted and displayed (F-7, F-8).<br>**P6-e.** Data-protection and ethics review for outcome and intervention linkage.<br>**P6-f.** Named owners and a review cadence [DECISION D8]. |
| **Proposed actions** | 1. Run the frozen candidate bundle in shadow mode beside the current production path. Users continue to see only the current output.<br>2. Log shadow scores, the shadow band, and bundle version.<br>3. Collect outcomes at course end, and log interventions with their link to the prediction.<br>4. Analyse once, at cohort end, under the pre-registered plan. Interpret intervention-affected outcomes separately: support may change outcomes and bias recall and calibration downward.<br>5. Monitor throughout the cohort: score distribution shift (quantiles, PSI/KS against 2014B), shadow vs production alert rate, input missingness and unseen categories, and per-module and per-presentation breakdowns. After labels arrive, also monitor prevalence, calibration-in-the-large and slope, reliability, Brier, log loss, AUC, and recall and precision at the frozen threshold.<br>6. Subgroups are limited to `code_module` and presentation. Sensitive-attribute analyses are excluded unless separately justified and approved. |
| **Deliverables** | `SHADOW_PROTOCOL.md`, monitoring definitions, end-of-cohort report |
| **Acceptance criteria** | Bundle unchanged throughout the cohort (hash checked). Analysis follows the pre-registration. All §8 Gate G6 metrics are reported against [DECISION] values. |
| **Risks and mitigations** | Label lag of a full presentation. Intervention confounding (log it; consider shadow-only for the first cohort). The live population differs from OULAD. Rollback criteria are defined in advance: any breach of the [DECISION] alert-rate or calibration bounds, or a contract violation rate above [DECISION], halts shadow promotion. Production is unaffected, because shadow never drives alerts. |
| **Approval before proceeding** | Owner, data-protection or ethics reviewer, and coordinator lead approve P6-a to P6-f. Each schema change is approved separately. |

### Stage 7: Approval and go/no-go gate

| | |
|---|---|
| **Purpose** | Authorise, or refuse, any change to production scoring or alerting. |
| **Prerequisites** | Stage 6 end-of-cohort report. All decisions D1–D8 recorded. |
| **Proposed actions** | Review the evidence against the pre-registered criteria. Decide go, no-go, or extend shadow. If go, a separately approved change persists the bundle as a new version with rollback (§5 metadata), updates inference to read the bundle's calibrator and threshold, and updates the docs. |
| **Deliverables** | Signed go/no-go record |
| **Acceptance criteria** | Every criterion in §8 G7 is met, or an exception is explicitly signed. |
| **Risks and mitigations** | Pressure to go on historical evidence alone. Mitigation: historical evidence (2014B/2014J) is classed as **necessary but not sufficient**. |
| **Approval before proceeding** | Project owner, with coordinator lead and ML reviewer. Rollback authority is named [DECISION D8]. |

---

## 4. Data-splitting and leakage-prevention protocol [Rec]

| Role | Data | Rows (after forward purge) | Independent of | Notes |
|---|---|---|---|---|
| **Training** | 2013B + 2013J | 11,439 | — | Preprocessing fitted inside the pipeline on these rows only (`make_preprocessor`) |
| **Calibration** | 2014B | 5,634 | Training (students purged) | Calibrator fit and assessment are cross-fitted **within** 2014B by `id_student` |
| **Threshold selection** | 2014B (same rows as calibration) | 5,634 | Training | **Not independent of calibration.** Uses out-of-fold calibrated scores with nested selection, so no row both chooses and evaluates the threshold within a fold. Shared-presentation dependence remains and is disclosed. |
| **Final retrospective evaluation** | 2014J | 7,626 | Training, calibration, threshold (students purged) | **Exploratory**: repeatedly viewed (F-13). Single use under pre-registration. |
| **Prospective evaluation** | Future institutional cohort | Unknown [Open] | Everything above | The only evidence admissible as genuinely unseen. Prerequisites P6-a to P6-f. |

**Leakage controls**
1. Forward student purge across roles, as in the existing `_student_disjoint_presentation_split`.
2. `StratifiedGroupKFold` with group = `id_student` inside 2014B, which handles the 578 rows from multi-module students.
3. Every fitted transform (imputer, scaler, encoder, calibrator) sits inside the fold.
4. Hash and freeze before 2014J labels are read.
5. No hyperparameter or model-family change. If one is ever wanted, it needs a new protocol and new data roles.
6. No refit after validation unless new calibration and threshold evidence is obtained (Stage 4 option R).
7. Cross-fitting results never feed the deployed threshold.

**Stated limitations**
- One presentation per role.
- B and J presentations differ in prevalence: 2014B 46.0% vs 2014J 38.0% before purge.
- CCC is unseen by a train-only model.
- AAA cannot be assessed on 2014B.
- No between-presentation variance estimate exists except from sensitivity analyses.

---

## 5. Metrics and intended interpretation

| Metric | Answers | Interpretation and caveats |
|---|---|---|
| ROC-AUC | Ranking: do positives score higher? | Unchanged by monotone calibration. Says nothing about probability accuracy or the threshold. |
| Brier score (+ prevalence reference, skill) | Overall probability accuracy | Mixes calibration and discrimination. Always compare with the prevalence-only reference. |
| Log loss (+ reference) | Probability accuracy, penalising confident errors | Sensitive to extreme scores. Clip and report the clipping. |
| Calibration-in-the-large | Average over- or under-prediction | Most sensitive to prevalence shift between cohorts |
| Calibration slope / intercept | Over- or under-confidence | Slope below 1 means scores are too extreme |
| Reliability table and diagram (fixed bins, Wilson CIs) | Where in the score range calibration fails | Fixed edges allow cohort comparison. Flag bins under the minimum n [DECISION]. |
| ECE (equal-width and equal-count) | Single-number calibration summary | Biased and binning-dependent. Never the sole criterion. |
| Precision, recall, F1, F2, specificity, FPR, FNR, TN/FP/FN/TP | Consequences at a threshold | Recall = share of at-risk students flagged. FNR = share missed. FPR = share of not-at-risk students alerted. |
| Flagged count, flag rate, alerts per true positive | Coordinator workload | Compare with approved capacity C (D1) |
| Per-module metrics | Heterogeneity | Descriptive. Small n. AAA is missing in 2014B. |
| Uncertainty | — | Cluster bootstrap by `id_student`, stratified by module. Between-presentation uncertainty cannot be estimated from a single presentation. |
| Metadata required with each version | — | Training-data fingerprint and range, feature contract and preprocessing versions, artifact hash, calibrator method/version/fit-data ID, threshold value, scale, rule and source-model hash, calibration/threshold dataset IDs, final-holdout reference and its history, approval date, rollback version |

---

## 6. Risks, limitations, and unresolved questions

| # | Item | Type |
|---|---|---|
| R1 | Calibration may not transfer across presentations (A1 calibration-in-the-large −0.22 → −0.71 logit). Any calibrator is cohort-specific until shown otherwise. | Limitation |
| R2 | Option A′ trades training data and CCC coverage for a matched pair. | Trade-off ([DECISION] D4) |
| R3 | The current refit model cannot be validly calibrated or re-thresholded from historical data without spending 2014J. | Limitation |
| R4 | 2014J is not pristine. Its results are exploratory. | Limitation |
| R5 | Intervention effects bias prospective outcome metrics. | Risk; mitigate by logging and shadow mode |
| R6 | Outcome collection and prediction-linked intervention logging do not exist (F-9, F-10). | Unmet prerequisite |
| R7 | The live population differs from OULAD, and `code_presentation` is always an unseen category at scoring time (A1 F5). | Risk; feature-contract change would need separate approval [Open] |
| R8 | No capacity, cost, or recall requirement is documented. | [Open] → D1, D2 |
| R9 | Database contents were not inspected for this plan. Live prediction volumes and current alert rates are unknown. | [Open] |
| R10 | Whether a future institutional cohort exists, its timing, and its label definition. | [Open] → D7 |
| A1-asm | [Assumption] Live features are computed per `backend/app/services/feature_assembly.py` and equal the training contract. This needs verification in Stage 6. | Assumption |

---

## 7. Stage-by-stage deliverables and completion criteria

| Stage | Deliverables | Done when |
|---|---|---|
| 0 | Baseline inventory, hashes, test log | Reproducible inventory accepted as rollback baseline |
| 1 | Signed pre-registration | All roles, metrics, grids, and placeholders defined and hashed |
| 2 | Calibration report (possibly "no calibrator needed"), isolated calibrator candidate | Out-of-fold assessment only; grouped folds verified; reviewer accepts |
| 3 | Threshold report, scenario table, frozen threshold record | Objective signed first; threshold from 2014B only; provenance hash matches |
| 4 | Matched bundle, single exploratory 2014J report, sensitivity report | Frozen before 2014J; results labelled exploratory |
| 5 | New tests, CI log | All tests pass on baseline and candidate; API and band strings unchanged |
| 6 | Shadow protocol, monitoring definitions, end-of-cohort report | Prerequisites P6-a to P6-f met; frozen bundle; pre-registered analysis complete |
| 7 | Signed go/no-go record | Criteria in G7 met, or a signed exception |

---

## 8. Approval gates

| Gate | Before | Approvers [DECISION: named roles] | Evidence required |
|---|---|---|---|
| G0 | Stage 1 | Project owner | Baseline inventory |
| G1 | Stage 2 | Owner + ML reviewer | Signed pre-registration; D1–D3, D5 at least provisional |
| G2 | Stage 3 | ML reviewer | Calibration report |
| G3 | Stage 4 | Owner + coordinator lead | Threshold report with scenario trade-offs |
| G4 | Stage 5 | Owner | Matched candidate report; 2014J exploratory results |
| G5 | Stage 6 | Code reviewer | Test suite results |
| G6 | Shadow start | Owner + data-protection/ethics + coordinator lead | P6-a to P6-f satisfied; schema changes separately approved |
| G7 | Any production change | Owner + coordinator lead + ML reviewer | Prospective report meeting all criteria |

**Stakeholder decisions (no values assumed)**

| ID | Decision |
|---|---|
| D1 | Alert-review capacity C (per cohort and/or per week) and acceptable false-positive burden |
| D2 | Desired minimum recall R and/or the relative cost of a missed at-risk student vs an unnecessary alert. If F-beta is used, the justification for β. |
| D3 | Whether calibrated probabilities are required by any consumer (UI, API, analytics) or ranking suffices |
| D4 | Versioning scheme for model + calibrator + threshold bundles; A′ (no refit) vs refit; rollback version |
| D5 | Minimum acceptable metrics: calibration tolerances (calibration-in-the-large, slope, ECE, Brier skill), AUC lower bound, alert-rate bound, recall and precision floors, minimum reliability-bin n, isotonic-vs-Platt margin |
| D6 | Whether 2014J evidence is exploratory only, which is recommended (versus being re-designated) |
| D7 | Access to an independent future cohort: source, timing, label definition, data agreement |
| D8 | Monitoring ownership, review cadence, drift thresholds, rollback authority |

---

## 9. Not Implemented

None of the following was done in this task:

| Area | Not performed |
|---|---|
| **Code** | No changes to `ml/supervised/train.py`, `ml/inference/prediction_service.py`, `backend/app/**`, `frontend/**`, scripts, or tests. No new source or test files were created. |
| **Models** | No training, retraining, refitting, or cross-fitting. No model artifact created, modified, or deleted. `ml/saved_models/*` and `registry.json` are untouched. |
| **Calibration** | No calibrator fitted, selected, or evaluated in this task |
| **Threshold** | No threshold selected or changed. 0.18982425 remains in the artifact. No new threshold is recommended. |
| **Data** | No changes to raw OULAD files, `data/processed/*`, manifests, or templates |
| **Database** | No connection to any database (port 5432 or 5433). No queries, migrations, imports, or writes. |
| **Configuration** | `.env`, `.env.example`, `docker-compose.yml`, and dependency files unchanged. No packages installed. |
| **Deployment** | No change to live prediction, alert logic, priority bands, UI, or API. No shadow mode started. |
| **Reports** | No existing report modified or overwritten. Only this file was created. |
| **Evaluation** | No tests executed for this plan. The only computation was a read-only load of `xgboost.joblib`, `registry.json`, and `supervised_evaluation.json` to verify F-4 and F-5. No data partition was scored. |
