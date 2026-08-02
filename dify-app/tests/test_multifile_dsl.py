"""MultiFileGenerator DSL コードノードの単体テスト。

Dify ワークフローは実行できないため、生成スクリプトが埋め込む
Python コード文字列（文書準備 / 出力整形）を exec して main() を直接検証する。
狙いは PR #29 の残リスク（270k 超のサイレント切り捨て・大容量サンプリングの不可視化）
に対する可視化が働くこと。
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "generate_multifile_generator_dsl.py"
)


def _load_gen():
    spec = importlib.util.spec_from_file_location("mfg_gen", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _exec_main(code: str):
    ns: dict = {}
    exec(code, ns)  # noqa: S102 - テスト内で自前コードを評価
    return ns["main"]


class PrepareCodeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.prepare = _exec_main(_load_gen().PREPARE_CODE)

    def test_small_doc_has_no_coverage_note(self) -> None:
        out = self.prepare(["短い本文"], "指示", "out", "markdown")
        self.assertEqual(out["truncated"], "false")
        self.assertEqual(out["is_large"], "false")
        self.assertEqual(out["coverage_note"], "")

    def test_large_but_not_truncated_notes_sampling(self) -> None:
        # MAX_INLINE(60000) 超・270000 以下
        out = self.prepare(["あ" * 100000], "全体を要約", "out", "markdown")
        self.assertEqual(out["is_large"], "true")
        self.assertEqual(out["truncated"], "false")
        self.assertIn("資料が大きいため", out["coverage_note"])
        self.assertNotIn("処理上限を超えた", out["coverage_note"])

    def test_over_270k_is_truncated_and_visible(self) -> None:
        out = self.prepare(["あ" * 400000], "全体を要約", "out", "markdown")
        self.assertEqual(out["truncated"], "true")
        self.assertEqual(out["kept_chars"], 270000)
        self.assertGreater(out["char_count"], 270000)
        self.assertIn("処理上限を超えた", out["coverage_note"])
        self.assertIn("270000", out["coverage_note"])

    def test_kept_chars_matches_part_capacity(self) -> None:
        out = self.prepare(["x" * 500000], "指示", "out", "markdown")
        # PART_SIZE(90000) * 3 = 270000 が保持上限
        self.assertEqual(out["kept_chars"], 270000)


class FinalizeCodeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.finalize = _exec_main(_load_gen().FINALIZE_CODE)

    def test_note_goes_to_result_text_not_file_content(self) -> None:
        note = "処理上限を超えたため先頭 270000 文字のみを対象にしました。"
        out = self.finalize("# 本文\n\n段落", "out", "markdown", note)
        self.assertTrue(out["result_text"].startswith("> ※ "))
        self.assertIn(note, out["result_text"])
        # ファイル本文には注意文を混ぜない
        self.assertNotIn("※", out["content"])
        self.assertTrue(out["content"].startswith("# 本文"))

    def test_json_file_content_stays_clean_with_note(self) -> None:
        note = "資料が大きいため代表区間の要約に基づいています。"
        out = self.finalize('{"k": 1}', "data", "json", note)
        # JSON ファイルは注意文で壊さない
        self.assertEqual(out["content"], '{"k": 1}')
        self.assertTrue(out["result_text"].startswith("> ※ "))

    def test_no_note_result_equals_content(self) -> None:
        out = self.finalize("本文", "out", "text", "")
        self.assertEqual(out["result_text"], out["content"])


if __name__ == "__main__":
    unittest.main()
