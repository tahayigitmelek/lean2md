"""Allow running Lean2Markdown via `python3 -m lean2markdown`."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
