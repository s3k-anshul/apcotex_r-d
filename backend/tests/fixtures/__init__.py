"""Shared test fixtures for pipeline redesign tests."""
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent


def load_fixture(name: str) -> dict | list:
    """Load a JSON fixture by filename (with or without .json suffix)."""
    import json

    path = FIXTURES_DIR / (name if name.endswith(".json") else f"{name}.json")
    with path.open(encoding="utf-8") as f:
        return json.load(f)
