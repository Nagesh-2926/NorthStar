# Feature contract — `oulad-early-risk-v2`

One inference/training row represents a student in a specific module presentation. Prediction cutoff is relative course day 56 (days 0–55 observed). IDs are join keys only and are never predictors. All transformations are implemented in `ml/features/build_dataset.py`; fitted imputation, encoding, and scaling live inside serialized training pipelines.

| Feature | Source columns | Transformation / type | Expected range | Missing handling | Models |
|---|---|---|---|---|---|
| `registration_day` | studentRegistration.`date_registration` | Relative registration day, numeric; dates on/after prediction cutoff are censored to missing | OULAD observed -322–49 after cutoff | Median imputer fitted on training fold, with missing indicator | Supervised |
| `num_of_prev_attempts` | studentInfo.`num_of_prev_attempts` | Numeric count | 0–6 observed | Training-fold median imputation | Supervised |
| `studied_credits` | studentInfo.`studied_credits` | Numeric credit load | 30–655 observed | Training-fold median imputation | Supervised |
| `early_assessment_mean` | studentAssessment.`score`, `date_submitted`; assessments.`date` | Mean valid score for assessment scheduled and submitted during days 0–55; numeric score points | 0–100 | Missing retained; median + missing indicator fitted on training only | Supervised, clustering |
| `early_assessment_count` | Same assessment columns | Count of nonmissing early scores | 0–4 observed | Zero when no observed early score | Supervised, clustering |
| `early_on_time_rate` | studentAssessment.`date_submitted`; assessments.`date` | Fraction of scored early assessments submitted on/before due day | 0–1 | Missing if no scored early assessment; training-fold imputation | Supervised, clustering |
| `early_assessment_coverage` | assessments.`date`; studentAssessment IDs | Number of valid early scores / number of assessments scheduled by day 56 for that module presentation | 0–1 | Zero when assessments are scheduled but no valid score is observed; missing only when no assessment is scheduled; training-fold imputation | Supervised, clustering |
| `early_vle_clicks` | studentVle.`date`, `sum_click` | Sum of recorded clicks on days 0–55 | 0–9,481 observed | Zero when no activity record | Supervised, clustering |
| `early_vle_active_days` | studentVle.`date` | Count distinct active course-relative days, 0–55 | 0–56 | Zero when no activity record | Supervised, clustering |
| `early_vle_active_weeks` | studentVle.`date`, `sum_click` | Count of the eight weeks with at least one recorded click | 0–8 | Zero when no activity record | Supervised, clustering |
| `early_vle_active_sites` | studentVle.`id_site` | Distinct sites used before cutoff | 0–267 observed | Zero when no activity record | Supervised, clustering |
| `early_vle_activity_types` | studentVle site + vle.`activity_type` | Distinct mapped VLE activity types observed before cutoff | 0–14 observed | Zero when no activity record | Supervised, clustering |
| `code_module` | studentInfo.`code_module` | Categorical course/module code | Observed AAA–GGG | Most-frequent imputation; unknown categories ignored by fitted encoder | Supervised |
| `code_presentation` | studentInfo.`code_presentation` | Categorical presentation code | Observed 2013B/2013J/2014B/2014J | Most-frequent imputation; unknown categories ignored by fitted encoder | Supervised |

## Backend inference source mapping

The production API does not accept a client feature vector. It assembles this same ordered contract from persisted enrollment context: enrollment fields map to registration/prior-attempt/credit inputs; the enrollment's assessment schedule and unique `assessment_score` records provide the assessment statistics; weekly engagement records provide click totals, active-day totals, active weeks, and distinct site/activity-type counts. Assessment scores count only when the scheduled day and submitted day are both 0-55. On-time rate compares submitted day with scheduled day. Assessment coverage divides eligible scores by schedule entries due in that window; with a nonempty schedule and no eligible scores the value is `0`, and with no scheduled assessment it is missing. Weeks 0-7 provide the ordered LSTM sequence. Missing values follow this file's table and the saved training preprocessors.

Version 2 corrects a parity defect in version 1: training previously left coverage missing for learners with no scored early submission even when early assessments were scheduled, while inference correctly produced zero. Supervised, clustering, and final-exam score models are retrained against version 2. The weekly sequence inputs and existing LSTM artifact are unchanged; the sequence model keeps its independent `oulad-weekly-sequence-v1` contract (legacy artifact tag `oulad-early-risk-v1` is accepted for compatibility).

## Target and leakage boundary

`early_support_label=1` for final `Fail` or a `Withdrawn` outcome dated on/after day 56; `0` for `Pass` or `Distinction`. A `Withdrawn` row with `date_unregistration` before day 56, or with no recorded unregistration day, is excluded from the forecast cohort because its outcome is already known or its timing cannot be established at the prediction boundary. This source field is used only for eligibility and never enters the feature vector. Inputs are censored to course days 0–55. Assessment schedule/score records are included only when both assessment date and submission date are nonnegative and before day 56; VLE data uses the same day boundary. The same ordered `FEATURES` constant is used by training and inference.

The chronological evaluation also purges repeated `id_student` values from later partitions: training uses 2013B/2013J; 2014B rows for students in training are removed; 2014J rows for students in training or retained validation are removed. This keeps student identities disjoint across training, validation, and test without using the identifier as a predictor.
