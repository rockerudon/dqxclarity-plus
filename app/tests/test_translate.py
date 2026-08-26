import unittest
from common.language import contains_choice_markup, is_suspicious_translation, looks_like_choice_list
from common.translate import Translator, _runtime_translation_policy, should_translate_text, transliterate_player_name
from unittest.mock import MagicMock, patch


class TestTranslate(unittest.TestCase):
    def test_provider_html_css_is_rejected(self):
        self.assertTrue(is_suspicious_translation("body{overflow:auto!important;display:block!important;}"))
        self.assertTrue(is_suspicious_translation("<style>body>*{display:none!important;}</style>"))
        self.assertFalse(is_suspicious_translation("Welcome to the Item Shop."))

        translator = Translator.__new__(Translator)
        translator.glossary = {}
        translator._get_translator_instance = lambda: MagicMock(
            translate=lambda phrases: ["body{display:none!important;}"]
        )
        self.assertEqual(translator._Translator__api_translate(["こんにちは"]), [])

    def test_selectable_dialogue_controls_are_detected(self):
        self.assertTrue(contains_choice_markup("Choose:<select>\nFirst\nSecond\n<select_end>"))
        self.assertTrue(contains_choice_markup("Choose:<select_se_off>\nFirst\nSecond\n<select_end>"))
        self.assertTrue(contains_choice_markup("Confirm?<yesno><close>"))
        self.assertFalse(contains_choice_markup("This is ordinary dialogue."))
        self.assertTrue(looks_like_choice_list("First option\nSecond option\n..."))
        self.assertFalse(looks_like_choice_list("Please save your progress.\nThen return to town."))

    def test_choice_options_stay_in_pack_language_while_prose_is_translated(self):
        translator = Translator.__new__(Translator)
        translator.glossary = {}
        translator.service = "test"
        translator._Translator__api_translate = lambda text: [f"PT:{item}" for item in text]

        source = "Would you like to leave?<select>\nLeave together\nLeave alone\n<select_end>"
        with patch("common.translate.should_translate_text", return_value=True):
            translated = translator.translate(source, wrap_width=46, add_brs=False, translate_choices=False)

        self.assertIn("PT:Would you like to leave?", translated)
        self.assertIn("<select>\nLeave together\nLeave alone\n<select_end>", translated)

    def test_choice_options_can_be_translated_without_changing_controls(self):
        translator = Translator.__new__(Translator)
        translator.glossary = {}
        translator.service = "test"
        translator._Translator__api_translate = lambda text: [f"PT:{item}" for item in text]

        source = "Would you like to leave?<select>\nLeave together\nLeave alone\n<select_end><case 1><close>"
        with patch("common.translate.should_translate_text", return_value=True):
            translated = translator.translate(source, wrap_width=46, add_brs=False, translate_choices=True)

        self.assertIn("PT:Would you like to leave?", translated)
        self.assertIn("<select>\nPT:Leave together\nPT:Leave alone\n<select_end>", translated)
        self.assertTrue(translated.endswith("<case 1><close>"))

    def test_pack_line_wraps_become_word_spaces_in_provider_input(self):
        translator = Translator.__new__(Translator)
        translator.glossary = {}
        translator.service = "test"
        captured = []

        def translate_items(text):
            captured.extend(text)
            return text

        translator._Translator__api_translate = translate_items
        with patch("common.translate.should_translate_text", return_value=True):
            translator.translate(
                "This is the place\nwhere travelers meet\nnew friends.",
                wrap_width=46,
                add_brs=False,
            )

        self.assertEqual(captured, ["This is the place where travelers meet new friends."])

    def test_transliterate_player_name(self):
        name = "セラニー"
        result = transliterate_player_name(name)
        self.assertTrue(result == "Seranii")

        name = "エりん"
        result = transliterate_player_name(name)
        self.assertTrue(result == "Erin")

        name = "ファンシー"
        result = transliterate_player_name(name)
        self.assertTrue(result == "Fanshii")

    def test_api_overlay_adds_latin_prose_without_changing_legacy_japanese(self):
        legacy = MagicMock(api_translation_overlay=False, target_language="pt-BR")
        overlay = MagicMock(api_translation_overlay=True, target_language="pt-BR")
        with patch("common.translate.UserConfig", return_value=legacy):
            _runtime_translation_policy.cache_clear()
            self.assertTrue(should_translate_text("こんにちは"))
            self.assertFalse(should_translate_text("Welcome to the Armor Shop."))
        with patch("common.translate.UserConfig", return_value=overlay):
            _runtime_translation_policy.cache_clear()
            self.assertTrue(should_translate_text("Welcome to the Armor Shop."))
            self.assertFalse(should_translate_text("<color_red>123"))
        japanese_target = MagicMock(api_translation_overlay=True, target_language="ja")
        with patch("common.translate.UserConfig", return_value=japanese_target):
            _runtime_translation_policy.cache_clear()
            self.assertFalse(should_translate_text("こんにちは"))
            self.assertTrue(should_translate_text("Welcome"))
        _runtime_translation_policy.cache_clear()


if __name__ == "__main__":
    unittest.main()
