"""Comprehensive automated test suite for Lean2Markdown.

Covers all 15 specification domains:
1. Basic arithmetic
2. Natural and integer numbers
3. Real analysis (limits, derivatives, summations, integrals)
4. Set theory (set-builder, ∈, ∉, ∪, ∩, ∅)
5. Logic and quantifiers (∀, ∃, ∧, ∨, ¬, →, ↔)
6. Algebraic structures (structures, classes, instances)
7. Functions and mappings (lambdas, composition, application)
8. Inductive types
9. Structures and classes
10. Dependent types
11. Nested/multi-declaration files and namespaces
12. Complex tactic proofs (`induction`, `cases`, `have`, `calc`, comments)
13. Custom notation (`notation`, `infixl`, `prefix`)
14. Unicode mathematical symbols & subscripts
15. Proof modes (statement, human, source), output formats (markdown, html, latex),
    CLI flags, and unsupported/malformed syntax warnings & safe fallbacks.
"""

import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lean2markdown.expr_parser import parse_math_expr
from lean2markdown.latex_renderer import render_math_expr
from lean2markdown.pipeline import ConversionConfig, convert_file, convert_source


class TestExpressionConversion(unittest.TestCase):
    def _to_latex(self, expr: str):
        ir, warnings = parse_math_expr(expr)
        tex, is_fb = render_math_expr(ir)
        return tex, is_fb, warnings

    def test_basic_arithmetic_and_precedence(self):
        tex, fb, _ = self._to_latex("a + b * c ^ 2")
        self.assertFalse(fb)
        self.assertEqual(tex, r"a + b \cdot c^{2}")

        tex2, fb2, _ = self._to_latex("(a + b) * c")
        self.assertFalse(fb2)
        self.assertEqual(tex2, r"(a + b) \cdot c")

    def test_number_systems_and_relations(self):
        tex, fb, _ = self._to_latex("∀ (a b : ℕ), a ≤ b ∧ b ≠ 0 → a < b + 1")
        self.assertFalse(fb)
        self.assertIn(r"\forall a, b \in \mathbb{N}", tex)
        self.assertIn(r"a \leq b", tex)
        self.assertIn(r"b \neq 0", tex)
        self.assertIn(r"\land", tex)
        self.assertIn(r"\rightarrow", tex)

    def test_quantifiers_and_logic(self):
        tex, fb, _ = self._to_latex("∀ x, P x ↔ ¬∃ y, Q y")
        self.assertFalse(fb)
        self.assertIn(r"\forall x,\ P(x)", tex)
        self.assertIn(r"\leftrightarrow", tex)
        self.assertIn(r"\neg (\exists y,\ Q(y))", tex)

    def test_set_theory_and_set_builder(self):
        tex, fb, _ = self._to_latex("{x ∈ S | x ∉ T ∧ x ∈ A ∪ B ∩ ∅}")
        self.assertFalse(fb)
        self.assertIn(r"x \in S", tex)
        self.assertIn(r"\notin", tex)
        self.assertIn(r"\cup", tex)
        self.assertIn(r"\cap", tex)
        self.assertIn(r"\varnothing", tex)

    def test_real_analysis_bigops_deriv_limit(self):
        sum_tex, fb1, _ = self._to_latex("∑ i ∈ s, i ^ 2")
        self.assertFalse(fb1)
        self.assertIn(r"\sum_{i \in s}", sum_tex)
        self.assertIn("i^{2}", sum_tex)

        deriv_tex, fb2, _ = self._to_latex("deriv f x")
        self.assertFalse(fb2)
        self.assertIn(r"\frac{d}{dx}", deriv_tex)

        lim_tex, fb3, _ = self._to_latex("Tendsto f a L")
        self.assertFalse(fb3)
        self.assertIn(r"\lim_{a}", lim_tex)

    def test_lambda_composition_and_matrices(self):
        lam_tex, fb1, _ = self._to_latex("fun x => (f ∘ g) x")
        self.assertFalse(fb1)
        self.assertIn(r"\mapsto", lam_tex)
        self.assertIn(r"\circ", lam_tex)

        mat_tex, fb2, _ = self._to_latex("![![1, 2], ![3, 4]]")
        self.assertFalse(fb2)
        self.assertIn(r"\begin{pmatrix}", mat_tex)
        self.assertIn("1 & 2", mat_tex)
        self.assertIn("3 & 4", mat_tex)

    def test_dependent_function_type(self):
        dep_tex, fb, _ = self._to_latex("(x : α) → β x")
        self.assertFalse(fb)
        self.assertIn(r"\prod_{x : \alpha}", dep_tex)
        self.assertIn(r"\beta(x)", dep_tex)

    def test_unicode_subscripts(self):
        tex, fb, _ = self._to_latex("x₀ + x₁ = y₂")
        self.assertFalse(fb)
        self.assertIn("x_{0}", tex)
        self.assertIn("x_{1}", tex)
        self.assertIn("y_{2}", tex)

    def test_numeric_field_and_tuple_projections(self):
        tex1, fb1, w1 = self._to_latex("h.1 hp")
        self.assertFalse(fb1)
        self.assertEqual(w1, [])
        self.assertIn(r"\mathrm{h.1}", tex1)
        self.assertIn(r"\mathrm{hp}", tex1)

        tex2, fb2, w2 = self._to_latex("(f x).2 hq")
        self.assertFalse(fb2)
        self.assertEqual(w2, [])
        self.assertIn("f(x)", tex2)

    def test_unsupported_macro_falls_back_safely(self):
        tex, fb, warnings = self._to_latex("`(term| $x + $y)")
        self.assertTrue(fb)
        self.assertTrue(any(w.code == "UNSUPPORTED_MACRO_EXPR" for w in warnings))

    def test_unbalanced_expr_emits_warning(self):
        tex, fb, warnings = self._to_latex("(a + b")
        self.assertTrue(fb)
        self.assertTrue(any(w.code == "UNBALANCED_EXPR" for w in warnings))


