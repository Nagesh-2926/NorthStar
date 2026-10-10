"""Ordered channels and sequence length shared by LSTM training and serving."""

SEQUENCE_FEATURES = ["weekly_clicks", "weekly_active_days"]
SEQUENCE_LENGTH = 8
SEQUENCE_FEATURE_VERSION = "oulad-weekly-sequence-v1"
LEGACY_SEQUENCE_FEATURE_VERSIONS = {"oulad-early-risk-v1"}
