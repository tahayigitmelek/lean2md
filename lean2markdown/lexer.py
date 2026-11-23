"""Lean 4 Lexer with support for nested block comments, docstrings, Unicode operators, and line tracking."""

from dataclasses import dataclass
from typing import List, Tuple

from .ir import Comment, ConversionWarning


@dataclass
class Token:
    kind: str  # "IDENT", "NUMBER", "STRING", "CHAR", "OP", "LPAREN", "RPAREN", "LBRACE", "RBRACE", "LBRACK", "RBRACK", "COMMENT", "NEWLINE", "EOF"
    value: str
    line: int
    col: int
    end_line: int
    end_col: int


MULTI_CHAR_OPS = (
    ":=", "->", "<-", "<->", "=>", "<=", ">=", "!=", "/\\", "\\/",
    "&&", "||", "<;>", "::", "..", "++", "**", "![", "''", "<|", "|>", "+ᵥ", "?_", "⁻¹",
)

SINGLE_CHAR_DELIMS = {
    "(": "LPAREN",
    ")": "RPAREN",
    "{": "LBRACE",
    "}": "RBRACE",
    "[": "LBRACK",
    "]": "RBRACK",
    "⦃": "SLBRACE",
    "⦄": "SRBRACE",
    "⟨": "LANGLE",
    "⟩": "RANGLE",
    ",": "COMMA",
    ";": "SEMI",
    ":": "COLON",
    "|": "PIPE",
}

UNICODE_MATH_OPS = set(
    "∀∃∄¬∧∨→←↔⇒⇐⇔↦⊢⊨⊤⊥λ∈∉∋⊆⊂⊇⊃⊄∪∩⋃⋂∅∖≠≤≥≪≫≡≈≃≅∼∝∣∤∥⟂×÷±∓·•∘⊕⊗⊙⋆∞∑∏∫∂∇√‖⌊⌋⌈⌉"
)

ASCII_OP_CHARS = set("+-*/^=<>!~@&\\?.")


def _is_ident_start(ch: str) -> bool:
    if ch.isalpha() or ch == "_":
        return ch not in UNICODE_MATH_OPS
    return False


def _is_ident_continue(ch: str) -> bool:
    if ch in UNICODE_MATH_OPS:
        return False
    if ch.isalnum() or ch in ("_", "'", "′", "₀", "₁", "₂", "₃", "₄", "₅", "₆", "₇", "₈", "₉"):
        return True
    return False