class TestProofModesAndFormats(unittest.TestCase):
    SAMPLE = """
/-!
# Sample Proof Module
-/

/-- Commutativity of natural number addition. -/
theorem add_comm_example (a b : ℕ) : a + b = b + a := by
  -- arithmetic normalization
  omega
"""

    def test_mode_a_statement_only(self):
        res = convert_source(self.SAMPLE, "sample.lean", ConversionConfig(proof_mode="statement"))
        self.assertIn("a + b = b + a", res.output)
        self.assertNotIn("**Proof.**", res.output)
        self.assertNotIn("Presburger", res.output)

    def test_mode_b_human_readable_with_comments(self):
        res = convert_source(self.SAMPLE, "sample.lean", ConversionConfig(proof_mode="human"))
        self.assertIn("**Proof.**", res.output)
        self.assertIn("Presburger arithmetic", res.output)
        self.assertIn("arithmetic normalization", res.output)

    def test_mode_c_lean_source_included(self):
        res = convert_source(self.SAMPLE, "sample.lean", ConversionConfig(proof_mode="source"))
        self.assertIn("```lean", res.output)
        self.assertIn("omega", res.output)

    def test_unknown_tactic_never_fabricates_reasoning(self):
        code = "theorem foo (a : ℕ) : a = a := by\n  my_custom_mystery_tactic\n"
        res = convert_source(code, "mystery.lean", ConversionConfig(proof_mode="human"))
        self.assertTrue(any(w.code == "UNKNOWN_TACTIC" for w in res.warnings))
        self.assertIn("requires manual explanation", res.output)

    def test_html_and_latex_output_formats(self):
        html_res = convert_source(self.SAMPLE, "sample.lean", ConversionConfig(format="html"))
        self.assertIn("<!DOCTYPE html>", html_res.output)
        self.assertIn("katex", html_res.output.lower())

        tex_res = convert_source(self.SAMPLE, "sample.lean", ConversionConfig(format="latex"))
        self.assertIn(r"\documentclass", tex_res.output)
        self.assertIn(r"\begin{theorem}", tex_res.output)
        self.assertIn(r"\begin{proof}", tex_res.output)


