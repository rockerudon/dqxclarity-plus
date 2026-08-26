import unittest
from unittest.mock import MagicMock, patch

from hooking.hooks import corner_text


class CornerTextTests(unittest.TestCase):
    def setUp(self) -> None:
        corner_text._data = {"Japanese event": "English event"}
        corner_text._custom_text_logger = MagicMock()
        corner_text._translator = MagicMock()
        corner_text._language = MagicMock()

    def test_overlay_translates_pack_english_and_caches_by_source(self) -> None:
        corner_text._translator.translate.return_value = "Evento traduzido"
        with (
            patch("hooking.hooks.corner_text.sql_read", return_value=None) as read,
            patch("hooking.hooks.corner_text.sql_write") as write,
            patch("hooking.hooks.corner_text.should_translate_text", return_value=True),
        ):
            result = corner_text.corner_text_replacement("Japanese event")

        self.assertEqual(result, "Evento traduzido")
        read.assert_called_once_with(text="English event", table="corner_text")
        corner_text._translator.translate.assert_called_once_with(
            "English event",
            wrap_width=46,
            add_brs=False,
        )
        write.assert_called_once_with(
            source_text="English event",
            translated_text="Evento traduzido",
            table="corner_text",
        )

    def test_provider_failure_uses_english_pack_fallback(self) -> None:
        corner_text._translator.translate.return_value = None
        with (
            patch("hooking.hooks.corner_text.sql_read", return_value=None),
            patch("hooking.hooks.corner_text.should_translate_text", return_value=True),
        ):
            result = corner_text.corner_text_replacement("Japanese event")

        self.assertEqual(result, "English event")

    def test_disabled_overlay_still_uses_english_pack_entry(self) -> None:
        with (
            patch("hooking.hooks.corner_text.sql_read", return_value=None),
            patch("hooking.hooks.corner_text.should_translate_text", return_value=False),
        ):
            result = corner_text.corner_text_replacement("Japanese event")

        self.assertEqual(result, "English event")
        corner_text._translator.translate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
