import pytest

from scripts import import_oulad


def test_historical_oulad_import_into_live_student_tables_is_disabled():
    with pytest.raises(SystemExit, match="Historical OULAD rows are not live students"):
        import_oulad.main()


def test_old_import_command_points_to_non_persistent_canonical_export():
    with pytest.raises(SystemExit) as error:
        import_oulad.main()
    assert "python -m ml.features.export_canonical" in str(error.value)
