import pytest
from pathlib import Path
from ml.features.build_dataset import FEATURES
from ml.inference.prediction_service import (predict, validate_features, load_model,
    model_feature_importance, assign_behavioral_cluster, assign_behavioral_clusters,
    predict_weekly_sequence)


def valid_row():
    return {"registration_day":-30,"num_of_prev_attempts":0,"studied_credits":60,
        "early_assessment_mean":None,"early_assessment_count":0,"early_on_time_rate":None,
        "early_assessment_coverage":None,"early_vle_clicks":0,"early_vle_active_days":0,
        "early_vle_active_weeks":0,"early_vle_active_sites":0,"early_vle_activity_types":0,
        "code_module":"AAA","code_presentation":"2014J"}


def test_feature_key_validation_and_null_handling():
    row = valid_row()
    assert list(validate_features(row)) == list(row)
    with pytest.raises(ValueError, match="Feature keys mismatch"):
        validate_features({k:v for k,v in row.items() if k != FEATURES[0]})
    row["early_vle_active_weeks"] = 9
    with pytest.raises(ValueError, match="between"):
        validate_features(row)
    row = valid_row()
    row["num_of_prev_attempts"] = 0.5
    with pytest.raises(ValueError, match="integer"):
        validate_features(row)


def test_prediction_result_shape_and_feature_order():
    class Model:
        def predict_proba(self, frame):
            assert list(frame.columns) == FEATURES
            return [[0.2, 0.8]]
    loaded = {"pipeline":Model(),"threshold":0.5,"name":"test","version":"1.0"}
    result = predict(valid_row(), loaded)
    assert result["support_priority_score"] == 0.8
    assert result["priority_band"] == "review_for_support"
    assert "destiny" in result["interpretation"]


@pytest.mark.skipif(not Path("ml/saved_models/registry.json").exists(), reason="train model artifacts first")
def test_saved_model_loading_prediction_and_global_importance():
    model = load_model()
    result = predict(valid_row(), model)
    assert 0 <= result["support_priority_score"] <= 1
    importance = model_feature_importance(model)
    assert importance["features"]
    assert "causal" in importance["interpretation"]


@pytest.mark.skipif(not Path("ml/saved_models/registry.json").exists(), reason="train model artifacts first")
@pytest.mark.parametrize("name", ["logistic_regression", "random_forest", "xgboost"])
def test_each_supervised_artifact_loads_with_the_shared_feature_contract(name):
    model = load_model(name)
    result = predict(valid_row(), model)
    assert result["model"] == name
    assert result["feature_version"] == model["feature_version"]
    assert 0 <= result["support_priority_score"] <= 1


@pytest.mark.skipif(not Path("ml/saved_models/kmeans.joblib").exists(), reason="train model artifacts first")
def test_saved_cluster_model_loads_and_assigns():
    values = {"early_assessment_mean":None,"early_assessment_count":0,"early_on_time_rate":None,
        "early_assessment_coverage":None,"early_vle_clicks":0,"early_vle_active_days":0,
        "early_vle_active_weeks":0,"early_vle_active_sites":0,"early_vle_activity_types":0}
    assert isinstance(assign_behavioral_cluster(values)["cluster_id"], int)


def test_behavioral_clustering_assigns_each_row_in_one_batch():
    class Preprocessor:
        def transform(self, frame):
            assert len(frame) == 2
            return frame

    class Model:
        def predict(self, frame):
            assert len(frame) == 2
            return [0, 1]

    features = {
        "early_assessment_mean": None,
        "early_assessment_count": 0,
        "early_on_time_rate": None,
        "early_assessment_coverage": None,
        "early_vle_clicks": 0,
        "early_vle_active_days": 0,
        "early_vle_active_weeks": 0,
        "early_vle_active_sites": 0,
        "early_vle_activity_types": 0,
    }
    result = assign_behavioral_clusters([features, features], {
        "preprocessor": Preprocessor(),
        "model": Model(),
    })

    assert [item["cluster_id"] for item in result] == [0, 1]
    assert all(item["features"] == features for item in result)


@pytest.mark.skipif(not Path("ml/saved_models/lstm_weekly.keras").exists(), reason="train model artifacts first")
def test_saved_lstm_loads_and_predicts():
    result = predict_weekly_sequence([[0, 0]] * 8)
    assert 0 <= result["support_priority_score"] <= 1
