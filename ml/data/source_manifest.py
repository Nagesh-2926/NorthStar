"""Content-based source dataset identity; raw CSVs are read-only."""
from __future__ import annotations
import hashlib, json
from pathlib import Path


def create_source_manifest(raw_dir: str | Path, output: str | Path | None = None) -> dict:
    root = Path(raw_dir)
    entries = []
    for path in sorted(root.glob("*.csv")):
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                digest.update(block)
        entries.append({"file": path.name, "bytes": path.stat().st_size, "sha256": digest.hexdigest()})
    if len(entries) != 7:
        raise ValueError(f"Expected seven OULAD CSVs; found {len(entries)} under {root}")
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    manifest = {"dataset": "OULAD", "snapshot_sha256": hashlib.sha256(canonical).hexdigest(),
                "files": entries}
    if output is not None:
        Path(output).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest
