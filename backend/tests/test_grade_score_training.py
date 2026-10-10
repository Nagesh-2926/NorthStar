from pathlib import Path

from ml.features.build_dataset import FEATURES
from ml.features.train_grade_score import build_training_data, student_disjoint_splits


ROOT = Path(__file__).resolve().parents[2]


def test_numeric_target_is_observed_exam_score_and_uses_disjoint_chronological_folds():
    data = build_training_data(ROOT / "data" / "raw" / "oulad",
        ROOT / "data" / "processed" / "oulad_early_features.csv.gz")
    assert len(data) == 4959
    assert set(data.code_module) == {"CCC", "DDD"}
    assert data.final_exam_score.between(0, 100).all()
    assert "early_support_label" not in FEATURES

    train, validation, test = student_disjoint_splits(data)
    student_sets = [set(frame.id_student) for frame in (train, validation, test)]
    assert not (student_sets[0] & student_sets[1])
    assert not (student_sets[0] & student_sets[2])
    assert not (student_sets[1] & student_sets[2])
    assert set(train.code_presentation) == {"2013B", "2013J"}
    assert set(validation.code_presentation) == {"2014B"}
    assert set(test.code_presentation) == {"2014J"}
