from pathlib import Path


def get_version() -> str:
    root = Path(__file__).resolve().parent.parent
    p = root / "VERSION"
    if p.is_file():
        return p.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    return "0.0.0"