def tokenize_lean(source: str) -> Tuple[List[Token], List[Comment], List[ConversionWarning]]:
    """Tokenizes Lean 4 source code while extracting all comments and reporting lexical errors."""
    tokens: List[Token] = []
    comments: List[Comment] = []
    warnings: List[ConversionWarning] = []

    i = 0
    n = len(source)
    line = 1
    col = 1

    while i < n:
        ch = source[i]

        # Newline
        if ch == "\n":
            tokens.append(Token("NEWLINE", "\n", line, col, line, col + 1))
            i += 1
            line += 1
            col = 1
            continue

        # Whitespace
        if ch in (" ", "\t", "\r"):
            i += 1
            col += 1
            continue

        # Line comment: -- ...
        if ch == "-" and i + 1 < n and source[i + 1] == "-":
            start_line, start_col = line, col
            start_i = i
            while i < n and source[i] != "\n":
                i += 1
                col += 1
            raw = source[start_i:i]
            text = raw[2:].strip()
            comments.append(Comment("line", text, raw, start_line, line, start_col - 1))
            tokens.append(Token("COMMENT", raw, start_line, start_col, line, col))
            continue

        # Block / Doc / Module-Doc comment: /- ... -/ (supports nesting!)
        if ch == "/" and i + 1 < n and source[i + 1] == "-":
            start_line, start_col = line, col
            start_i = i
            kind = "block"
            prefix_len = 2
            if i + 2 < n and source[i + 2] == "-":
                # Check that it's not `/- -/` or `/---`
                if i + 3 < n and source[i + 3] == "/":
                    kind = "block"
                else:
                    kind = "doc"
                    prefix_len = 3
            elif i + 2 < n and source[i + 2] == "!":
                kind = "module_doc"
                prefix_len = 3

            depth = 1
            i += 2
            col += 2
            while i < n and depth > 0:
                if source[i] == "/" and i + 1 < n and source[i + 1] == "-":
                    depth += 1
                    i += 2
                    col += 2
                elif source[i] == "-" and i + 1 < n and source[i + 1] == "/":
                    depth -= 1
                    i += 2
                    col += 2
                elif source[i] == "\n":
                    i += 1
                    line += 1
                    col = 1
                else:
                    i += 1
                    col += 1

            raw = source[start_i:i]
            if depth > 0:
                warnings.append(
                    ConversionWarning(
                        code="UNCLOSED_COMMENT",
                        message="Unclosed block comment (`/-` without matching `-/`).",
                        line=start_line,
                        column=start_col,
                        source_snippet=raw[:60],
                    )
                )
                inner = raw[prefix_len:]
            else:
                inner = raw[prefix_len:-2]

            # Dedent comment body cleanly
            cleaned_lines = [ln.strip() for ln in inner.strip().splitlines()]
            cleaned_text = "\n".join(cleaned_lines).strip()
            comments.append(Comment(kind, cleaned_text, raw, start_line, line, start_col - 1))
            tokens.append(Token("COMMENT", raw, start_line, start_col, line, col))
            continue

        # String literal
        if ch == '"':
            start_line, start_col = line, col
            start_i = i
            i += 1
            col += 1
            closed = False
            while i < n:
                if source[i] == "\\" and i + 1 < n:
                    i += 2
                    col += 2
                elif source[i] == '"':
                    i += 1
                    col += 1
                    closed = True
                    break
                elif source[i] == "\n":
                    i += 1
                    line += 1
                    col = 1
                else:
                    i += 1
                    col += 1
            raw = source[start_i:i]
            if not closed:
                warnings.append(
                    ConversionWarning(
                        code="UNCLOSED_STRING",
                        message="Unclosed string literal.",
                        line=start_line,
                        column=start_col,
                        source_snippet=raw[:40],
                    )
                )
            tokens.append(Token("STRING", raw, start_line, start_col, line, col))
            continue

        # Number literal (integer, float, hex)
        if ch.isdigit():
            start_line, start_col = line, col
            start_i = i
            while i < n and (source[i].isalnum() or (source[i] == "." and i + 1 < n and source[i + 1].isdigit())):
                i += 1
                col += 1
            tokens.append(Token("NUMBER", source[start_i:i], start_line, start_col, line, col))
            continue

        # Multi-character operators
        matched_multi = None
        for mop in MULTI_CHAR_OPS:
            if source.startswith(mop, i):
                matched_multi = mop
                break
        if matched_multi is not None:
            start_col = col
            i += len(matched_multi)
            col += len(matched_multi)
            tokens.append(Token("OP", matched_multi, line, start_col, line, col))
            continue

        # Single-character delimiters
        if ch in SINGLE_CHAR_DELIMS:
            tokens.append(Token(SINGLE_CHAR_DELIMS[ch], ch, line, col, line, col + 1))
            i += 1
            col += 1
            continue

        # Unicode math operators
        if ch in UNICODE_MATH_OPS:
            tokens.append(Token("OP", ch, line, col, line, col + 1))
            i += 1
            col += 1
            continue

        # Identifiers (including dotted names like Nat.add_comm or Real.sin)
        if _is_ident_start(ch):
            start_line, start_col = line, col
            start_i = i
            while i < n and _is_ident_continue(source[i]):
                i += 1
                col += 1
            # Consume dotted qualified identifiers and numeric projections like `Nat.add_comm`, `h.1`, `p.1.2`
            while i + 1 < n and source[i] == "." and (_is_ident_start(source[i + 1]) or source[i + 1].isdigit()):
                i += 1
                col += 1
                while i < n and (_is_ident_continue(source[i]) or source[i].isdigit()):
                    i += 1
                    col += 1
            tokens.append(Token("IDENT", source[start_i:i], start_line, start_col, line, col))
            continue

        # ASCII single-char operators
        if ch in ASCII_OP_CHARS or ch == "#":
            tokens.append(Token("OP", ch, line, col, line, col + 1))
            i += 1
            col += 1
            continue

        # Superscript / subscript or miscellaneous Unicode character
        tokens.append(Token("OP", ch, line, col, line, col + 1))
        i += 1
        col += 1

    tokens.append(Token("EOF", "", line, col, line, col))
    return tokens, comments, warnings
