"""Build leak-aware course-level features from the untouched OULAD source files."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pandas as pd

PREDICTION_DAY = 56
FEATURE_VERSION = "oulad-early-risk-v2"
KEYS = ["code_module", "code_presentation", "id_student"]
NUMERIC_FEATURES = [
    "registration_day", "num_of_prev_attempts", "studied_credits",
    "early_assessment_mean", "early_assessment_count", "early_on_time_rate",
    "early_assessment_coverage", "early_vle_clicks", "early_vle_active_days",
    "early_vle_active_weeks", "early_vle_active_sites", "early_vle_activity_types",
]
CATEGORICAL_FEATURES = ["code_module", "code_presentation"]
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES
TARGET = "early_support_label"


def _read(root: Path, name: str) -> pd.DataFrame:
    path = root / name
    if not path.is_file():
        raise FileNotFoundError(f"Required OULAD file not found: {path}")
    return pd.read_csv(path)


def historical_source_record_id(code_module: str, code_presentation: str, id_student: object) -> str:
    """Stable OULAD course-record key, namespaced away from live enrollment IDs."""
    identity = json.dumps(
        ["OULAD", 1, str(code_module), str(code_presentation), str(int(id_student))],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return "oulad:student-course:v1:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()


def build_student_features(raw_dir: str | Path, prediction_day: int = PREDICTION_DAY,
                           chunk_size: int = 500_000) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return one row per student-course, plus weekly engagement sequences.

    Labels use final_result. Inputs are restricted to registration metadata known by course
    start, assessment submissions no later than both day cutoff and scheduled due date, and
    VLE activity dated before the cutoff. Sensitive demographic attributes are excluded.
    """
    if prediction_day != PREDICTION_DAY:
        raise ValueError(f"Feature contract {FEATURE_VERSION} requires prediction_day={PREDICTION_DAY}")
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    raw = Path(raw_dir)
    info = _read(raw, "studentInfo.csv")
    info["id_student"] = info["id_student"].astype("int64")
    if info.duplicated(KEYS).any():
        raise ValueError("studentInfo.csv contains duplicate student-course identities")
    source_key_index = pd.MultiIndex.from_frame(info[KEYS])
    base = info[KEYS + ["final_result", "num_of_prev_attempts", "studied_credits"]].copy()
    base[TARGET] = base["final_result"].isin(["Fail", "Withdrawn"]).astype("int8")
    base["_withdrawn_result"] = base["final_result"].eq("Withdrawn")
    base = base.drop(columns="final_result")

    reg = _read(raw, "studentRegistration.csv")
    reg["id_student"] = reg["id_student"].astype("int64")
    if reg.duplicated(KEYS).any():
        raise ValueError("studentRegistration.csv contains duplicate student-course identities")
    registration_key_index = pd.MultiIndex.from_frame(reg[KEYS])
    if not source_key_index.isin(registration_key_index).all():
        raise ValueError("studentInfo.csv contains a student-course identity absent from studentRegistration.csv")
    # A withdrawal before the prediction boundary is already known at scoring time, not
    # a future outcome. Unknown withdrawal timing is excluded conservatively. The field
    # is used only for cohort eligibility and is never a model feature.
    base = base.merge(reg[KEYS + ["date_registration", "date_unregistration"]],
                      on=KEYS, how="left", validate="one_to_one")
    withdrawn = base["_withdrawn_result"]
    early_withdrawal = withdrawn & base["date_unregistration"].notna() & (base["date_unregistration"] < prediction_day)
    unknown_withdrawal_timing = withdrawn & base["date_unregistration"].isna()
    exclusion_counts = {
        "source_rows": int(len(base)),
        "excluded_withdrawn_before_prediction_day": int(early_withdrawal.sum()),
        "excluded_withdrawn_unknown_timing": int(unknown_withdrawal_timing.sum()),
    }
    base = base.loc[~(early_withdrawal | unknown_withdrawal_timing)].copy()
    base["registration_day"] = base["date_registration"].where(base["date_registration"] < prediction_day)
    base = base.drop(columns=["date_registration", "date_unregistration", "_withdrawn_result"])

    assessments = _read(raw, "assessments.csv")
    if assessments["id_assessment"].duplicated().any():
        raise ValueError("assessments.csv contains duplicate id_assessment values")
    courses = _read(raw, "courses.csv")
    if courses.duplicated(KEYS[:2]).any():
        raise ValueError("courses.csv contains duplicate module-presentation identities")
    assessments = assessments.merge(courses, on=["code_module", "code_presentation"],
                                    how="left", validate="many_to_one", indicator=True)
    if assessments["_merge"].ne("both").any():
        raise ValueError("assessments.csv contains a module-presentation key absent from courses.csv")
    assessments = assessments.drop(columns="_merge")
    early_sched = assessments[assessments["date"].notna() & (assessments["date"] >= 0) &
                              (assessments["date"] < prediction_day)]
    scheduled = early_sched.groupby(["code_module", "code_presentation"]).size().rename("_scheduled")

    sa = _read(raw, "studentAssessment.csv")
    sa["id_student"] = sa["id_student"].astype("int64")
    sa = sa.merge(assessments[KEYS[:2] + ["id_assessment", "date"]], on="id_assessment", how="left",
                  validate="many_to_one", indicator=True)
    if sa["_merge"].ne("both").any():
        raise ValueError("studentAssessment.csv contains an id_assessment absent from assessments.csv")
    sa = sa.drop(columns="_merge")
    if not pd.MultiIndex.from_frame(sa[KEYS]).isin(source_key_index).all():
        raise ValueError("studentAssessment.csv contains a student-course key absent from studentInfo.csv")
    sa = sa[(sa["date"].notna()) & (sa["date"] >= 0) & (sa["date"] < prediction_day) &
            (sa["date_submitted"] >= 0) & (sa["date_submitted"] < prediction_day) & sa["score"].notna()]
    sa["_on_time"] = (sa["date_submitted"] <= sa["date"]).astype("float32")
    assess = sa.groupby(KEYS).agg(early_assessment_mean=("score", "mean"),
        early_assessment_count=("score", "count"), early_on_time_rate=("_on_time", "mean")).reset_index()
    base = base.merge(assess, on=KEYS, how="left", validate="one_to_one")
    base = base.merge(scheduled.reset_index(), on=KEYS[:2], how="left", validate="many_to_one")
    # No scored submissions means zero covered assessments when assessments were
    # scheduled. Coverage is missing only when the presentation has no early schedule.
    base["early_assessment_count"] = base["early_assessment_count"].fillna(0)
    base["early_assessment_coverage"] = (base["early_assessment_count"] / base["_scheduled"].replace(0, pd.NA))
    base = base.drop(columns="_scheduled")

    # Stream the 454 MB log instead of loading it all into memory. Per-day records sum
    # clicks; date is relative to the presentation start (OULAD convention).
    totals: dict[tuple, list] = {}
    weekly: dict[tuple, dict] = {}
    site_types = _read(raw, "vle.csv")[["id_site", "code_module", "code_presentation", "activity_type"]]
    site_keys = ["code_module", "code_presentation", "id_site"]
    if site_types.duplicated(site_keys).any():
        raise ValueError("vle.csv contains duplicate site-course identities")
    site_key_index = pd.MultiIndex.from_frame(site_types[site_keys])
    usecols = ["code_module", "code_presentation", "id_student", "id_site", "date", "sum_click"]
    for part in pd.read_csv(raw / "studentVle.csv", usecols=usecols, chunksize=chunk_size):
        part = part[(part["date"] >= 0) & (part["date"] < prediction_day)]
        if part.empty:
            continue
        part["id_student"] = part["id_student"].astype("int64")
        if not pd.MultiIndex.from_frame(part[KEYS]).isin(source_key_index).all():
            raise ValueError("studentVle.csv contains an early-window student-course key absent from studentInfo.csv")
        if not pd.MultiIndex.from_frame(part[site_keys]).isin(site_key_index).all():
            raise ValueError("studentVle.csv contains an early-window site-course key absent from vle.csv")
        part["week"] = (part["date"] // 7).astype("int8")
        part = part.merge(site_types, on=["id_site", "code_module", "code_presentation"], how="left",
                          validate="many_to_one")
        group = part.groupby(KEYS)
        agg = group.agg(clicks=("sum_click", "sum"), days=("date", "nunique"),
                        sites=("id_site", "nunique"), activities=("id_site", "size"))
        for key, row in agg.iterrows():
            k = tuple(key)
            old = totals.setdefault(k, [0, set(), set(), set()])
            old[0] += int(row.clicks)
        for key, frame in group:
            totals[tuple(key)][1].update(frame["date"].unique())
            totals[tuple(key)][2].update(frame["id_site"].unique())
            totals[tuple(key)][3].update(frame["activity_type"].dropna().unique())
        wg = part.groupby(KEYS + ["week"])
        for key, frame in wg:
            k = tuple(key[:3]); week = int(key[3]); seq = weekly.setdefault(k, {
                "weekly_clicks": [0.0] * (prediction_day // 7),
                "weekly_active_days": [set() for _ in range(prediction_day // 7)]})
            if 0 <= week < len(seq["weekly_clicks"]):
                seq["weekly_clicks"][week] += float(frame["sum_click"].sum())
                seq["weekly_active_days"][week].update(frame["date"].unique())

    activity_rows = []
    for key, vals in totals.items():
        activity_rows.append((*key, vals[0], len(vals[1]), len(vals[2]), len(vals[3])))
    activity = pd.DataFrame(activity_rows, columns=KEYS + ["early_vle_clicks", "early_vle_active_days",
                        "early_vle_active_sites", "early_vle_activity_types"])
    base = base.merge(activity, on=KEYS, how="left", validate="one_to_one")
    base["early_vle_active_weeks"] = base[KEYS].apply(lambda r: sum(
        v > 0 for v in weekly.get(tuple(r), {}).get("weekly_clicks", [])), axis=1)
    for col in ["early_vle_clicks", "early_vle_active_days", "early_vle_active_weeks",
                "early_vle_active_sites", "early_vle_activity_types"]:
        base[col] = base[col].fillna(0)
    base["source_record_id"] = [
        historical_source_record_id(module, presentation, student_id)
        for module, presentation, student_id in base[KEYS].itertuples(index=False, name=None)
    ]
    if base["source_record_id"].duplicated().any():
        raise ValueError("Canonical OULAD source record IDs are not unique")
    # Missing assessment means are intentionally left NaN for fold-fitted imputation.
    eligible_keys = set(map(tuple, base[KEYS].itertuples(index=False, name=None)))
    seq_rows = [{**dict(zip(KEYS, k)), "weekly_clicks": v["weekly_clicks"],
                 "weekly_active_days": [len(days) for days in v["weekly_active_days"]]}
                for k, v in weekly.items() if k in eligible_keys]
    sequences = pd.DataFrame(seq_rows)
    base.attrs["cohort_exclusions"] = {
        **exclusion_counts,
        "eligible_rows": int(len(base)),
        "policy": "Exclude withdrawals before day 56 and withdrawals with unknown timing; retain withdrawal outcomes on or after day 56.",
    }
    return base, sequences


def _student_disjoint_presentation_split(data: pd.DataFrame):
    """Keep chronological cohorts while purging repeat students from later folds."""
    train = data[data.code_presentation.isin(["2013B", "2013J"])].copy()
    valid_candidates = data[data.code_presentation.eq("2014B")].copy()
    test_candidates = data[data.code_presentation.eq("2014J")].copy()
    train_students = set(train.id_student)
    valid_overlap = valid_candidates.id_student.isin(train_students)
    valid = valid_candidates.loc[~valid_overlap].copy()
    validation_students = set(valid.id_student)
    test_overlap = test_candidates.id_student.isin(train_students | validation_students)
    test = test_candidates.loc[~test_overlap].copy()
    if any(frame.empty for frame in (train, valid, test)):
        raise ValueError("Expected nonempty student-disjoint chronological groups 2013B/2013J, 2014B, 2014J")
    train_students = set(train.id_student)
    valid_students = set(valid.id_student)
    test_students = set(test.id_student)
    if (train_students & valid_students) or (train_students & test_students) or (valid_students & test_students):
        raise RuntimeError("Presentation split contains a student in more than one partition")
    diagnostics = {
        "rows": {"train": len(train), "validation": len(valid), "test": len(test)},
        "unique_students": {"train": len(train_students), "validation": len(valid_students), "test": len(test_students)},
        "excluded_validation_rows": int(valid_overlap.sum()),
        "excluded_validation_students": int(valid_candidates.loc[valid_overlap, "id_student"].nunique()),
        "excluded_test_rows": int(test_overlap.sum()),
        "excluded_test_students": int(test_candidates.loc[test_overlap, "id_student"].nunique()),
        "policy": "Keep 2013B/2013J for train, purge train IDs from 2014B, then purge train and retained validation IDs from 2014J.",
    }
    return (train, valid, test), diagnostics


def split_by_presentation(data: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Chronological split with student IDs disjoint across train, validation, and test."""
    return _student_disjoint_presentation_split(data)[0]


def split_diagnostics(data: pd.DataFrame) -> dict:
    """Report cohort sizes and repeat-student rows removed from later periods."""
    return _student_disjoint_presentation_split(data)[1]
