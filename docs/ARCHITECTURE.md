# Lean2Markdown Architecture

Lean2Markdown separates Lean 4 parsing/elaboration from mathematical rendering and output generation through a six-layer CLI pipeline.

## Pipeline Overview

```text
input/*.lean / stdin
   │
   ▼
[1. Input Layer]          lean2md.py, lean2markdown/cli.py, pipeline.py
   │
   ▼
[2. Parser Layer]         lean2markdown/lexer.py, parser.py, tactic_analyzer.py
   │                      (Tokenizer with nested comments & numeric projections,
   │                       declaration boundaries, namespaces/sections, calc chains)
   ▼
[3. Semantic / Lean 4]    lean2markdown/lean_bridge_client.py
   │                      lean_bridge/Lean2MdExtractor.lean (Lean.Elab.Frontend)
   │                      (Optional native elaboration enrichment when `lean` is installed)
   ▼
[4. Math IR & Rendering]  lean2markdown/ir.py, expr_parser.py, latex_renderer.py
   │                      (Pratt + recursive-descent MathExpr AST with precedence,
   │                       safe RawFallbackExpr on unsupported syntax)
   ▼
[5. Output Generators]    lean2markdown/generators/{markdown_gen,html_gen,latex_gen}.py
   │
   ▼
[6. Output Layer]         output/*.md / .html / .tex (preserving subfolder layout) or stdout
```

## Key Design Principles

1. **Intermediate Representation (`DocumentIR` & `MathExpr`)**: Declarations, binders, comments, proof steps, and mathematical expressions are represented as typed dataclasses (`lean2markdown/ir.py`) rather than manipulated via regex replacements.
2. **Mathematical Fidelity First**: If an expression has unbalanced delimiters, meta/macro syntax, or unparseable trailing tokens, `expr_parser.py` emits a `ConversionWarning` and returns `RawFallbackExpr`, rendering a raw Lean code block rather than misleading LaTeX.
3. **Honest Proof Explanations**: `tactic_analyzer.py` maps recognized tactics (`rfl`, `simp`, `ring`, `linarith`, `omega`, `induction`, `calc`, etc.) to accurate mathematical descriptions and preserves every leading/inline comment. Unknown tactics emit `UNKNOWN_TACTIC` and explicitly state that manual explanation is required.
