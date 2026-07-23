#!/usr/bin/env python3
"""Validate and write the release identity embedded in the Debian package."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


VERSION_RE = re.compile(r"^\d+(?:\.\d+)+$")
TIMESTAMP_RE = re.compile(r"^\d{14}$")
REVISION_RE = re.compile(r"^[0-9a-f]+$")


def validate_versions(
    *,
    channel: str,
    debian_version: str,
    python_version: str,
    build_timestamp: str,
    source_revision: str,
) -> None:
    if channel == "stable":
        if not VERSION_RE.fullmatch(debian_version) or python_version != debian_version:
            raise ValueError("stable Debian and Python versions must be the same numeric dotted version")
        return

    if not TIMESTAMP_RE.fullmatch(build_timestamp):
        raise ValueError("nightly build timestamp must contain exactly 14 UTC digits")
    if not REVISION_RE.fullmatch(source_revision):
        raise ValueError("nightly source revision must be a lowercase hexadecimal Git revision")

    debian_match = re.fullmatch(
        rf"(\d+(?:\.\d+)+)~nightly\.{build_timestamp}\.g{source_revision}",
        debian_version,
    )
    if not debian_match:
        raise ValueError("Debian version does not match the declared nightly build identity")
    expected_python = f"{debian_match.group(1)}.dev{build_timestamp}+g{source_revision}"
    if python_version != expected_python:
        raise ValueError("Python version does not match the declared nightly build identity")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--channel", choices=("nightly", "stable"), required=True)
    parser.add_argument("--debian-version", required=True)
    parser.add_argument("--python-version", required=True)
    parser.add_argument("--build-timestamp", default="")
    parser.add_argument("--source-revision", default="")
    parser.add_argument("--expected-debian-version", default="")
    parser.add_argument("--expected-python-version", default="")
    args = parser.parse_args()

    if args.expected_debian_version and args.debian_version != args.expected_debian_version:
        parser.error("Debian changelog version differs from the orchestrator release identity")
    if args.expected_python_version and args.python_version != args.expected_python_version:
        parser.error("pyproject version differs from the orchestrator release identity")

    try:
        validate_versions(
            channel=args.channel,
            debian_version=args.debian_version,
            python_version=args.python_version,
            build_timestamp=args.build_timestamp,
            source_revision=args.source_revision,
        )
    except ValueError as error:
        parser.error(str(error))

    metadata = {
        "schema": 1,
        "channel": args.channel,
        "debian_version": args.debian_version,
        "python_version": args.python_version,
        "build_timestamp": args.build_timestamp,
        "source_revision": args.source_revision,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
