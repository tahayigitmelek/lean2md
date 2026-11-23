# Contributing to Lean2Markdown

Contributions are welcome! To keep the mathematical output faithful and maintainable:

## Development Setup

```bash
git clone <repo-url>
cd lean2md
python3 -m unittest discover -s tests -v
```

## Adding Support for New Tactics or Math Notation

1. **Expression syntax**: Add new AST nodes to `lean2markdown/ir.py`, parse them in `lean2markdown/expr_parser.py`, and render them in `lean2markdown/latex_renderer.py`.
2. **Tactics**: Add verified mathematical templates to `TACTIC_TEMPLATES` in `lean2markdown/tactic_analyzer.py`. Never fabricate proof reasoning for opaque tactics.
3. **Lean 4 Bridge**: Extend `lean_bridge/Lean2MdExtractor.lean` and map new fields in `lean2markdown/lean_bridge_client.py`.
4. **Tests**: Add unit and end-to-end tests in `tests/test_lean2markdown.py` verifying both the LaTeX output and warning/fallback behavior.
