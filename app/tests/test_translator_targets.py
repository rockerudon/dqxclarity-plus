import requests
import unittest
from common.translation_domains import PROSE_LAYOUTS, fit_prose_layout
from common.translators.chatgpt import _system_prompt
from common.translators.deepl import _deepl_target
from common.translators.googletranslatefree import GoogleTranslateFree
from common.translators.googletranslatepa import GoogleTranslatePa
from unittest.mock import MagicMock, patch


class TestTranslatorTargets(unittest.TestCase):
    def test_prose_layouts_match_upstream_english_pack_constraints(self):
        self.assertEqual(
            (PROSE_LAYOUTS["walkthrough"].wrap_width, PROSE_LAYOUTS["walkthrough"].max_lines),
            (31, 3),
        )
        self.assertEqual(
            (PROSE_LAYOUTS["story_so_far"].wrap_width, PROSE_LAYOUTS["story_so_far"].max_lines),
            (39, 8),
        )
        self.assertEqual((PROSE_LAYOUTS["quests"].wrap_width, PROSE_LAYOUTS["quests"].max_lines), (45, 6))

    def test_cached_story_text_is_reflowed_to_box_constraints(self):
        cached = " ".join(f"palavra{index}" for index in range(60))
        fitted = fit_prose_layout(cached, PROSE_LAYOUTS["story_so_far"])

        self.assertLessEqual(len(fitted.splitlines()), 8)
        self.assertTrue(all(len(line) <= 39 or " " not in line for line in fitted.splitlines()))

    def test_deepl_brazilian_portuguese_mapping(self):
        self.assertEqual(_deepl_target("pt-BR"), "PT-BR")
        self.assertEqual(_deepl_target("pt-PT"), "PT-PT")
        self.assertEqual(_deepl_target("zh-Hant"), "ZH-HANT")

    def test_llm_prompt_requests_brazilian_portuguese_and_preserves_tags(self):
        prompt = _system_prompt("Brazilian Portuguese")
        self.assertIn("Japanese to Brazilian Portuguese", prompt)
        self.assertIn("game tag and placeholder", prompt)

    def test_free_google_adapters_use_supported_portuguese_code(self):
        config = MagicMock(target_language="pt-BR", source_language="ja")
        with (
            patch("common.translators.googletranslatefree.UserConfig", return_value=config),
            patch("common.translators.googletranslatepa.UserConfig", return_value=config),
        ):
            self.assertEqual(GoogleTranslateFree().target, "pt")
            self.assertEqual(GoogleTranslatePa().target, "pt")

    def test_mobile_google_request_uses_mapped_target(self):
        config = MagicMock(target_language="pt-BR", source_language="ja")
        response = MagicMock(text='<div class="result-container">Ol&#225;</div>')
        with patch("common.translators.googletranslatefree.UserConfig", return_value=config):
            translator = GoogleTranslateFree()
        translator.session.get = MagicMock(return_value=response)

        self.assertEqual(translator.translate(["こんにちは"]), ["Olá"])
        _, kwargs = translator.session.get.call_args
        self.assertEqual(kwargs["params"]["tl"], "pt")
        self.assertEqual(kwargs["params"]["hl"], "pt")
        self.assertEqual(kwargs["params"]["sl"], "ja")

    def test_mobile_google_uses_auto_source_for_api_overlay(self):
        config = MagicMock(target_language="pt-BR", source_language="auto")
        response = MagicMock(text='<div class="result-container">Bem-vindo</div>')
        with patch("common.translators.googletranslatefree.UserConfig", return_value=config):
            translator = GoogleTranslateFree()
        translator.session.get = MagicMock(return_value=response)

        self.assertEqual(translator.translate(["Welcome"]), ["Bem-vindo"])
        _, kwargs = translator.session.get.call_args
        self.assertEqual(kwargs["params"]["sl"], "auto")

    def test_mobile_google_falls_back_to_free_json_endpoint(self):
        config = MagicMock(target_language="pt-BR", source_language="auto")
        mobile = MagicMock(text="<html><body>consent</body></html>")
        fallback = MagicMock()
        fallback.json.return_value = [[["Ola", "こんにちは", None, None]]]
        with patch("common.translators.googletranslatefree.UserConfig", return_value=config):
            translator = GoogleTranslateFree()
        translator.session.get = MagicMock(side_effect=[mobile, fallback])

        with patch("common.translators.googletranslatefree.time.sleep"):
            self.assertEqual(translator.translate(["こんにちは"]), ["Ola"])
        self.assertEqual(translator.session.get.call_args_list[1].args[0], translator.json_url)

    def test_mobile_google_uses_json_fallback_after_timeout(self):
        config = MagicMock(target_language="pt-BR", source_language="auto")
        fallback = MagicMock()
        fallback.json.return_value = [[["Bem-vindo", "Welcome", None, None]]]
        with patch("common.translators.googletranslatefree.UserConfig", return_value=config):
            translator = GoogleTranslateFree()
        translator.session.get = MagicMock(
            side_effect=[requests.Timeout("mobile timeout"), fallback]
        )

        with patch("common.translators.googletranslatefree.time.sleep"):
            self.assertEqual(translator.translate(["Welcome"]), ["Bem-vindo"])

    def test_free_google_batches_choice_lines_into_one_request(self):
        config = MagicMock(target_language="pt-BR", source_language="auto")
        response = MagicMock(
            text=(
                '<div class="result-container">Pergunta traduzida\n'
                'ZXQSEGMENT0001QXZ\nAceitar\nZXQSEGMENT0002QXZ\nRecusar</div>'
            )
        )
        with patch("common.translators.googletranslatefree.UserConfig", return_value=config):
            translator = GoogleTranslateFree()
        translator.session.get = MagicMock(return_value=response)

        result = translator.translate(["Question", "Accept", "Decline"])

        self.assertEqual(result, ["Pergunta traduzida", "Aceitar", "Recusar"])
        translator.session.get.assert_called_once()
        request_text = translator.session.get.call_args.kwargs["params"]["q"]
        self.assertIn("ZXQSEGMENT0001QXZ", request_text)
        self.assertIn("ZXQSEGMENT0002QXZ", request_text)

    def test_free_google_reuses_successful_phrase_cache(self):
        config = MagicMock(target_language="pt-BR", source_language="auto")
        response = MagicMock(text='<div class="result-container">Bem-vindo</div>')
        with patch("common.translators.googletranslatefree.UserConfig", return_value=config):
            translator = GoogleTranslateFree()
        translator.session.get = MagicMock(return_value=response)

        self.assertEqual(translator.translate(["Welcome"]), ["Bem-vindo"])
        self.assertEqual(translator.translate(["Welcome"]), ["Bem-vindo"])
        translator.session.get.assert_called_once()

    def test_free_google_does_not_switch_provider_when_rate_limited(self):
        config = MagicMock(
            target_language="pt-BR",
            source_language="auto",
            googlefree_yandex_fallback=False,
        )
        rate_limited = MagicMock()
        response_429 = MagicMock(status_code=429)
        rate_limited.raise_for_status.side_effect = requests.HTTPError("429", response=response_429)
        with patch("common.translators.googletranslatefree.UserConfig", return_value=config):
            translator = GoogleTranslateFree()
        translator.session.get = MagicMock(return_value=rate_limited)

        self.assertEqual(translator.translate(["Question", "Accept"]), ["", ""])
        self.assertEqual(translator.translate(["Question", "Accept"]), ["", ""])
        translator.session.get.assert_called_once()

    def test_free_google_uses_yandex_only_during_rate_limit_cooldown(self):
        config = MagicMock(
            target_language="pt-BR",
            source_language="auto",
            googlefree_yandex_fallback=True,
        )
        rate_limited = MagicMock()
        response_429 = MagicMock(status_code=429)
        rate_limited.raise_for_status.side_effect = requests.HTTPError("429", response=response_429)
        yandex = MagicMock()
        yandex.translate.side_effect = [
            ["Pergunta", "Aceitar"],
            ["Outra fala"],
        ]
        with (
            patch("common.translators.googletranslatefree.UserConfig", return_value=config),
            patch("common.translators.yandex.YandexTranslate", return_value=yandex),
        ):
            translator = GoogleTranslateFree()
            translator.session.get = MagicMock(return_value=rate_limited)

            self.assertEqual(translator.translate(["Question", "Accept"]), ["Pergunta", "Aceitar"])
            self.assertEqual(translator.translate(["Another line"]), ["Outra fala"])

        # Google is attempted once; the second call stays inside its cooldown.
        translator.session.get.assert_called_once()
        self.assertEqual(yandex.translate.call_count, 2)
        self.assertGreater(translator._consecutive_throttles, 0)

    def test_free_google_returns_to_google_after_yandex_cooldown(self):
        config = MagicMock(
            target_language="pt-BR",
            source_language="auto",
            googlefree_yandex_fallback=True,
        )
        success = MagicMock(text='<div class="result-container">De volta ao Google</div>')
        with patch("common.translators.googletranslatefree.UserConfig", return_value=config):
            translator = GoogleTranslateFree()
        translator._blocked_until = 0.0
        translator._consecutive_throttles = 2
        translator.session.get = MagicMock(return_value=success)

        self.assertEqual(translator.translate(["Back on Google"]), ["De volta ao Google"])
        translator.session.get.assert_called_once()
        self.assertEqual(translator._consecutive_throttles, 0)

    def test_free_google_uses_bounded_progressive_cooldown(self):
        config = MagicMock(target_language="pt-BR", source_language="auto")
        with patch("common.translators.googletranslatefree.UserConfig", return_value=config):
            translator = GoogleTranslateFree()

        with patch(
            "common.translators.googletranslatefree.time.monotonic",
            side_effect=[100.0, 200.0, 300.0, 400.0, 500.0],
        ):
            cooldowns = [
                translator._GoogleTranslateFree__mark_throttled()  # noqa: SLF001
                for _ in range(5)
            ]

        self.assertEqual(cooldowns, [5.0, 15.0, 30.0, 60.0, 60.0])
        self.assertEqual(translator._blocked_until, 560.0)

    def test_free_google_success_resets_progressive_cooldown(self):
        config = MagicMock(target_language="pt-BR", source_language="auto")
        response = MagicMock(text='<div class="result-container">Bem-vindo</div>')
        with patch("common.translators.googletranslatefree.UserConfig", return_value=config):
            translator = GoogleTranslateFree()
        translator._consecutive_throttles = 3
        translator.session.get = MagicMock(return_value=response)

        self.assertEqual(translator.translate(["Welcome"]), ["Bem-vindo"])
        self.assertEqual(translator._consecutive_throttles, 0)

if __name__ == "__main__":
    unittest.main()
