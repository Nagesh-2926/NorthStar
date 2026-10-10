"""Build the coordinator-upload test fixture with reserved synthetic enrollment numbers.

The fixture is for isolated development/test databases only. Rows come from the
student-disjoint held-out 2014J test partition of the canonical OULAD dataset.
Synthetic enrollment numbers are drawn from a reserved block that no registry has
issued; they are not institution-issued IDs and do not identify real students.
The test-only mapping keeps each synthetic number next to its historical
source_record_id so nothing has to be inferred later. Neither the numbers nor
the source IDs are model features.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml.features.build_dataset import FEATURES, TARGET, split_by_presentation
from ml.features.canonical import COORDINATOR_UPLOAD_COLUMNS, WEEKLY_COLUMNS
from ml.inference.prediction_service import INTEGER_FEATURES, validate_features

FIXTURE_VERSION = "coordinator-upload-fixture-v1"
SYNTHETIC_PREFIX = "24030315"
SYNTHETIC_FIRST_SUFFIX = 90_000
SYNTHETIC_LAST_SUFFIX = 99_999
SYNTHETIC_FIRST = int(f"{SYNTHETIC_PREFIX}{SYNTHETIC_FIRST_SUFFIX:05d}")
SYNTHETIC_LAST = int(f"{SYNTHETIC_PREFIX}{SYNTHETIC_LAST_SUFFIX:05d}")
SYNTHETIC_EMAIL_PREFIX = "synthetic-upload-fixture-"
SYNTHETIC_EMAIL_DOMAIN = "@example.com"

CANONICAL_DATASET = ROOT / "data/processed/student_training_dataset.csv"
UPLOAD_TEMPLATE = ROOT / "data/templates/student_upload_template.csv"
APPLICATION_REGISTRY = ROOT / "data/processed/application_enrollment_registry.json"
LEGACY_REGISTRY = ROOT / "data/processed/enrollment_mapping_registry.json"
FIXTURE_DIR = ROOT / "data/test_fixtures/coordinator_upload"
VALID_CSV = "coordinator_upload_valid.test.csv"
REJECTIONS_CSV = "coordinator_upload_rejections.test.csv"
MAPPING_CSV = "synthetic_enrollment_mapping.test-only.csv"
MANIFEST_JSON = "fixture_manifest.json"

VALID_ROWS_PER_MODULE = 3
AGGREGATE_ONLY_ROWS = 2
MAPPING_COLUMNS = [
    "synthetic_enrollment_number", "fixture_file", "fixture_row", "case_id",
    "expected_outcome", "expected_field", "seed_enrollment", "seed_enrollment_active",
    "seed_code_module", "seed_code_presentation", "seed_registration_day",
    "seed_num_of_prev_attempts", "seed_studied_credits", "source_system",
    "source_record_id", "description",
]
# Columns that must never appear in an upload fixture.
FORBIDDEN_UPLOAD_COLUMNS = {TARGET, "source_system", "source_record_id", "source_student_id",
                            "id_student", "final_result", "date_unregistration"}

# Each rejection case corrupts or withholds exactly one thing, documented here.
# "seed" means the seed script creates a matching enrollment so the intended rule,
# not an unknown-enrollment error, is what rejects the row.
REJECTION_CASES = [
    ("unknown_enrollment", "enrollment_number", False,
     "Well-formed reserved number with no seeded application enrollment."),
    ("module_presentation_mismatch", "enrollment_number", True,
     "Seeded for the source presentation; the CSV row states code_presentation 2014B."),
    ("registration_metadata_mismatch", "enrollment_features", True,
     "Seeded with source studied_credits; the CSV row states studied_credits + 30."),
    ("inactive_enrollment", "enrollment_number", True,
     "Seeded enrollment is marked inactive; features are unchanged."),
    ("missing_enrollment_number", "enrollment_number", False,
     "enrollment_number is blank."),
    ("malformed_enrollment_number", "enrollment_number", False,
     "enrollment_number has only four digits after the prefix."),
    ("missing_code_module", "features", False,
     "Required categorical code_module is blank."),
    ("malformed_numeric", "early_vle_clicks", False,
     "early_vle_clicks is the text 'not-a-number'."),
    ("out_of_range_numeric", "features", False,
     "early_assessment_mean is 150, outside 0-100."),
    ("non_integer_count", "features", False,
     "early_vle_active_days is 3.5; the contract requires an integer."),
    ("partial_weekly_sequence", "weekly_sequence", False,
     "week_8 click and active-day values are blank while weeks 1-7 are present."),
    ("weekly_aggregate_mismatch", "weekly_sequence", False,
     "week_1_clicks is one higher than the source, so weekly clicks no longer sum to early_vle_clicks."),
    ("duplicate_enrollment_number_a", "enrollment_number", True,
     "First of two rows sharing one seeded number; every occurrence is rejected."),
    ("duplicate_enrollment_number_b", "enrollment_number", False,
     "Second row sharing the number above (seeded once via case _a)."),
]


class FixtureCollisionError(RuntimeError):
    """A synthetic number collides with an issued, reserved, or in-fixture number."""


@dataclass
class FixtureResult:
    valid_rows: list[dict]
    rejection_rows: list[dict]
    mapping: list[dict]
    manifest: dict = field(default_factory=dict)


def _registry_numbers(path: Path) -> set[int]:
    if not path.is_file():
        return set()
    document = json.loads(path.read_text(encoding="utf-8"))
    return {int(value) for value in document.get("mappings", {}).values()}


def known_issued_numbers(application_registry: Path = APPLICATION_REGISTRY,
                         legacy_registry: Path = LEGACY_REGISTRY,
                         extra: set[str] | None = None) -> set[int]:
    """Every number any registry (or the caller, e.g. a DB read) knows was issued."""
    issued = _registry_numbers(application_registry) | _registry_numbers(legacy_registry)
    issued |= {int(value) for value in (extra or set()) if str(value).isdigit()}
    return issued


def synthetic_number(index: int) -> str:
    value = SYNTHETIC_FIRST + index
    if not SYNTHETIC_FIRST <= value <= SYNTHETIC_LAST:
        raise FixtureCollisionError("Fixture exceeds the reserved synthetic enrollment block")
    return str(value)


def is_reserved_synthetic(number: str) -> bool:
    return (len(number) == 13 and number.isdigit() and number.startswith(SYNTHETIC_PREFIX)
            and SYNTHETIC_FIRST <= int(number) <= SYNTHETIC_LAST)


def check_collisions(numbers: list[str], issued: set[int]) -> None:
    """Fail closed: never reuse an issued number or let the allocator reach the block."""
    unique = set(numbers)
    if len(unique) != len(numbers):
        raise FixtureCollisionError("Synthetic numbers repeat within the fixture")
    if any(not is_reserved_synthetic(number) for number in unique):
        raise FixtureCollisionError("A synthetic number is outside the reserved block")
    clashes = sorted(int(number) for number in unique if int(number) in issued)
    if clashes:
        raise FixtureCollisionError(f"{len(clashes)} synthetic numbers were already issued (first: {clashes[0]})")
    if issued and max(issued) >= SYNTHETIC_FIRST:
        raise FixtureCollisionError(
            "The application allocator high-water mark has reached the reserved synthetic block")


def _format(name: str, value) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    if name in ("code_module", "code_presentation"):
        return str(value)
    numeric = float(value)
    if name in INTEGER_FEATURES or name in WEEKLY_COLUMNS:
        if not numeric.is_integer():
            raise ValueError(f"{name} must be an integer in the canonical dataset")
        return str(int(numeric))
    return repr(numeric)


def _upload_row(source: pd.Series, number: str, *, weekly: bool = True) -> dict:
    row = {"enrollment_number": number}
    for name in FEATURES:
        row[name] = _format(name, source[name])
    for name in WEEKLY_COLUMNS:
        row[name] = _format(name, source[name]) if weekly else ""
    return row


def _contract_problem(source: pd.Series) -> str | None:
    """Return a reason when a source row cannot satisfy the upload contract unchanged."""
    features = {}
    for name in FEATURES:
        value = source[name]
        if isinstance(value, float) and math.isnan(value):
            value = None
        elif name not in ("code_module", "code_presentation"):
            value = float(value)
        features[name] = value
    try:
        validate_features(features)
    except ValueError as exc:
        return str(exc)
    clicks = [int(source[f"week_{week}_clicks"]) for week in range(1, 9)]
    days = [int(source[f"week_{week}_active_days"]) for week in range(1, 9)]
    if (sum(clicks) != features["early_vle_clicks"] or sum(days) != features["early_vle_active_days"]
            or sum(value > 0 for value in clicks) != features["early_vle_active_weeks"]):
        return "weekly sequence does not reconcile with aggregate VLE features"
    return None


def held_out_candidates(canonical: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """Return test-partition rows in a deterministic order, plus exclusion counts."""
    frame = canonical.rename(columns={"source_student_id": "id_student"})
    _, _, test = split_by_presentation(frame)
    test = test.sort_values("source_record_id", kind="stable").reset_index(drop=True)
    problems = test.apply(_contract_problem, axis=1)
    exclusions: dict[str, int] = {}
    for reason in problems.dropna():
        exclusions[reason] = exclusions.get(reason, 0) + 1
    return test.loc[problems.isna()].reset_index(drop=True), exclusions


def _seed_fields(source: pd.Series, *, active: bool = True) -> dict:
    def optional_int(value):
        return "" if isinstance(value, float) and math.isnan(value) else str(int(value))
    return {
        "seed_enrollment": "true", "seed_enrollment_active": "true" if active else "false",
        "seed_code_module": source["code_module"], "seed_code_presentation": source["code_presentation"],
        "seed_registration_day": optional_int(source["registration_day"]),
        "seed_num_of_prev_attempts": optional_int(source["num_of_prev_attempts"]),
        "seed_studied_credits": optional_int(source["studied_credits"]),
    }


NO_SEED = {"seed_enrollment": "false", "seed_enrollment_active": "", "seed_code_module": "",
           "seed_code_presentation": "", "seed_registration_day": "",
           "seed_num_of_prev_attempts": "", "seed_studied_credits": ""}


def build_fixture(canonical: pd.DataFrame, issued: set[int]) -> FixtureResult:
    candidates, exclusions = held_out_candidates(canonical)
    modules = sorted(candidates["code_module"].unique())
    valid_sources = [row for module in modules
                     for _, row in candidates[candidates.code_module.eq(module)].head(VALID_ROWS_PER_MODULE).iterrows()]
    used = {row["source_record_id"] for row in valid_sources}
    remaining = candidates[~candidates.source_record_id.isin(used)].reset_index(drop=True)
    # Weekly corruption cases need a source row with clicks in week 1 and week 8.
    active = remaining[(remaining.week_1_clicks > 0) & (remaining.week_8_clicks > 0)
                       & remaining.early_assessment_mean.notna()].reset_index(drop=True)
    needed = AGGREGATE_ONLY_ROWS + len(REJECTION_CASES)
    if len(active) < needed:
        raise ValueError("Not enough held-out rows to build the fixture")
    aggregate_sources = [active.iloc[i] for i in range(AGGREGATE_ONLY_ROWS)]
    rejection_sources = [active.iloc[AGGREGATE_ONLY_ROWS + i] for i in range(len(REJECTION_CASES))]

    numbers = iter(range(SYNTHETIC_LAST_SUFFIX - SYNTHETIC_FIRST_SUFFIX + 1))
    valid_rows, rejection_rows, mapping = [], [], []

    def add_mapping(number, file_name, file_row, case, outcome, expected_field, seed, source, description):
        mapping.append({"synthetic_enrollment_number": number, "fixture_file": file_name,
                        "fixture_row": file_row, "case_id": case, "expected_outcome": outcome,
                        "expected_field": expected_field, **seed, "source_system": "OULAD",
                        "source_record_id": source["source_record_id"], "description": description})

    for source in valid_sources:
        number = synthetic_number(next(numbers))
        valid_rows.append(_upload_row(source, number))
        add_mapping(number, VALID_CSV, len(valid_rows) + 1, "valid_with_weekly_sequence", "accept", "",
                    _seed_fields(source), source, "Unchanged held-out features with all eight weekly windows.")
    for source in aggregate_sources:
        number = synthetic_number(next(numbers))
        valid_rows.append(_upload_row(source, number, weekly=False))
        add_mapping(number, VALID_CSV, len(valid_rows) + 1, "valid_aggregate_only", "accept", "",
                    _seed_fields(source), source,
                    "Unchanged aggregate features; weekly fields left blank as a group, so no sequence forecast runs.")

    duplicate_number = None
    for (case, expected_field, seeded, description), source in zip(REJECTION_CASES, rejection_sources, strict=True):
        if case == "duplicate_enrollment_number_b":
            number = duplicate_number
        else:
            number = synthetic_number(next(numbers))
        row = _upload_row(source, number)
        seed = _seed_fields(source, active=case != "inactive_enrollment") if seeded else dict(NO_SEED)
        if case == "module_presentation_mismatch":
            row["code_presentation"] = "2014B"
        elif case == "registration_metadata_mismatch":
            row["studied_credits"] = str(int(source["studied_credits"]) + 30)
        elif case == "missing_enrollment_number":
            row["enrollment_number"] = ""
        elif case == "malformed_enrollment_number":
            row["enrollment_number"] = number[:12]
        elif case == "missing_code_module":
            row["code_module"] = ""
        elif case == "malformed_numeric":
            row["early_vle_clicks"] = "not-a-number"
        elif case == "out_of_range_numeric":
            row["early_assessment_mean"] = "150"
        elif case == "non_integer_count":
            row["early_vle_active_days"] = "3.5"
        elif case == "partial_weekly_sequence":
            row["week_8_clicks"] = row["week_8_active_days"] = ""
        elif case == "weekly_aggregate_mismatch":
            row["week_1_clicks"] = str(int(row["week_1_clicks"]) + 1)
        elif case == "duplicate_enrollment_number_a":
            duplicate_number = number
        rejection_rows.append(row)
        add_mapping(number, REJECTIONS_CSV, len(rejection_rows) + 1, case, "reject", expected_field,
                    seed, source, description)

    check_collisions(sorted({item["synthetic_enrollment_number"] for item in mapping}), issued)
    for row in valid_rows + rejection_rows:
        if list(row) != COORDINATOR_UPLOAD_COLUMNS:
            raise AssertionError("Fixture row does not follow the upload template order")
    assigned = sorted(int(item["synthetic_enrollment_number"]) for item in mapping)
    manifest = {
        "fixture_version": FIXTURE_VERSION,
        "purpose": "Isolated development/test validation of coordinator CSV uploads only.",
        "synthetic_identifier_notice": ("Synthetic enrollment numbers are test fixtures. They are not "
                                        "institution-issued, do not identify real students, and must "
                                        "never be seeded into production."),
        "reserved_block": {"prefix": SYNTHETIC_PREFIX, "first": str(SYNTHETIC_FIRST),
                           "last": str(SYNTHETIC_LAST), "assigned_first": str(assigned[0]),
                           "assigned_last": str(assigned[-1]), "assigned_count": len(assigned)},
        "collision_checks": {"issued_numbers_checked": len(issued),
                             "issued_high_water_mark": str(max(issued)) if issued else None,
                             "collisions": 0},
        "source": {"dataset": "data/processed/student_training_dataset.csv",
                   "partition": "student-disjoint held-out test (2014J after purging train/validation students)",
                   "eligible_candidates": int(len(candidates)),
                   "excluded_candidates": exclusions,
                   "selection": (f"Sort by source_record_id; first {VALID_ROWS_PER_MODULE} per module for "
                                 "full-sequence valid rows, then the next rows with week-1 and week-8 "
                                 "activity and an observed assessment mean for aggregate-only and rejection cases.")},
        "files": {VALID_CSV: len(valid_rows), REJECTIONS_CSV: len(rejection_rows), MAPPING_CSV: len(mapping)},
        "upload_columns": COORDINATOR_UPLOAD_COLUMNS,
        "missing_value_representation": "empty field",
        "seeded_numbers": sum(item["seed_enrollment"] == "true" for item in mapping),
    }
    return FixtureResult(valid_rows, rejection_rows, mapping, manifest)


def _csv_bytes(rows: list[dict], columns: list[str]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def fixture_files(result: FixtureResult) -> dict[str, bytes]:
    files = {
        VALID_CSV: _csv_bytes(result.valid_rows, COORDINATOR_UPLOAD_COLUMNS),
        REJECTIONS_CSV: _csv_bytes(result.rejection_rows, COORDINATOR_UPLOAD_COLUMNS),
        MAPPING_CSV: _csv_bytes(result.mapping, MAPPING_COLUMNS),
    }
    manifest = dict(result.manifest)
    manifest["sha256"] = {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}
    files[MANIFEST_JSON] = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    return files


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path, default=FIXTURE_DIR)
    parser.add_argument("--known-ids-file", type=Path,
                        help="Optional newline-separated enrollment numbers read from the target test database.")
    args = parser.parse_args(argv)
    template_header = UPLOAD_TEMPLATE.read_text(encoding="utf-8-sig").splitlines()[0].split(",")
    if template_header != COORDINATOR_UPLOAD_COLUMNS:
        raise SystemExit("The upload template no longer matches the feature contract; refusing to build.")
    extra = set()
    if args.known_ids_file:
        extra = {line.strip() for line in args.known_ids_file.read_text(encoding="utf-8").splitlines() if line.strip()}
    issued = known_issued_numbers(extra=extra)
    canonical = pd.read_csv(CANONICAL_DATASET)
    try:
        result = build_fixture(canonical, issued)
    except FixtureCollisionError as exc:
        raise SystemExit(f"Refusing to write fixture: {exc}") from exc
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, content in fixture_files(result).items():
        (args.output_dir / name).write_bytes(content)
    print(f"valid_rows={len(result.valid_rows)} rejection_rows={len(result.rejection_rows)} "
          f"synthetic_numbers={result.manifest['reserved_block']['assigned_count']} "
          f"range={result.manifest['reserved_block']['assigned_first']}-{result.manifest['reserved_block']['assigned_last']}")
    print(f"output_dir={args.output_dir}")
    print("database_writes=0")


if __name__ == "__main__":
    main()