class TestFullFilesAndCLI(unittest.TestCase):
    ARITH_SAMPLE = """/-!
# Arithmetic and Analysis
-/
import Mathlib.Data.Nat.Basic

namespace Arithmetic

/-- Commutativity of addition. -/
theorem add_comm_example (a b : ℕ) : a + b = b + a := by
  omega

/-- Square of a sum via calc. -/
lemma square_sum (a b : ℤ) : (a + b) ^ 2 = a ^ 2 + 2 * a * b + b ^ 2 := by
  calc
    -- Expand the square as a product
    (a + b) ^ 2 = (a + b) * (a + b) := by ring
    _ = a ^ 2 + 2 * a * b + b ^ 2 := by ring

infixl:65 " ⊕ₘ " => avg

end Arithmetic
"""

    ALGEBRA_SAMPLE = """namespace AlgebraAndLogic

structure MyMonoid (α : Type) where
  mul : α → α → α
  one : α

class HasInvolution (α : Type) where
  inv : α → α

inductive PeanoNat : Type where
  | zero : PeanoNat
  | succ : PeanoNat → PeanoNat

theorem add_zero_right (n : ℕ) : n + 0 = n := by
  induction n with
  | zero => rfl
  | succ k ih =>
    have hstep : k + 0 = k := ih
    simp [hstep]

end AlgebraAndLogic
"""

    def test_arithmetic_example_file(self):
        res = convert_source(self.ARITH_SAMPLE, "arithmetic.lean", ConversionConfig(include_imports=True, include_source=True))
        self.assertIn("## Theorems", res.output)
        self.assertIn("## Lemmas", res.output)
        self.assertIn("## Custom Notation", res.output)
        self.assertIn("## Original Lean Source", res.output)
        self.assertIn(r"\begin{aligned}", res.output)
        self.assertIn("Expand the square", res.output)

    def test_algebra_and_logic_example_file(self):
        res = convert_source(self.ALGEBRA_SAMPLE, "algebra.lean", ConversionConfig(proof_mode="human"))
        self.assertIn("## Structures and Types", res.output)
        self.assertIn("MyMonoid", res.output)
        self.assertIn("HasInvolution", res.output)
        self.assertIn("PeanoNat", res.output)
        self.assertIn("mathematical induction", res.output)
        self.assertIn("Establish intermediate claim", res.output)

    def test_malformed_file_diagnostics(self):
        bad = "namespace Foo\n/- unclosed comment\ntheorem x : True := by trivial\n"
        res = convert_source(bad, "bad.lean")
        codes = {w.code for w in res.warnings}
        self.assertIn("UNCLOSED_COMMENT", codes)
        self.assertIn("UNCLOSED_SCOPE", codes)

    def test_cli_single_and_multi_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            in1 = Path(tmpdir) / "arithmetic.lean"
            in2 = Path(tmpdir) / "algebra.lean"
            in1.write_text(self.ARITH_SAMPLE, encoding="utf-8")
            in2.write_text(self.ALGEBRA_SAMPLE, encoding="utf-8")
            out_dir = Path(tmpdir) / "docs"
            cmd = [
                sys.executable, "-m", "lean2markdown",
                str(in1), str(in2),
                "-o", str(out_dir),
                "--proof-mode", "human",
                "--include-imports",
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            self.assertTrue((out_dir / "arithmetic.md").is_file())
            self.assertTrue((out_dir / "algebra.md").is_file())

    def test_cli_stdin_stdout(self):
        cmd = [sys.executable, "-m", "lean2markdown", "-", "--proof-mode", "statement"]
        proc = subprocess.run(
            cmd,
            input="theorem id_eq (x : ℕ) : x = x := by rfl\n",
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("x = x", proc.stdout)

    def test_cli_input_output_folder_preserves_subfolders(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            in_dir = Path(tmpdir) / "input"
            sub_dir = in_dir / "nested"
            out_dir = Path(tmpdir) / "output"
            sub_dir.mkdir(parents=True)
            (in_dir / "a.lean").write_text("theorem a (n : ℕ) : n = n := by rfl\n", encoding="utf-8")
            (sub_dir / "b.lean").write_text("theorem b (n : ℕ) : n + 0 = n := by omega\n", encoding="utf-8")
            cmd = [sys.executable, str(ROOT / "lean2md.py"), "-i", str(in_dir), "-o", str(out_dir)]
            proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            self.assertTrue((out_dir / "a.md").is_file())
            self.assertTrue((out_dir / "nested" / "b.md").is_file())


if __name__ == "__main__":
    unittest.main()
