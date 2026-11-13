"""Write SECRET_KEY into an env file when missing. Never prints the value."""
from __future__ import annotations

import argparse
import re
import secrets
import sys
from pathlib import Path

_PLACEHOLDERS = {
    "",
    "REPLACE_WITH_GENERATED_KEY",
    "changeme",
    "your-secret-key-change-in-production",
}

_KEY_LINE = re.compile(r"^SECRET_KEY=(.*)$")


def current_secret(text: str) -> str | None:
    """Return the SECRET_KEY value if the file has that assignment, else None."""
    found = None
    for line in text.splitlines():
        match = _KEY_LINE.match(line)
        if match:
            found = match.group(1).strip().strip("'").strip('"')
    return found


def needs_secret(value: str | None) -> bool:
    if value is None:
        return True
    return value in _PLACEHOLDERS


def apply(text: str, key: str) -> str:
    lines = text.splitlines(keepends=True)
    replaced = False
    out: list[str] = []
    for line in lines:
        raw = line[:-1] if line.endswith("\n") else line
        if _KEY_LINE.match(raw):
            if not replaced:
                out.append(f"SECRET_KEY={key}\n")
                replaced = True
            continue
        out.append(line if line.endswith("\n") else line + "\n")
    if not replaced:
        if out and not out[-1].endswith("\n"):
            out[-1] += "\n"
        out.append(f"SECRET_KEY={key}\n")
    return "".join(out)


def ensure(path: Path) -> str:
    """Returns 'generated' or 'kept'. Never returns the key."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    value = current_secret(text)
    if not needs_secret(value):
        return "kept"
    key = secrets.token_hex(32)
    path.write_text(apply(text, key), encoding="utf-8")
    return "generated"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Garante SECRET_KEY no .env sem imprimir o valor.")
    parser.add_argument("env_file")
    args = parser.parse_args(argv)
    status = ensure(Path(args.env_file))
    if status == "generated":
        print(f"SECRET_KEY gerado em {args.env_file} (valor não exibido).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
