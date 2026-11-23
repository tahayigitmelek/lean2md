# Lean2Markdown (`lean2md`)

**Lean2Markdown** is a parser-based CLI tool that analyzes Lean 4 source code step by step and converts formal proofs, definitions, theorems, lemmas, structures, and comments into readable **Markdown + LaTeX** documentation (plus standalone **HTML/KaTeX** and compilable **LaTeX `.tex`**).

Instead of fragile regex replacements, Lean2Markdown lexes and parses Lean 4 declarations, nested comments, `calc` chains, tactic blocks, and mathematical expressions into a typed Intermediate Representation (`DocumentIR` + `MathExpr` AST). When Lean 4 (`lean`) is installed locally, it also integrates with Lean 4's native elaboration API via `lean_bridge/Lean2MdExtractor.lean`.

## Features

- **Broad Lean 4 & Mathlib4 Coverage:** `import`, `public import`, `module`, `namespace`/`end`, `section`/`end`, `open`, `variable`, `universe`, `def`, `theorem`, `lemma`, `example`, `structure`, `class`, `inductive`, `instance`, `axiom`, `opaque`, `abbrev`, `notation`, `infix*`, `prefix`, `postfix`, `where`, `let`, `have`, `show`, `suffices`, `fun`, `match`, `if`, `calc`, and `by` tactic blocks.
- **Complete Comment & Docstring Preservation:** Preserves module docstrings (`/-! ... -/`), declaration docstrings (`/-- ... -/`), nested block comments (`/- ... -/`), and leading/inline line comments (`-- ...`) right next to their corresponding proof steps.
- **AST-Based Mathematical LaTeX Rendering:** Recursive-descent + Pratt expression parser handles operator precedence, quantifiers (`∀`, `∃`), set-builder notation (`{x ∈ S | P x}`), big operators (`∑`, `∏`, `∫`), derivatives (`deriv`), limits (`Tendsto`), matrices, lambdas (`↦`), dependent types (`(x : α) → β x`), postfix inverses (`a⁻¹`), numeric projections (`h.1`, `h.2`), and Unicode subscripts.
- **Three Proof Rendering Modes:**
  - `statement` (**Mode A**): Formal statement in LaTeX only.
  - `human` (**Mode B**, default): Step-by-step mathematical walkthrough of supported tactics (`rfl`, `simp`, `ring`, `linarith`, `omega`, `rw`, `nth_rw`, `induction`, `cases`, `have`, `calc`, etc.) without ever fabricating reasoning for unknown tactics.
  - `source` (**Mode C**): Original Lean 4 proof in a fenced `lean` code block beneath the statement.
- **Folder-to-Folder Bash Workflow:** Drop `.lean` files into `input/` (including nested subfolders) and run `python3 lean2md.py` to generate mirrored documentation in `output/`.
- **Accuracy-First Safeguards:** Never silently alters mathematical meaning; emits structured warnings (`--verbose`, `--strict`) and safely falls back to raw Lean code blocks on unsupported macros or malformed syntax.

## Project Structure

```text
lean2md/
├── lean2md.py                 # Main bash/CLI entry point (defaults to input/ -> output/)
├── input/                     # Place your .lean files here (supports nested subfolders)
├── output/                    # Generated .md / .html / .tex outputs mirror input/
├── lean2markdown/             # Core Python package (zero external dependencies)
│   ├── ir.py                  # DocumentIR, Declaration, ProofStep, and MathExpr AST nodes
│   ├── lexer.py               # Lean 4 tokenizer (nested comments, Unicode, projections)
│   ├── expr_parser.py         # Recursive-descent + Pratt expression parser
│   ├── latex_renderer.py      # MathExpr -> LaTeX renderer with safe fallbacks
│   ├── tactic_analyzer.py     # Step-by-step tactic & calc chain analyzer
│   ├── parser.py              # Full Lean 4 file & declaration parser
│   ├── lean_bridge_client.py  # Native Lean 4 elaboration bridge client
│   ├── pipeline.py            # End-to-end conversion orchestrator
│   ├── cli.py                 # Command-line interface
│   └── generators/            # Markdown, HTML (KaTeX), and LaTeX (.tex) generators
├── lean_bridge/               # Optional native Lean 4 Lake bridge (Lean.Elab.Frontend)
├── tests/                     # Self-contained automated unit & CLI test suite
├── docs/ARCHITECTURE.md       # System architecture documentation
├── .github/workflows/ci.yml   # GitHub Actions CI workflow
├── pyproject.toml             # Packaging metadata (`lean2md` console script)
├── CONTRIBUTING.md            # Contribution guidelines
└── LICENSE                    # MIT License
```

