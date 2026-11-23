"""Command-Line Interface for Lean2Markdown (`lean2md`)."""

import argparse
import glob
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from . import __version__
from .pipeline import ConversionConfig, convert_file, convert_source


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lean2md",
        description="Convert Lean 4 source code into mathematically accurate Markdown, HTML, or LaTeX documentation.",
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help="Input .lean file(s), folder(s), glob pattern(s), or '-' for stdin. Defaults to ./input if present.",
    )
    parser.add_argument(
        "-i", "--input",
        dest="input_dir",
        help="Input file or folder containing .lean files (e.g. ./input).",
    )
    parser.add_argument(
        "-o", "--output",
        help="Output file path (single file) or output folder (default: ./output when using folder mode, else stdout).",
    )
    parser.add_argument(
        "--proof-mode",
        choices=["statement", "human", "source"],
        default="human",
        help="Proof rendering mode: 'statement' (Mode A), 'human' (Mode B, default), or 'source' (Mode C).",
    )
    parser.add_argument(
        "--format",
        choices=["markdown", "html", "latex"],
        default="markdown",
        help="Output format (default: markdown).",
    )
    parser.add_argument(
        "--include-source",
        action="store_true",
        help="Append the full original Lean source code section at the end of the document.",
    )
    parser.add_argument(
        "--include-imports",
        action="store_true",
        help="Include an Imports, Opened Namespaces, Universes, and Variables section.",
    )
    parser.add_argument(
        "--include-definitions",
        dest="include_definitions",
        action="store_true",
        default=True,
        help="Include definitions, structures, classes, and inductive types (default: enabled).",
    )
    parser.add_argument(
        "--no-definitions",
        dest="include_definitions",
        action="store_false",
        help="Omit definitions and type declarations.",
    )
    parser.add_argument(
        "--include-theorems",
        dest="include_theorems",
        action="store_true",
        default=True,
        help="Include theorems, lemmas, and examples (default: enabled).",
    )
    parser.add_argument(
        "--no-theorems",
        dest="include_theorems",
        action="store_false",
        help="Omit theorems, lemmas, and examples.",
    )
    parser.add_argument(
        "--number-theorems",
        dest="number_theorems",
        action="store_true",
        default=True,
        help="Number definitions, theorems, and lemmas sequentially (default: enabled).",
    )
    parser.add_argument(
        "--no-number-theorems",
        dest="number_theorems",
        action="store_false",
        help="Disable sequential numbering.",
    )
    parser.add_argument(
        "--show-types",
        dest="show_types",
        action="store_true",
        default=True,
        help="Show type annotations on definitions (default: enabled).",
    )
    parser.add_argument(
        "--no-show-types",
        dest="show_types",
        action="store_false",
        help="Hide type annotations on definitions.",
    )
    parser.add_argument(
        "--show-docstrings",
        dest="show_docstrings",
        action="store_true",
        default=True,
        help="Include Lean docstrings and module docs (default: enabled).",
    )
    parser.add_argument(
        "--no-docstrings",
        dest="show_docstrings",
        action="store_false",
        help="Hide Lean docstrings.",
    )
    parser.add_argument(
        "--no-comments",
        dest="show_comments",
        action="store_false",
        default=True,
        help="Hide inline and leading Lean comments.",
    )
    parser.add_argument(
        "--backend",
        choices=["auto", "lean", "parser"],
        default="auto",
        help="Analysis backend: 'auto' (use Lean 4 if installed, else AST parser), 'lean', or 'parser'.",
    )
    parser.add_argument(
        "--title",
        help="Custom document title.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with non-zero status if any conversion warnings are emitted.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print conversion diagnostics and include warnings in output.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def _expand_inputs(raw_inputs: List[str]) -> Tuple[List[Tuple[str, Optional[Path]]], bool]:
    """Expands files/folders/globs into list of (file_path, base_dir_or_None) and folder_mode flag."""
    expanded: List[Tuple[str, Optional[Path]]] = []
    folder_mode = False
    for item in raw_inputs:
        if item == "-":
            expanded.append(("-", None))
            continue
        p = Path(item)
        if p.is_dir():
            folder_mode = True
            for f in sorted(p.rglob("*.lean")):
                expanded.append((str(f), p))
        elif any(ch in item for ch in ("*", "?", "[")):
            for m in sorted(glob.glob(item, recursive=True)):
                expanded.append((m, None))
        else:
            expanded.append((item, None))
    return expanded, folder_mode


def _ext_for_format(fmt: str) -> str:
    return {"markdown": ".md", "html": ".html", "latex": ".tex"}[fmt]


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    cfg = ConversionConfig(
        format=args.format,
        proof_mode=args.proof_mode,
        include_source=args.include_source,
        include_imports=args.include_imports,
        include_definitions=args.include_definitions,
        include_theorems=args.include_theorems,
        number_theorems=args.number_theorems,
        show_types=args.show_types,
        show_docstrings=args.show_docstrings,
        show_comments=args.show_comments,
        strict=args.strict,
        verbose=args.verbose,
        backend=args.backend,
        title=args.title,
    )

    raw_inputs = list(args.inputs)
    if args.input_dir:
        raw_inputs.insert(0, args.input_dir)

    used_default_folders = False
    if not raw_inputs:
        default_in = Path("input")
        if default_in.is_dir():
            raw_inputs = [str(default_in)]
            used_default_folders = True
        elif not sys.stdin.isatty():
            raw_inputs = ["-"]
        else:
            parser.print_help()
            return 1

    inputs, folder_mode = _expand_inputs(raw_inputs)
    if not inputs:
        print(f"No .lean files found in {', '.join(raw_inputs)}.", file=sys.stderr)
        return 1

    output_arg = args.output
    if not output_arg and (folder_mode or used_default_folders):
        output_arg = "output"

    total_warnings = 0
    ext = _ext_for_format(cfg.format)

    # Single stdin or single non-folder file
    if len(inputs) == 1 and not folder_mode:
        inp, _ = inputs[0]
        try:
            if inp == "-":
                src = sys.stdin.read()
                res = convert_source(src, source_name="<stdin>", config=cfg)
            else:
                res = convert_file(inp, config=cfg)
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

        total_warnings += len(res.warnings)
        if args.verbose:
            print(f"[lean2md] Converted {inp} using backend '{res.backend_used}' ({len(res.warnings)} warnings).", file=sys.stderr)
            for w in res.warnings:
                print(f"  WARNING [{w.code}] L{w.line}: {w.message}", file=sys.stderr)

        if output_arg:
            out_path = Path(output_arg)
            if out_path.is_dir() or str(output_arg).endswith("/"):
                out_path.mkdir(parents=True, exist_ok=True)
                stem = "stdin" if inp == "-" else Path(inp).stem
                out_path = out_path / (stem + ext)
            else:
                out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(res.output, encoding="utf-8")
            if args.verbose:
                print(f"[lean2md] Wrote {out_path}", file=sys.stderr)
        else:
            sys.stdout.write(res.output)

        if args.strict and total_warnings > 0:
            return 2
        return 0

    # Folder mode or multiple input files -> write to output directory preserving nested structure
    out_dir = Path(output_arg) if output_arg else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    for inp, base_dir in inputs:
        try:
            res = convert_file(inp, config=cfg)
        except Exception as exc:
            print(f"Error converting {inp}: {exc}", file=sys.stderr)
            return 1

        total_warnings += len(res.warnings)
        if out_dir:
            inp_path = Path(inp)
            if base_dir is not None:
                rel = inp_path.relative_to(base_dir).with_suffix(ext)
                dest = out_dir / rel
            else:
                dest = out_dir / (inp_path.stem + ext)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(res.output, encoding="utf-8")
            if args.verbose or folder_mode:
                print(f"[lean2md] {inp} -> {dest} ({len(res.warnings)} warnings)", file=sys.stderr)
        else:
            sys.stdout.write(res.output)
            sys.stdout.write("\n")

    if args.strict and total_warnings > 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
