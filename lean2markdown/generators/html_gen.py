"""Standalone HTML + KaTeX Generator for Lean2Markdown."""

import html
import re
from typing import TYPE_CHECKING, List

from ..ir import DocumentIR
from .markdown_gen import generate_markdown

if TYPE_CHECKING:
    from ..pipeline import ConversionConfig


def _md_to_html_body(md: str) -> str:
    """Converts our structured Markdown + LaTeX output into semantic HTML while preserving math delimiters."""
    lines = md.splitlines()
    out: List[str] = []
    in_code = False
    code_lang = ""
    code_buf: List[str] = []
    in_math_block = False
    math_buf: List[str] = []
    in_list = False
    list_tag = "ul"
    in_table = False

    def flush_list() -> None:
        nonlocal in_list
        if in_list:
            out.append(f"</{list_tag}>")
            in_list = False

    def flush_table() -> None:
        nonlocal in_table
        if in_table:
            out.append("</tbody></table>")
            in_table = False

    def format_inline(text: str) -> str:
        # Preserve inline math \( ... \) verbatim while escaping HTML outside math
        parts = re.split(r"(\\\(.*?\\\))", text)
        rendered: List[str] = []
        for idx, part in enumerate(parts):
            if idx % 2 == 1:
                rendered.append(part)
                continue
            esc = html.escape(part)
            esc = re.sub(r"`([^`]+)`", r"<code>\1</code>", esc)
            esc = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", esc)
            esc = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", esc)
            rendered.append(esc)
        return "".join(rendered)

    i = 0
    while i < len(lines):
        ln = lines[i]

        if in_code:
            if ln.strip().startswith("```"):
                out.append(
                    f'<pre><code class="language-{html.escape(code_lang)}">'
                    + html.escape("\n".join(code_buf))
                    + "</code></pre>"
                )
                in_code = False
                code_buf = []
            else:
                code_buf.append(ln)
            i += 1
            continue

        if in_math_block:
            if ln.strip() == "\\]":
                out.append('<div class="math-display">\\[\n' + "\n".join(math_buf) + "\n\\]</div>")
                in_math_block = False
                math_buf = []
            else:
                math_buf.append(ln)
            i += 1
            continue

        stripped = ln.strip()
        if not stripped:
            flush_list()
            flush_table()
            i += 1
            continue

        if stripped.startswith("```"):
            flush_list()
            flush_table()
            in_code = True
            code_lang = stripped[3:].strip() or "text"
            code_buf = []
            i += 1
            continue

        if stripped == "\\[":
            flush_list()
            flush_table()
            in_math_block = True
            math_buf = []
            i += 1
            continue

        # Table
        if stripped.startswith("|") and stripped.endswith("|"):
            flush_list()
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if not in_table:
                out.append("<table><thead><tr>" + "".join(f"<th>{format_inline(c)}</th>" for c in cells) + "</tr></thead><tbody>")
                in_table = True
                # Skip separator row if present
                if i + 1 < len(lines) and re.match(r"^\|[\s:\-|]+\|$", lines[i + 1].strip()):
                    i += 1
            else:
                out.append("<tr>" + "".join(f"<td>{format_inline(c)}</td>" for c in cells) + "</tr>")
            i += 1
            continue
        else:
            flush_table()

        # Headings
        hm = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if hm:
            flush_list()
            lvl = len(hm.group(1))
            out.append(f"<h{lvl}>{format_inline(hm.group(2))}</h{lvl}>")
            i += 1
            continue

        # Blockquote
        if stripped.startswith("> "):
            flush_list()
            out.append(f"<blockquote>{format_inline(stripped[2:])}</blockquote>")
            i += 1
            continue

        # Ordered / unordered list
        om = re.match(r"^\d+\.\s+(.*)$", stripped)
        um = re.match(r"^[-*]\s+(.*)$", stripped)
        if om:
            if not in_list or list_tag != "ol":
                flush_list()
                out.append("<ol>")
                in_list = True
                list_tag = "ol"
            out.append(f"<li>{format_inline(om.group(1))}</li>")
            i += 1
            continue
        if um:
            if not in_list or list_tag != "ul":
                flush_list()
                out.append("<ul>")
                in_list = True
                list_tag = "ul"
            out.append(f"<li>{format_inline(um.group(1))}</li>")
            i += 1
            continue

        flush_list()
        out.append(f"<p>{format_inline(stripped)}</p>")
        i += 1

    flush_list()
    flush_table()
    return "\n".join(out)


def generate_html(doc: DocumentIR, cfg: "ConversionConfig") -> str:
    """Generates a self-contained HTML document with KaTeX math rendering."""
    md = generate_markdown(doc, cfg)
    body = _md_to_html_body(md)
    title = html.escape(cfg.title or f"Mathematical Documentation: {doc.source_name}")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title}</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css" />
  <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>
  <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js"
    onload="renderMathInElement(document.body, {{delimiters: [{{left: '\\\\[', right: '\\\\]', display: true}}, {{left: '\\\\(', right: '\\\\)', display: false}}]}});"></script>
  <style>
    :root {{ color-scheme: light dark; }}
    body {{
      font-family: 'Georgia', 'Cambria', serif;
      max-width: 880px;
      margin: 2.5rem auto;
      padding: 0 1.5rem;
      line-height: 1.7;
      color: #1f2937;
      background: #ffffff;
    }}
    @media (prefers-color-scheme: dark) {{
      body {{ color: #e5e7eb; background: #0f172a; }}
      code, pre {{ background: #1e293b; color: #f8fafc; }}
      blockquote {{ border-left-color: #60a5fa; background: #1e293b; }}
      table, th, td {{ border-color: #334155; }}
    }}
    h1, h2, h3 {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin-top: 1.8rem; }}
    h1 {{ border-bottom: 2px solid #e5e7eb; padding-bottom: 0.4rem; }}
    code {{ font-family: 'SFMono-Regular', Consolas, monospace; font-size: 0.9em; background: #f3f4f6; padding: 0.15rem 0.35rem; border-radius: 4px; }}
    pre {{ background: #f8fafc; padding: 1rem; border-radius: 8px; overflow-x: auto; border: 1px solid #e2e8f0; }}
    pre code {{ background: transparent; padding: 0; }}
    blockquote {{ border-left: 4px solid #3b82f6; margin: 1rem 0; padding: 0.5rem 1rem; background: #eff6ff; border-radius: 0 6px 6px 0; }}
    .math-display {{ overflow-x: auto; padding: 0.5rem 0; }}
    table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
    th, td {{ border: 1px solid #d1d5db; padding: 0.5rem 0.75rem; text-align: left; }}
  </style>
</head>
<body>
{body}
</body>
</html>
"""
