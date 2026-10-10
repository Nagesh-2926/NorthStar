import hashlib
import json

from ml.identity_registry import allocate_application_enrollment_number


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def test_application_numbers_are_stable_and_written_to_separate_registry(tmp_path):
    application_registry = tmp_path / "application_enrollment_registry.json"
    legacy_registry = tmp_path / "no-legacy-registry.json"

    first = allocate_application_enrollment_number(
        "student-uuid-1", application_registry, legacy_registry_path=legacy_registry
    )
    second = allocate_application_enrollment_number(
        "student-uuid-2", application_registry, legacy_registry_path=legacy_registry
    )
    replay = allocate_application_enrollment_number(
        "student-uuid-1", application_registry, legacy_registry_path=legacy_registry
    )

    assert first == "2403031500001"
    assert second == "2403031500002"
    assert replay == first
    document = json.loads(application_registry.read_text(encoding="utf-8"))
    assert document["namespace"] == "application-account"
    assert len(document["mappings"]) == 2


def test_legacy_oulad_numbers_are_not_reallocated_but_app_numbers_are_preserved(tmp_path):
    legacy = tmp_path / "enrollment_mapping_registry.json"
    application_registry = tmp_path / "application_enrollment_registry.json"
    legacy_document = {
        "registry_version": 1,
        "first_enrollment_number": "2403031500001",
        "mappings": {
            digest("107"): "2403031500001",  # historical OULAD source key
            digest("application-account:existing-student"): "2403031500002",
        },
    }
    original = json.dumps(legacy_document, indent=2)
    legacy.write_text(original, encoding="utf-8")

    existing = allocate_application_enrollment_number(
        "existing-student", application_registry, legacy_registry_path=legacy
    )
    new = allocate_application_enrollment_number(
        "new-student", application_registry, legacy_registry_path=legacy
    )

    assert existing == "2403031500002"
    assert new == "2403031500003"
    assert legacy.read_text(encoding="utf-8") == original
    saved = json.loads(application_registry.read_text(encoding="utf-8"))
    assert len(saved["mappings"]) == 2
    assert digest("107") not in saved["mappings"]
