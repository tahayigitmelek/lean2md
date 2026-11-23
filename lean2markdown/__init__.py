"""Lean2Markdown: Parser-based Lean 4 to Markdown + LaTeX mathematical documentation tool."""

__version__ = "1.0.0"

from .pipeline import ConversionConfig, ConversionResult, convert_file, convert_source

__all__ = [
    "__version__",
    "ConversionConfig",
    "ConversionResult",
    "convert_file",
    "convert_source",
]
