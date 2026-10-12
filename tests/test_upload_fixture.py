import csv
from pathlib import Path

import pandas as pd
import pytest

from backend.app.services.csv_import import parse_inference_csv_report
from ml.features.build_dataset import split_by_presentation
from ml.features.canonical import COORDINATOR_UPLOAD_COLUMNS
from ml.fixtures import coordinator_upload as fixture

ROOT = Path(__file__).resolve().parents[1]
DIR = fixture.FIXTURE_DIR

pytestmark = pytest.mark.skipif(not (DIR / fixture.MAPPING_CSV).is_file(),
                                reason="Coordinator upload fixture has not been generated")


@pytest.fixture(scope="module")
def canonical():
    return pd.read_csv(fixture.CANONICAL_DATASET)


@pytest.fixture(scope="module")
def mapping():
    with (DIR / fixture.MAPPING_CSV).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def read_header(name):
    with (DIR / name).open(encoding="utf-8", newline="") as stream:
        return next(csv.reader(stream))


def test_fixture_files_use_the_exact_upload_template_schema():
    template = fixture.UPLOAD_TEMPLATE.read_text(encoding="utf-8-sig").splitlines()[0].split(",")
    assert template == COORDINATOR_UPLOAD_COLUMNS
    for name in (fixture.VALID_CSV, fixture.REJECTIONS_CSV):
        header = read_header(name)
        assert header == template
        assert not fixture.FORBIDDEN_UPLOAD_COLUMNS & set(header)


def test_upload_files_contain_no_source_identifiers(mapping):
    source_ids = {row["source_record_id"] for row in mapping}
    for name in (fixture.VALID_CSV, fixture.REJECTIONS_CSV):
        text = (DIR / name).read_text(encoding="utf-8")
        assert "oulad:" not in text
        assert not any(source_id in text for source_id in source_ids)


def test_fixture_is_deterministic_and_matches_committed_files(canonical):
    first = fixture.fixture_files(fixture.build_fixture(canonical, fixture.known_issued_numbers()))
    second = fixture.fixture_files(fixture.build_fixture(canonical, fixture.known_issued_numbers()))
    for name in (fixture.VALID_CSV, fixture.REJECTIONS_CSV, fixture.MAPPING_CSV):
        assert first[name] == second[name]
        committed = (DIR / name).read_bytes()
        # Git may check these tracked CSVs out with CRLF on Windows. Compare exact
        # content while treating CRLF and the generator's canonical LF as equivalent.
        assert b"\r" not in committed.replace(b"\r\n", b""), f"{name} has invalid line endings"
        assert first[name] == committed.replace(b"\r\n", b"\n"), (
            f"{name} is stale; regenerate the fixture"
        )


def test_synthetic_numbers_are_reserved_unique_and_never_issued(mapping):
    numbers = [row["synthetic_enrollment_number"] for row in mapping]
    distinct = set(numbers)
    assert all(fixture.is_reserved_synthetic(number) for number in distinct)
    assert all(len(number) == 13 and number.startswith("24030315") for number in distinct)
    # Only the intentional duplicate case shares a number.
    assert len(numbers) - len(distinct) == 1
    assert distinct.isdisjoint({str(value) for value in fixture.known_issued_numbers()})


def test_fixture_rows_come_only_from_the_held_out_test_partition(canonical, mapping):
    train, validation, test = split_by_presentation(canonical.rename(columns={"source_student_id": "id_student"}))
    used = {row["source_record_id"] for row in mapping}
    assert used <= set(test.source_record_id)
    assert used.isdisjoint(set(train.source_record_id) | set(validation.source_record_id))


def test_valid_file_parses_cleanly_and_full_sequences_reconcile():
    rows, errors, total = parse_inference_csv_report((DIR / fixture.VALID_CSV).read_bytes())
    assert errors == []
    assert total == len(rows) == 23
    with_sequence = [row for row in rows if row["weekly_sequence"] is not None]
    assert len(with_sequence) == 21
    for row in with_sequence:
        sequence = row["weekly_sequence"]
        assert len(sequence) == 8
        assert sum(week[0] for week in sequence) == row["features"]["early_vle_clicks"]
        assert sum(week[1] for week in sequence) == row["features"]["early_vle_active_days"]
        assert sum(week[0] > 0 for week in sequence) == row["features"]["early_vle_active_weeks"]


def test_rejection_file_parse_level_cases_fail_on_the_documented_field(mapping):
    rows, errors, total = parse_inference_csv_report((DIR / fixture.REJECTIONS_CSV).read_bytes())
    cases = {int(row["fixture_row"]): row for row in mapping if row["fixture_file"] == fixture.REJECTIONS_CSV}
    assert total == len(cases) == len(fixture.REJECTION_CASES)
    error_fields = {}
    for error in errors:
        error_fields.setdefault(error["row"], set()).add(error["field"])
    parsed_rows = {row["row"] for row in rows}
    identity_cases = {"unknown_enrollment", "module_presentation_mismatch",
                      "registration_metadata_mismatch", "inactive_enrollment"}
    for row_number, case in cases.items():
        if case["case_id"] in identity_cases:
            # These are rejected only by the database identity check.
            assert row_number in parsed_rows, case["case_id"]
        else:
            assert row_number not in parsed_rows, case["case_id"]
            assert case["expected_field"] in error_fields[row_number], case["case_id"]


def test_collision_checks_fail_closed():
    number = fixture.synthetic_number(0)
    with pytest.raises(fixture.FixtureCollisionError, match="already issued"):
        fixture.check_collisions([number], {int(number)})
    with pytest.raises(fixture.FixtureCollisionError, match="repeat"):
        fixture.check_collisions([number, number], set())
    with pytest.raises(fixture.FixtureCollisionError, match="outside"):
        fixture.check_collisions(["2403031500001"], set())
    with pytest.raises(fixture.FixtureCollisionError, match="high-water"):
        fixture.check_collisions([number], {fixture.SYNTHETIC_LAST})
    with pytest.raises(fixture.FixtureCollisionError, match="reserved"):
        fixture.synthetic_number(fixture.SYNTHETIC_LAST - fixture.SYNTHETIC_FIRST + 1)
    fixture.check_collisions([number], {2403031528793})


def test_builder_refuses_to_emit_when_registry_already_holds_a_reserved_number(canonical):
    with pytest.raises(fixture.FixtureCollisionError):
        fixture.build_fixture(canonical, {fixture.SYNTHETIC_FIRST + 3})
