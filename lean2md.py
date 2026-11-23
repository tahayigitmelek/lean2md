#!/usr/bin/env python3
"""Lean2Markdown CLI entry point.

Usage:
  python3 lean2md.py                       # Default: ./input -> ./output
  python3 lean2md.py -i input -o output    # Batch folder-to-folder conversion
  python3 lean2md.py file.lean -o out.md   # Single file conversion
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lean2markdown.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