## Installation

Requires **Python 3.9+** with **no external Python dependencies**. Lean 4 (`lean`/`lake`) is optional and automatically detected when present on `PATH`.

```bash
# Option 1: Run directly with Python (no install required)
python3 lean2md.py

# Option 2: Install editable package to expose `lean2md` globally
pip install -e .
```

## Usage (Bash / CLI)

```bash
# 1. Default folder mode: converts all .lean files in ./input/ into ./output/
python3 lean2md.py

# 2. Custom input/output folders (preserves nested subfolder structure)
python3 lean2md.py -i input -o output

# 3. Single file conversion
python3 lean2md.py input/my_proofs.lean -o output/my_proofs.md

# 4. Choose proof mode: statement | human | source
python3 lean2md.py -i input -o output --proof-mode statement
python3 lean2md.py -i input -o output --proof-mode human
python3 lean2md.py -i input -o output --proof-mode source

# 5. Export HTML (with KaTeX) or compilable LaTeX (.tex)
python3 lean2md.py input/my_proofs.lean --format html -o output/my_proofs.html
python3 lean2md.py input/my_proofs.lean --format latex -o output/my_proofs.tex

# 6. Pipe from stdin
cat input/my_proofs.lean | python3 lean2md.py - --proof-mode human

# 7. Strict CI mode (exits with code 2 on any warning) + verbose diagnostics
python3 lean2md.py input/my_proofs.lean --strict --verbose -o output/my_proofs.md
```

### CLI Options

| Flag | Description |
| :--- | :--- |
| `-i, --input PATH` | Input `.lean` file or folder (defaults to `./input` when run with no arguments). |
| `-o, --output PATH` | Output file or folder (defaults to `./output` in folder mode, else stdout). |
| `--proof-mode {statement,human,source}` | Proof representation mode (default: `human`). |
| `--format {markdown,html,latex}` | Output format (default: `markdown`). |
| `--include-source` | Append an `Original Lean Source` section at the end. |
| `--include-imports` | Include imports, opened namespaces, universes, and variables. |
| `--include-definitions` / `--no-definitions` | Include or omit definitions, structures, classes, and inductive types. |
| `--include-theorems` / `--no-theorems` | Include or omit theorems, lemmas, and examples. |
| `--number-theorems` / `--no-number-theorems` | Toggle sequential numbering of declarations. |
| `--show-types` / `--no-show-types` | Toggle type annotations on definitions. |
| `--show-docstrings` / `--no-docstrings` | Toggle docstrings and module docs. |
| `--no-comments` | Omit inline and leading Lean comments. |
| `--backend {auto,lean,parser}` | Select Lean 4 elaborator bridge or pure AST parser. |
| `--strict` | Exit with status `2` if any conversion warnings are emitted. |
| `--verbose` | Print warnings to stderr and append a `Conversion Warnings` section. |

## Before & After Example

### Input (Lean 4)

```lean
/-- Square of a sum on integers, proved step-by-step via a `calc` chain. -/
lemma square_sum (a b : ℤ) : (a + b) ^ 2 = a ^ 2 + 2 * a * b + b ^ 2 := by
  calc
    -- Expand the square as a product
    (a + b) ^ 2 = (a + b) * (a + b) := by ring
    _ = a ^ 2 + 2 * a * b + b ^ 2 := by ring -- Collect like terms
```

### Output (Markdown + LaTeX)

```markdown
### Lemma 1: Square Sum (`Arithmetic.square_sum`)

Square of a sum on integers, proved step-by-step via a `calc` chain.

For all integers \(a, b\),

\[
(a + b)^{2} = a^{2} + 2 \cdot a \cdot b + b^{2}
\]

**Proof.**

1. By the following chain of equalities/inequalities:

\[
\begin{aligned}
(a + b)^{2} &\; = \; (a + b) \cdot (a + b) && \text{(by } \mathrm{ring} \text{)} \\
&\; = \; a^{2} + 2 \cdot a \cdot b + b^{2} && \text{(by } \mathrm{ring} \text{)}
\end{aligned}
\]
   > *Comment (L27):* Expand the square as a product
   > *Comment (L29):* Collect like terms
```

Drop any `.lean` files into `input/` and run `python3 lean2md.py` to generate corresponding documentation in `output/`.

## Testing

```bash
python3 -m unittest discover -s tests -v
```

## Documentation & Contributing

- Architecture & pipeline details: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- Contributing guide: [`CONTRIBUTING.md`](CONTRIBUTING.md)
- License: [`LICENSE`](LICENSE) (MIT)
