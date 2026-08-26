import unittest
from common.language import (
    LanguageContext,
    normalize_language_code,
    prepare_game_text,
    provider_target_code,
    truncate_utf8,
    utf8_length,
)


class TestLanguage(unittest.TestCase):
    def test_normalizes_bcp47_codes(self):
        self.assertEqual(normalize_language_code("EN"), "en")
        self.assertEqual(normalize_language_code("pt_br"), "pt-BR")
        self.assertEqual(normalize_language_code("zh-hant-tw"), "zh-Hant-TW")

    def test_rejects_invalid_codes(self):
        with self.assertRaises(ValueError):
            normalize_language_code("portuguese brazil")

    def test_pt_br_provider_name_and_ascii_policy(self):
        language = LanguageContext.create("pt-br")
        self.assertEqual(language.display_name, "Brazilian Portuguese")
        self.assertTrue(language.ascii_output)

    def test_provider_target_mapping_does_not_change_language_identity(self):
        for provider in ("google", "googlefree", "googletranslatepa", "libretranslate", "yandex"):
            with self.subTest(provider=provider):
                self.assertEqual(provider_target_code(provider, "pt-BR"), "pt")
        self.assertEqual(provider_target_code("deepl", "pt-BR"), "PT-BR")
        self.assertEqual(provider_target_code("chatgpt", "pt-BR"), "pt-BR")
        self.assertEqual(provider_target_code("ollama", "pt-BR"), "pt-BR")

    def test_provider_script_variant_mappings(self):
        for provider in ("google", "googlefree", "googletranslatepa"):
            with self.subTest(provider=provider):
                self.assertEqual(provider_target_code(provider, "zh-Hans"), "zh-CN")
                self.assertEqual(provider_target_code(provider, "zh-Hant"), "zh-TW")
        self.assertEqual(provider_target_code("deepl", "zh-Hans"), "ZH-HANS")
        self.assertEqual(provider_target_code("libretranslate", "zh-Hans"), "zh")
        self.assertEqual(provider_target_code("yandex", "zh-Hant"), "zh")

    def test_pt_br_ascii_is_only_an_output_policy(self):
        stored = "voce tem um coracao e uma bencao"
        unicode_stored = "você tem um coração e uma bênção"
        output = prepare_game_text(unicode_stored, LanguageContext.create("pt-BR"))
        self.assertEqual(output, stored)
        self.assertEqual(unicode_stored, "você tem um coração e uma bênção")

    def test_spanish_is_converted_to_visible_game_ascii(self):
        source = "¡El pingüino pidió caña y acción! ¿Qué tal?"
        output = prepare_game_text(source, LanguageContext.create("es"))
        self.assertEqual(output, "!El pinguino pidio cana y accion! ?Que tal?")
        self.assertTrue(output.isascii())

    def test_non_latin_scripts_are_romanized_instead_of_disappearing(self):
        samples = {
            "ar": "مرحبا بالعالم",
            "ru": "Привет, мир!",
            "el": "Καλημέρα κόσμε",
            "zh-Hans": "你好，世界！",
            "ko": "안녕하세요 세계",
        }
        for language_code, source in samples.items():
            with self.subTest(language=language_code):
                output = prepare_game_text(source, LanguageContext.create(language_code))
                self.assertTrue(output)
                self.assertTrue(output.isascii())

    def test_native_japanese_is_not_romanized(self):
        source = "こんにちは、世界！"
        self.assertEqual(prepare_game_text(source, LanguageContext.create("ja")), source)

    def test_tags_and_placeholders_survive_output_policy(self):
        source = "<voice_nw><color_red>ação para <pc><select 2>coração"
        output = prepare_game_text(source, LanguageContext.create("pt-BR"))
        self.assertIn("<voice_nw>", output)
        self.assertIn("<color_red>", output)
        self.assertIn("<pc>", output)
        self.assertIn("<select 2>", output)

    def test_utf8_truncation_uses_bytes_and_keeps_tags_atomic(self):
        value = "ação<pc>coração"
        truncated = truncate_utf8(value, 13)
        self.assertLessEqual(utf8_length(truncated), 13)
        self.assertNotRegex(truncated, r"<[^>]*$")

    def test_transliteration_happens_before_byte_truncation(self):
        output = prepare_game_text("Привет, мир!", LanguageContext.create("ru"), max_bytes=9)
        self.assertEqual(output, "Privet...")
        self.assertLessEqual(utf8_length(output), 9)

    def test_fallback_chain_is_selected_then_english_then_japanese(self):
        self.assertEqual(LanguageContext.create("pt-BR").fallback_codes(), ("pt-BR", "en", "ja"))


if __name__ == "__main__":
    unittest.main()
