"""Build the canonical historical OULAD feature export without training or DB writes."""
from __future__ import annotations

from pathlib import Path

from ml.data.source_manifest import create_source_manifest
from ml.features.build_dataset import build_student_features
from ml.features.canonical import write_canonical_training_dataset

ROOT = Path(__file__).resolve().parents[2]
RAW_CANDIDATES = [ROOT / "data/raw/oulad", ROOT / "data/raw/raw/oulad"]
PROCESSED = ROOT / "data/processed"


def main() -> None:
    raw = next((path for path in RAW_CANDIDATES if (path / "studentInfo.csv").is_file()), None)
    if raw is None:
        raise FileNotFoundError(f"OULAD source folder missing; checked {RAW_CANDIDATES}")
    manifest = create_source_manifest(raw, PROCESSED / "source_manifest.json")
    data, sequences = build_student_features(raw)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    data.to_csv(PROCESSED / "oulad_early_features.csv.gz", index=False, compression="gzip")
    sequences.to_json(PROCESSED / "oulad_weekly_sequences.jsonl", orient="records", lines=True)
    output = PROCESSED / "student_training_dataset.csv"
    rows = write_canonical_training_dataset(data, sequences, output)
    print(f"source_snapshot_sha256={manifest['snapshot_sha256']}")
    print(f"canonical_student_course_rows={rows}")
    print(f"feature_version={data.attrs.get('feature_version', 'oulad-early-risk-v2')}")
    print(f"canonical_dataset={output.relative_to(ROOT)}")
    print("database_writes=0")
    print("live_enrollment_numbers_assigned=0")


if __name__ == "__main__":
    main()
