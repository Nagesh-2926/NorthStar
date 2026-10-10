"""Validation for the single-file coordinator inference CSV."""
from __future__ import annotations

import csv
import io
import math
import re
from typing import Any

from ml.features.build_dataset import FEATURES, NUMERIC_FEATURES
from ml.inference.prediction_service import validate_features

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_ROWS = 5_000
ENROLLMENT_NUMBER_PATTERN = re.compile(r"^24030315[0-9]{5,}$")
WEEKLY_COLUMNS = [
    column
    for week in range(1, 9)
    for column in (f"week_{week}_clicks", f"week_{week}_active_days")
]
EXPECTED_COLUMNS = {"enrollment_number", *FEATURES, *WEEKLY_COLUMNS}
MAX_ERRORS = MAX_ROWS * (len(NUMERIC_FEATURES) + len(WEEKLY_COLUMNS) + 4)


class CSVImportValidationError(ValueError):
    def __init__(self, errors: list[dict[str, Any]]):
        self.errors = errors[:MAX_ERRORS]
        super().__init__("CSV validation failed")


def _error(errors: list[dict[str, Any]], row: int | None, field: str, message: str) -> None:
    if len(errors) < MAX_ERRORS:
        errors.append({"row": row, "field": field, "message": message})


def parse_inference_csv(content: bytes) -> list[dict[str, Any]]:
    if not content:
        raise CSVImportValidationError([{"row": None, "field": "file", "message": "The CSV file is empty."}])
    if len(content) > MAX_UPLOAD_BYTES:
        raise CSVImportValidationError([{"row": None, "field": "file", "message": "File exceeds the 20 MB upload limit."}])
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CSVImportValidationError([{"row": None, "field": "encoding", "message": "Use UTF-8 encoded CSV."}]) from exc
    reader = csv.DictReader(io.StringIO(text, newline=""), dialect="excel", strict=True)
    try:
        headers = reader.fieldnames
    except csv.Error:
        raise CSVImportValidationError([
            {"row": 1, "field": "header", "message": "Malformed CSV header."}
        ]) from None
    if not headers:
        raise CSVImportValidationError([{"row": None, "field": "header", "message": "CSV header is required."}])
    errors: list[dict[str, Any]] = []
    if len(headers) != len(set(headers)):
        _error(errors, 1, "header", "Duplicate column names are not allowed.")
    if "enrollment_number" not in headers:
        _error(errors, 1, "enrollment_number", "Enrollment number is required. Please use the provided student upload template.")
    unknown = sorted(set(headers) - EXPECTED_COLUMNS)
    if unknown:
        _error(errors, 1, "header", f"Unknown columns: {', '.join(unknown)}.")
    if "early_support_label" in headers:
        _error(errors, 1, "early_support_label", "Outcome labels are training-only and must not be uploaded.")
    missing_features = sorted(set(FEATURES) - set(headers))
    if missing_features:
        _error(errors, 1, "header", f"Required model columns are missing: {', '.join(missing_features)}.")
    weekly_headers = set(headers) & set(WEEKLY_COLUMNS)
    if weekly_headers and weekly_headers != set(WEEKLY_COLUMNS):
        missing_weekly = sorted(set(WEEKLY_COLUMNS) - weekly_headers)
        _error(errors, 1, "weekly_sequence",
               f"Weekly columns must be supplied together or omitted: {', '.join(missing_weekly)}.")
    if errors:
        raise CSVImportValidationError(errors)

    rows: list[dict[str, Any]] = []
    seen_numbers: set[str] = set()
    try:
        for row_index, raw in enumerate(reader, start=2):
            if row_index > MAX_ROWS + 1:
                _error(errors, row_index, "file", f"Upload exceeds the {MAX_ROWS:,}-row limit.")
                break
            if None in raw:
                _error(errors, row_index, "row", "Row contains extra values beyond the header.")
                continue
            number = (raw.get("enrollment_number") or "").strip()
            if not number or not ENROLLMENT_NUMBER_PATTERN.fullmatch(number):
                _error(errors, row_index, "enrollment_number", "Enrollment number has an invalid format.")
                continue
            if number in seen_numbers:
                _error(errors, row_index, "enrollment_number", "Duplicate enrollment number in this file.")
                continue
            seen_numbers.add(number)

            feature_values: dict[str, Any] = {"code_module": (raw.get("code_module") or "").strip().upper(),
                                               "code_presentation": (raw.get("code_presentation") or "").strip().upper()}
            row_invalid = False
            for name in NUMERIC_FEATURES:
                text_value = (raw.get(name) or "").strip()
                if not text_value:
                    feature_values[name] = None
                    continue
                try:
                    number_value = float(text_value)
                    if not math.isfinite(number_value):
                        raise ValueError
                    feature_values[name] = int(number_value) if number_value.is_integer() else number_value
                except ValueError:
                    _error(errors, row_index, name, "Value must be a finite number or blank.")
                    row_invalid = True

            try:
                feature_values = validate_features(feature_values)
            except ValueError as exc:
                _error(errors, row_index, "features", str(exc))
                row_invalid = True

            weekly_values: list[float] = []
            weekly_supplied = 0
            weekly_blank = 0
            if not row_invalid:
                for name in WEEKLY_COLUMNS:
                    value = (raw.get(name) or "").strip()
                    if not value:
                        weekly_blank += 1
                        continue
                    maximum = 9481 if name.endswith("_clicks") else 7
                    try:
                        numeric = float(value)
                        if not math.isfinite(numeric) or not numeric.is_integer():
                            raise ValueError
                        integer = int(numeric)
                        if integer < 0 or integer > maximum:
                            raise ValueError
                        weekly_values.append(float(integer))
                        weekly_supplied += 1
                    except ValueError:
                        _error(errors, row_index, name, f"Value must be an integer between 0 and {maximum}.")
                        row_invalid = True
                if weekly_supplied and weekly_blank:
                    _error(errors, row_index, "weekly_sequence", "Provide all eight weeks or leave all weekly fields blank; missing weeks are never filled.")
                    row_invalid = True
                sequence = None
                if weekly_supplied == len(WEEKLY_COLUMNS):
                    sequence = [weekly_values[index:index + 2]
                                for index in range(0, len(WEEKLY_COLUMNS), 2)]
                    if (sum(week[0] for week in sequence) != feature_values["early_vle_clicks"] or
                            sum(week[1] for week in sequence) != feature_values["early_vle_active_days"] or
                            sum(week[0] > 0 for week in sequence) != feature_values["early_vle_active_weeks"]):
                        _error(errors, row_index, "weekly_sequence",
                               "Weekly totals must match the aggregate early clicks, active days, and active weeks.")
                        row_invalid = True
            else:
                sequence = None

            if not row_invalid:
                rows.append({"row": row_index, "enrollment_number": number,
                             "features": feature_values, "weekly_sequence": sequence})
    except csv.Error as exc:
        _error(errors, reader.line_num or None, "csv", "Malformed CSV row.")

    if not rows and not errors:
        _error(errors, None, "file", "CSV must contain at least one data row.")
    if errors:
        raise CSVImportValidationError(errors)
    return rows


