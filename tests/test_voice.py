"""フリガナ展開がTTS入力を壊さないための回帰テスト。"""
from __future__ import annotations

import unittest

from agents.voice import (
    _build_tts_prompt,
    _clean_text_for_tts,
    _is_retryable_exception,
    _sanitize_text_for_tts,
    _tts_input_diagnostics,
)
from google.genai import errors


class CleanTextForTtsTests(unittest.TestCase):
    def test_expands_supported_ruby_notation(self) -> None:
        cases = {
            "漢字（かんじ）": "かんじ",
            "OpenAI（オープンエーアイ）": "オープンエーアイ",
            "C++（シープラスプラス）": "シープラスプラス",
            "取り扱い（とりあつかい）": "とりあつかい",
            "株式会社（かぶしきがいしゃ）": "かぶしきがいしゃ",
            "これは東京都（とうきょうと）の発表です。": "これはとうきょうとの発表です。",
        }

        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(_clean_text_for_tts(source), expected)

    def test_preserves_parentheses_that_are_not_kana_readings(self) -> None:
        cases = (
            "名称（よみ：Reading）",
            "設定（Version 2）",
            "（注）漢字（かんじ）",
        )

        for source in cases:
            with self.subTest(source=source):
                expected = "（注）かんじ" if source.startswith("（注）") else source
                self.assertEqual(_clean_text_for_tts(source), expected)

    def test_tts_input_diagnostics_reports_non_content_metadata(self) -> None:
        diagnostics = _tts_input_diagnostics("AI\n東京")

        self.assertIn("chars=5", diagnostics)
        self.assertIn("utf8_bytes=9", diagnostics)
        self.assertIn("control_chars=0", diagnostics)
        self.assertIn("non_bmp_chars=0", diagnostics)
        self.assertRegex(diagnostics, r"sha256=[0-9a-f]{12}")


class SanitizeTextForTtsTests(unittest.TestCase):
    def test_removes_unicode_replacement_character(self) -> None:
        self.assertEqual(_sanitize_text_for_tts("研究\ufffd機関"), "研究機関")

    def test_removes_control_characters(self) -> None:
        self.assertEqual(_sanitize_text_for_tts("a\x00b\x07c"), "abc")

    def test_collapses_whitespace(self) -> None:
        self.assertEqual(
            _sanitize_text_for_tts("  AI\nニュース\tです。 "),
            "AI ニュース です。",
        )

    def test_leaves_normal_text_unchanged(self) -> None:
        source = "こんにちは、テストです。"
        self.assertEqual(_sanitize_text_for_tts(source), source)


class RetryableExceptionTests(unittest.TestCase):
    @staticmethod
    def _client_error(message: str, code: int = 400) -> errors.ClientError:
        return errors.ClientError(
            code,
            {"error": {"code": code, "message": message, "status": "INVALID_ARGUMENT"}},
        )

    def test_generic_invalid_argument_400_is_retryable(self) -> None:
        error = self._client_error("Request contains an invalid argument.")
        self.assertTrue(_is_retryable_exception(error))

    def test_specific_400_is_not_retryable(self) -> None:
        error = self._client_error("Voice Zephyr is not supported.")
        self.assertFalse(_is_retryable_exception(error))

    def test_401_403_404_are_not_retryable(self) -> None:
        for code in (401, 403, 404):
            with self.subTest(code=code):
                self.assertFalse(
                    _is_retryable_exception(self._client_error("nope", code=code))
                )

    def test_429_and_5xx_are_retryable(self) -> None:
        for code in (408, 429, 500, 502, 503, 504):
            with self.subTest(code=code):
                self.assertTrue(
                    _is_retryable_exception(self._client_error("temporary", code=code))
                )

    def test_plain_exception_is_not_retryable(self) -> None:
        self.assertFalse(_is_retryable_exception(RuntimeError("boom")))


class BuildTtsPromptTests(unittest.TestCase):
    def test_contains_request_id_persona_and_clean_script(self) -> None:
        prompt = _build_tts_prompt("abc123", "PERSONA\n", "今日のニュースです。")

        self.assertTrue(
            prompt.startswith("[request_id=abc123]\nPERSONA\n今日のニュースです。")
        )


if __name__ == "__main__":
    unittest.main()