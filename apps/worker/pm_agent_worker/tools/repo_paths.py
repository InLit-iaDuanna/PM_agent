from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def research_core_data_path(filename: str) -> Path:
    return repo_root() / "packages" / "research-core" / "data" / filename


def config_defaults_path(filename: str) -> Path:
    return repo_root() / "packages" / "config" / "defaults" / filename