def parse_inference_csv_report(content: bytes) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """Parse a batch while retaining valid rows and reporting each invalid row."""
    if not content:
        return [], [{"row": None, "field": "file", "message": "The CSV file is empty."}], 0
    if len(content) > MAX_UPLOAD_BYTES:
        return [], [{"row": None, "field": "file", "message": "File exceeds the 20 MB upload limit."}], 0
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return [], [{"row": None, "field": "encoding", "message": "Use UTF-8 encoded CSV."}], 0

    reader = csv.DictReader(io.StringIO(text, newline=""), dialect="excel", strict=True)
    try:
        headers = reader.fieldnames
    except csv.Error:
        return [], [{"row": 1, "field": "header", "message": "Malformed CSV header."}], 0
    if not headers:
        return [], [{"row": None, "field": "header", "message": "CSV header is required."}], 0

    errors: list[dict[str, Any]] = []
    if len(headers) != len(set(headers)):
        _error(errors, 1, "header", "Duplicate column names are not allowed.")
    if "enrollment_number" not in headers:
        _error(errors, 1, "enrollment_number", "Enrollment number is required. Please use the provided student upload template.")
    unknown = sorted(set(headers) - EXPECTED_COLUMNS)
    if unknown:
        _error(errors, 1, "header", f"Unknown columns: {', '.join(unknown)}.")
    if "early_support_label" in headers:
        _error(errors, 1, "early_support_label", "Outcome labels are training-only and must not be uploaded.")
    missing_features = sorted(set(FEATURES) - set(headers))
    if missing_features:
        _error(errors, 1, "header", f"Required model columns are missing: {', '.join(missing_features)}.")
    weekly_headers = set(headers) & set(WEEKLY_COLUMNS)
    if weekly_headers and weekly_headers != set(WEEKLY_COLUMNS):
        missing_weekly = sorted(set(WEEKLY_COLUMNS) - weekly_headers)
        _error(errors, 1, "weekly_sequence",
               f"Weekly columns must be supplied together or omitted: {', '.join(missing_weekly)}.")

    parsed_rows: list[dict[str, Any]] = []
    seen: dict[str, list[int]] = {}
    total = 0
    over_limit = False
    while True:
        try:
            raw = next(reader)
        except StopIteration:
            break
        except csv.Error:
            total += 1
            _error(errors, total + 1, "csv", "Malformed CSV row; remaining file content could not be parsed.")
            break
        total += 1
        row_number = total + 1
        if total > MAX_ROWS:
            if not over_limit:
                _error(errors, row_number, "file", f"Upload exceeds the {MAX_ROWS:,}-row limit.")
                over_limit = True
            continue
        if errors and any(item["row"] == 1 for item in errors):
            continue
        if None in raw:
            _error(errors, row_number, "row", "Row contains extra values beyond the header.")
            continue
        enrollment_number = (raw.get("enrollment_number") or "").strip()
        if enrollment_number:
            seen.setdefault(enrollment_number, []).append(row_number)
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=headers, lineterminator="\n")
        writer.writeheader()
        writer.writerow(raw)
        try:
            parsed = parse_inference_csv(output.getvalue().encode("utf-8"))
            parsed[0]["row"] = row_number
            parsed_rows.extend(parsed)
        except (CSVImportValidationError, IndexError) as exc:
            row_errors = exc.errors if isinstance(exc, CSVImportValidationError) else [
                {"row": 2, "field": "row", "message": "Malformed CSV row."}
            ]
            for item in row_errors:
                _error(errors, row_number, item["field"], item["message"])

    duplicate_rows = {row for numbers in seen.values() if len(numbers) > 1 for row in numbers}
    if duplicate_rows:
        parsed_rows = [row for row in parsed_rows if row["row"] not in duplicate_rows]
        for row_number in sorted(duplicate_rows):
            _error(errors, row_number, "enrollment_number", "Duplicate enrollment number in this file; all occurrences were rejected.")
    if not total and not errors:
        _error(errors, None, "file", "CSV must contain at least one data row.")
    if errors and any(item["row"] == 1 for item in errors):
        return [], errors, total
    if over_limit:
        return [], errors, total
    return parsed_rows, errors, total
