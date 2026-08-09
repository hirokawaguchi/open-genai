"""FormFileGenerator DSL の assemble / finalize コード単体テスト。"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "generate_form_file_generator_dsl.py"
)


def _load_gen():
    spec = importlib.util.spec_from_file_location("ffg_gen", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _exec_main(code: str):
    ns: dict = {}
    exec(code, ns)  # noqa: S102
    return ns["main"]


class AssembleCodeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.assemble = _exec_main(_load_gen().ASSEMBLE_CODE)

    def test_builds_prompt_from_fields(self) -> None:
        out = self.assemble("事業A", "企画課", "課題あり", "out", "docx")
        self.assertIn("事業A", out["prompt"])
        self.assertIn("企画課", out["prompt"])
        self.assertIn("課題あり", out["prompt"])
        self.assertEqual(out["filename"], "out")
        self.assertEqual(out["output_format"], "docx")


class JoinRefsCodeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.join = _exec_main(_load_gen().JOIN_REFS_CODE)

    def test_empty(self) -> None:
        self.assertEqual(self.join(None)["ref_context"], "(参考資料なし)")
        self.assertEqual(self.join([])["ref_context"], "(参考資料なし)")

    def test_list(self) -> None:
        out = self.join(["資料A", "資料B"])
        self.assertIn("資料A", out["ref_context"])
        self.assertIn("資料B", out["ref_context"])


class FinalizeCodeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.finalize = _exec_main(_load_gen().FINALIZE_CODE)

    def test_strips_fence_and_sets_ext(self) -> None:
        out = self.finalize("```markdown\n# 本文\n```", "report", "markdown")
        self.assertEqual(out["content"], "# 本文")
        self.assertEqual(out["filename"], "report.md")
        self.assertEqual(out["mime_type"], "text/markdown")


if __name__ == "__main__":
    unittest.main()
