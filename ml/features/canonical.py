"""Write the historical OULAD training table without application identities."""
from __future__ import annotations

import math
import os
from pathlib import Path

import pandas as pd

from ml.features.build_dataset import (
    FEATURES,
    KEYS,
    TARGET,
    historical_source_record_id,
)

SEQUENCE_LENGTH = 8
WEEKLY_COLUMNS = [
    column
    for week in range(1, SEQUENCE_LENGTH + 1)
    for column in (f"week_{week}_clicks", f"week_{week}_active_days")
]
CANONICAL_ID_COLUMNS = ["source_system", "source_record_id", "source_student_id"]
CANONICAL_COLUMNS = [*CANONICAL_ID_COLUMNS, *FEATURES, TARGET, *WEEKLY_COLUMNS]
COORDINATOR_UPLOAD_COLUMNS = ["enrollment_number", *FEATURES, *WEEKLY_COLUMNS]


def _sequence_values(value, field: str, maximum: int) -> list[int]:
    values = list(value)
    if len(values) != SEQUENCE_LENGTH:
        raise ValueError(f"{field} must contain exactly {SEQUENCE_LENGTH} chronological weeks")
    result: list[int] = []
    for item in values:
        numeric = float(item)
        if not math.isfinite(numeric) or not numeric.is_integer() or not 0 <= numeric <= maximum:
            raise ValueError(f"{field} contains a value outside its integer range")
        result.append(int(numeric))
    return result


def write_canonical_training_dataset(
    data: pd.DataFrame,
    sequences: pd.DataFrame,
    output_path: str | Path,
) -> int:
    """Write one historical student-course row with source IDs and day-56 inputs.

    The eight weekly windows cover course-relative days 0-55. A missing sequence
    key means no VLE activity was recorded for that source row; consistent with
    LSTM training and the historical database import, it is represented as eight
    measured zero-activity windows. This convention is specific to complete OULAD
    source-log exports, not a rule for unobserved coordinator CSV uploads.
    """
    required = {*KEYS, *FEATURES, TARGET, "source_record_id"}
    if not required.issubset(data.columns):
        raise ValueError(f"Canonical feature frame is missing columns: {sorted(required - set(data.columns))}")
    if data.duplicated(KEYS).any() or data["source_record_id"].duplicated().any():
        raise ValueError("Canonical features contain duplicate historical student-course identities")
    sequence_map: dict[tuple, tuple[list[int], list[int]]] = {}
    if not sequences.empty:
        if sequences.duplicated(KEYS).any():
            raise ValueError("Weekly source data contains duplicate student-course identities")
        for row in sequences.itertuples(index=False):
            key = tuple(getattr(row, name) for name in KEYS)
            sequence_map[key] = (
                _sequence_values(row.weekly_clicks, "weekly_clicks", 9481),
                _sequence_values(row.weekly_active_days, "weekly_active_days", 7),
            )

    rows: list[dict] = []
    ordered = data.sort_values(KEYS, kind="stable")
    for row in ordered.itertuples(index=False):
        key = tuple(getattr(row, name) for name in KEYS)
        clicks, active_days = sequence_map.get(key, ([0] * SEQUENCE_LENGTH, [0] * SEQUENCE_LENGTH))
        expected_source_id = historical_source_record_id(*key)
        if str(row.source_record_id) != expected_source_id:
            raise ValueError(f"Historical source_record_id does not match source keys for {key}")
        aggregate_clicks = int(getattr(row, "early_vle_clicks"))
        aggregate_days = int(getattr(row, "early_vle_active_days"))
        aggregate_weeks = int(getattr(row, "early_vle_active_weeks"))
        if (sum(clicks) != aggregate_clicks or sum(active_days) != aggregate_days or
                sum(value > 0 for value in clicks) != aggregate_weeks):
            raise ValueError(f"Weekly OULAD values do not reconcile with day-56 aggregates for {key}")
        output = {
            "source_system": "OULAD",
            "source_record_id": str(row.source_record_id),
            "source_student_id": int(row.id_student),
        }
        output.update({name: getattr(row, name) for name in FEATURES})
        output[TARGET] = int(getattr(row, TARGET))
        for week, (week_clicks, days) in enumerate(zip(clicks, active_days, strict=True), start=1):
            output[f"week_{week}_clicks"] = week_clicks
            output[f"week_{week}_active_days"] = days
        rows.append(output)

    result = pd.DataFrame(rows, columns=CANONICAL_COLUMNS)
    if result["source_record_id"].duplicated().any():
        raise ValueError("Canonical source_record_id values are not unique")
    if "enrollment_number" in result.columns:
        raise AssertionError("Historical canonical dataset must not contain application enrollment numbers")

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    result.to_csv(temporary_path, index=False)
    os.replace(temporary_path, path)
    return len(result)


def write_coordinator_upload_template(path: str | Path) -> None:
    """Write the blank live-upload schema separately from historical training data."""
    frame = pd.DataFrame(columns=COORDINATOR_UPLOAD_COLUMNS)
    template_path = Path(path)
    template_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(template_path, index=False)
