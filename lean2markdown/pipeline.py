"""End-to-end conversion pipeline for Lean2Markdown."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .generators.html_gen import generate_html
from .generators.latex_gen import generate_latex
from .generators.markdown_gen import generate_markdown
from .ir import ConversionWarning, DocumentIR
from .lean_bridge_client import enrich_with_lean4
from .parser import parse_lean_source


@dataclass
class ConversionConfig:
    """Configuration options controlling parsing, proof rendering, and output formatting."""

    format: str = "markdown"  # "markdown", "html", "latex"
    proof_mode: str = "human"  # "statement", "human", "source"
    include_source: bool = False
    include_imports: bool = False
    include_definitions: bool = True
    include_theorems: bool = True
    number_theorems: bool = True
    show_types: bool = True
    show_docstrings: bool = True
    show_comments: bool = True
    strict: bool = False
    verbose: bool = False
    backend: str = "auto"  # "auto", "lean", "parser"
    title: Optional[str] = None


@dataclass
class ConversionResult:
    """Output bundle returned by `convert_source` and `convert_file`."""

    output: str
    ir: DocumentIR
    warnings: List[ConversionWarning] = field(default_factory=list)
    backend_used: str = "parser"


def convert_source(
    source: str,
    source_name: str = "<stdin>",
    config: Optional[ConversionConfig] = None,
) -> ConversionResult:
    """Converts Lean 4 source text into Markdown, HTML, or LaTeX according to `config`."""
    cfg = config or ConversionConfig()
    ir = parse_lean_source(source, source_name=source_name)

    if cfg.backend in ("auto", "lean"):
        enrich_with_lean4(ir, source, strict=(cfg.backend == "lean"))

    if cfg.format == "markdown":
        rendered = generate_markdown(ir, cfg)
    elif cfg.format == "html":
        rendered = generate_html(ir, cfg)
    elif cfg.format == "latex":
        rendered = generate_latex(ir, cfg)
    else:
        raise ValueError(f"Unsupported output format: {cfg.format!r}. Use 'markdown', 'html', or 'latex'.")

    return ConversionResult(
        output=rendered,
        ir=ir,
        warnings=list(ir.warnings),
        backend_used=ir.backend,
    )


def convert_file(
    filepath: str,
    config: Optional[ConversionConfig] = None,
) -> ConversionResult:
    """Reads a `.lean` file from disk and converts it."""
    path = Path(filepath)
    if not path.is_file():
        raise FileNotFoundError(f"Lean file not found: {filepath}")
    source = path.read_text(encoding="utf-8")
    return convert_source(source, source_name=path.name, config=config)
