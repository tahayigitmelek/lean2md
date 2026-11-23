"""Lean 4 Native Elaboration Bridge Client.

Integrates with the Lean 4 Lake project in `lean_bridge/` whenever `lean` and `lake`
are installed on the system. Runs elaboration in a resource-limited subprocess and
enriches the parsed `DocumentIR` with elaborated types, resolved constant names, and
exact Prop-vs-definition classification.
"""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Optional

from .expr_parser import parse_math_expr
from .ir import ConversionWarning, DocumentIR

LEAN_BRIDGE_DIR = Path(__file__).resolve().parent.parent / "lean_bridge"


def find_lean_executable() -> Optional[str]:
    """Locates the `lean` executable, including standard `~/.elan/bin` locations."""
    found = shutil.which("lean")
    if found:
        return found
    for candidate in (
        Path.home() / ".elan" / "bin" / "lean",
        Path("/opt/homebrew/bin/lean"),
        Path("/usr/local/bin/lean"),
    ):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def find_lake_executable() -> Optional[str]:
    found = shutil.which("lake")
    if found:
        return found
    for candidate in (
        Path.home() / ".elan" / "bin" / "lake",
        Path("/opt/homebrew/bin/lake"),
        Path("/usr/local/bin/lake"),
    ):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def is_lean_available() -> bool:
    return find_lean_executable() is not None


def enrich_with_lean4(
    doc: DocumentIR,
    source_code: str,
    timeout_sec: int = 30,
    strict: bool = False,
) -> bool:
    """Attempts to elaborate `source_code` with Lean 4 and enrich `doc` in-place.

    Returns True if Lean 4 elaboration succeeded, False otherwise.
    """
    lean_exe = find_lean_executable()
    if not lean_exe:
        if strict:
            doc.warnings.append(
                ConversionWarning(
                    code="LEAN_NOT_INSTALLED",
                    message="Lean 4 (`lean`) was not found on PATH; used built-in AST parser backend.",
                )
            )
        return False

    extractor = LEAN_BRIDGE_DIR / "Lean2MdExtractor.lean"
    if not extractor.is_file():
        return False

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".lean", encoding="utf-8", delete=False
        ) as tmp:
            tmp.write(source_code)
            tmp_path = tmp.name

        cmd = [lean_exe, "--run", str(extractor), tmp_path]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            cwd=str(LEAN_BRIDGE_DIR),
        )
        if proc.returncode != 0:
            doc.warnings.append(
                ConversionWarning(
                    code="LEAN_ELAB_ERROR",
                    message=f"Lean 4 elaboration returned exit code {proc.returncode}: {proc.stderr.strip()[:200]}",
                )
            )
            return False

        payload = json.loads(proc.stdout)
        elab_map: Dict[str, dict] = {}
        for item in payload.get("declarations", []):
            name = item.get("name", "")
            if name:
                elab_map[name] = item
                if "." in name:
                    elab_map[name.rsplit(".", 1)[-1]] = item

        for decl in doc.declarations:
            match = elab_map.get(decl.qualified_name) or elab_map.get(decl.name)
            if not match:
                continue
            decl.elaborated = True
            if "isProp" in match:
                decl.is_proposition = bool(match["isProp"])
            elab_type = match.get("type", "").strip()
            if elab_type and not decl.return_type_raw:
                decl.return_type_raw = elab_type
                decl.return_type_ir, w = parse_math_expr(elab_type, decl.start_line)
                doc.warnings.extend(w)

        doc.backend = "lean4"
        return True
    except subprocess.TimeoutExpired:
        doc.warnings.append(
            ConversionWarning(
                code="LEAN_ELAB_TIMEOUT",
                message=f"Lean 4 elaboration timed out after {timeout_sec}s; using AST parser results.",
            )
        )
        return False
    except Exception as exc:
        doc.warnings.append(
            ConversionWarning(
                code="LEAN_BRIDGE_ERROR",
                message=f"Lean 4 bridge failed ({exc}); using AST parser results.",
            )
        )
        return False
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
