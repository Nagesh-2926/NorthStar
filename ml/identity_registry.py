"""Allocate application enrollment numbers without assigning them to OULAD IDs.

The legacy registry may contain historical OULAD digests and application-account
digests. It is read only as a compatibility source: historical keys are never
allocated or exported as application identities. New assignments are stored in a
separate application-only registry.
"""
from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path

FIRST_ENROLLMENT_NUMBER = 2403031500001
APPLICATION_REGISTRY_VERSION = 1
LEGACY_REGISTRY_NAME = "enrollment_mapping_registry.json"
LEGACY_REGISTRY_PATH = Path(__file__).resolve().parents[1] / "data" / "processed" / LEGACY_REGISTRY_NAME


def _application_key_digest(student_id: object) -> str:
    key = f"application-account:{student_id}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


@contextmanager
def _registry_lock(path: Path):
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock_file:
        if os.name == "nt":
            import msvcrt
            lock_file.seek(0)
            if lock_file.read(1) == b"":
                lock_file.write(b"\0")
                lock_file.flush()
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _read_mappings(path: Path, *, expected_version: int, namespace: str | None = None) -> dict[str, str]:
    if not path.exists():
        return {}
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("registry_version") != expected_version:
        raise ValueError(f"Unsupported enrollment registry version in {path.name}")
    if namespace is not None and document.get("namespace") != namespace:
        raise ValueError(f"Enrollment registry namespace mismatch in {path.name}")
    mappings = document.get("mappings")
    if not isinstance(mappings, dict):
        raise ValueError(f"Enrollment registry mappings are invalid in {path.name}")
    result = {str(key): str(value) for key, value in mappings.items()}
    values = list(result.values())
    if len(values) != len(set(values)):
        raise ValueError(f"Enrollment registry contains duplicate values in {path.name}")
    if any(not value.isdigit() or int(value) < FIRST_ENROLLMENT_NUMBER for value in values):
        raise ValueError(f"Enrollment registry contains an invalid number in {path.name}")
    return result


def _write_application_registry(path: Path, mappings: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "registry_version": APPLICATION_REGISTRY_VERSION,
        "namespace": "application-account",
        "mappings": mappings,
    }
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary_path, path)


def allocate_application_enrollment_number(
    student_id: object,
    registry_path: str | Path,
    legacy_registry_path: str | Path | None = None,
) -> str:
    """Return a stable app-account number, preserving exact legacy app assignments.

    Historical OULAD registry values contribute only a high-water mark so new
    application numbers cannot collide with previously issued identifiers. A
    legacy number is reused only when the digest matches this exact namespaced
    application account key.
    """
    path = Path(registry_path)
    legacy_path = Path(legacy_registry_path) if legacy_registry_path else LEGACY_REGISTRY_PATH
    digest = _application_key_digest(student_id)
    with _registry_lock(path):
        mappings = _read_mappings(
            path,
            expected_version=APPLICATION_REGISTRY_VERSION,
            namespace="application-account",
        )
        if digest in mappings:
            return mappings[digest]

        legacy = _read_mappings(legacy_path, expected_version=1)
        legacy_number = legacy.get(digest)
        if legacy_number is not None:
            mappings[digest] = legacy_number
        else:
            high_watermark = max(
                [FIRST_ENROLLMENT_NUMBER - 1]
                + [int(value) for value in legacy.values()]
                + [int(value) for value in mappings.values()]
            )
            mappings[digest] = str(high_watermark + 1)
        _write_application_registry(path, mappings)
        return mappings[digest]
