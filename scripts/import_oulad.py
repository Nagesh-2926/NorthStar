"""Deprecated safety guard for the former historical-to-live database importer."""


def main() -> None:
    raise SystemExit(
        "Historical OULAD rows are not live students and are no longer imported into "
        "application Student/Enrollment tables. To rebuild the historical canonical "
        "feature export without database writes, run: "
        "python -m ml.features.export_canonical"
    )


if __name__ == "__main__":
    main()
