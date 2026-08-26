import unittest
from unittest.mock import MagicMock, patch

from hooking.hooks import network_text


class NetworkTextTests(unittest.TestCase):
    def setUp(self) -> None:
        network_text._m00_text = {}
        network_text._custom_text_logger = MagicMock()

    def test_observed_story_progress_category_uses_api_and_own_cache(self) -> None:
        translator = MagicMock()
        translator.translate.return_value = "Resumo traduzido"
        with (
            patch("hooking.hooks.network_text._init_data", return_value={}),
            patch("hooking.hooks.network_text.sql_read", return_value=None) as read,
            patch("hooking.hooks.network_text.sql_write") as write,
            patch("hooking.hooks.network_text.Translator", return_value=translator),
            patch("hooking.hooks.network_text.should_translate_text", return_value=True),
        ):
            result = network_text.network_text_replacement("物語の進行", "<%sM_text01>")

        self.assertEqual(result, "Resumo traduzido")
        read.assert_called_once_with(text="物語の進行", table="fixed_dialog_template")
        write.assert_called_once_with(
            source_text="物語の進行",
            translated_text="Resumo traduzido",
            table="fixed_dialog_template",
        )

    def test_story_progress_provider_failure_keeps_source(self) -> None:
        translator = MagicMock()
        translator.translate.return_value = None
        with (
            patch("hooking.hooks.network_text._init_data", return_value={}),
            patch("hooking.hooks.network_text.sql_read", return_value=None),
            patch("hooking.hooks.network_text.Translator", return_value=translator),
            patch("hooking.hooks.network_text.should_translate_text", return_value=True),
        ):
            result = network_text.network_text_replacement("物語の進行", "<%sM_text01>")

        self.assertEqual(result, "物語の進行")


if __name__ == "__main__":
    unittest.main()
