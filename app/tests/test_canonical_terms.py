import unittest
from unittest.mock import patch

from common.canonical_terms import CanonicalTermProtector
from common.translate import Translator


class TestCanonicalTermProtector(unittest.TestCase):
    def test_japanese_and_english_terms_are_restored_in_official_english(self):
        protector = CanonicalTermProtector(
            {
                "ヴェリナード領西": "Verinard West",
                "ヴェリナード": "Verinard",
                "水竜": "Water Dragon",
            }
        )

        prepared, protected = protector.prepare("Go to Verinard West and defeat 水竜.")

        self.assertNotIn("Verinard", prepared)
        self.assertNotIn("Water Dragon", prepared)
        self.assertEqual(
            protector.restore(prepared, protected),
            "Go to Verinard West and defeat Water Dragon.",
        )

    def test_longest_name_wins_and_game_tags_are_untouched(self):
        protector = CanonicalTermProtector(
            {
                "ヴェリナード領西": "Verinard West",
                "ヴェリナード": "Verinard",
            }
        )

        prepared, protected = protector.prepare("<pc>ヴェリナード領西")

        self.assertTrue(prepared.startswith("<pc>"))
        self.assertEqual(list(protected.values()), ["Verinard West"])
        self.assertEqual(protector.restore(prepared, protected), "<pc>Verinard West")

    def test_adjacent_japanese_names_are_never_exposed_as_joined_english(self):
        protector = CanonicalTermProtector(
            {
                "港町レンドア": "Port Lendor",
                "ココラタの浜辺": "Cocolata Beach",
            }
        )

        prepared, protected = protector.prepare("港町レンドアココラタの浜辺間を")

        self.assertNotIn("Port LendorCocolata Beach", prepared)
        self.assertEqual(len(protected), 2)
        self.assertEqual(
            protector.restore(prepared, protected),
            "Port LendorCocolata Beach間を",
        )

    def test_missing_marker_is_allowed_but_malformed_marker_is_rejected(self):
        protector = CanonicalTermProtector({"水竜": "Water Dragon"})
        prepared, protected = protector.prepare("Defeat Water Dragon.")
        marker = next(iter(protected))

        self.assertEqual(protector.restore(prepared.replace(marker, ""), protected), "Defeat .")
        self.assertIsNone(protector.restore(prepared.replace(marker, marker.replace("<&", "<")), protected))

    def test_hiragana_name_does_not_match_inside_an_ordinary_word(self):
        protector = CanonicalTermProtector({"かりな": "Carina"})

        prepared, protected = protector.prepare("手がかりなんてない。　かりなに話そう。")

        self.assertIn("手がかりなんてない", prepared)
        self.assertEqual(list(protected.values()), ["Carina"])
        self.assertEqual(
            protector.restore(prepared, protected),
            "手がかりなんてない。　Carinaに話そう。",
        )

    def test_translator_preserves_terms_while_translating_full_sentence(self):
        translator = Translator.__new__(Translator)
        translator.glossary = {}
        translator.service = "test"
        translator._canonical_protector = CanonicalTermProtector(
            {
                "水竜": "Water Dragon",
                "ヴェリナード": "Verinard",
            }
        )
        captured: list[str] = []

        def translate_items(text):
            captured.extend(text)
            return [item.replace("Defeat", "Derrote").replace(" in ", " em ") for item in text]

        translator._Translator__api_translate = translate_items
        with patch("common.translate.should_translate_text", return_value=True):
            translated = translator.translate(
                "Defeat Water Dragon in Verinard.",
                wrap_width=80,
                add_brs=False,
            )

        self.assertEqual(len(captured), 1)
        self.assertIn("<&dqxc_", captured[0])
        self.assertEqual(translated, "Derrote Water Dragon em Verinard.")

    def test_translator_falls_back_if_provider_changes_marker(self):
        translator = Translator.__new__(Translator)
        translator.glossary = {}
        translator.service = "test"
        translator._canonical_protector = CanonicalTermProtector({"水竜": "Water Dragon"})
        translator._Translator__api_translate = lambda text: [item.replace("<&dqxc_", "<dqxc_") for item in text]

        with patch("common.translate.should_translate_text", return_value=True):
            translated = translator.translate("Defeat Water Dragon.", wrap_width=80, add_brs=False)

        self.assertEqual(translated, "")

    def test_long_canonical_name_is_restored_before_line_wrapping(self):
        translator = Translator.__new__(Translator)
        translator.glossary = {}
        translator.service = "test"
        translator._canonical_protector = CanonicalTermProtector(
            {"グレン城下町駅": "Glen Castle Town Station"}
        )
        translator._Translator__api_translate = lambda text: text

        with patch("common.translate.should_translate_text", return_value=True):
            translated = translator.translate(
                "Visit Glen Castle Town Station today.",
                wrap_width=20,
                add_brs=False,
            )

        self.assertIn("Glen Castle Town Station", translated.replace("\n", " "))
        self.assertTrue(all(len(line) <= 20 for line in translated.splitlines()))

    def test_protected_name_in_untranslated_choice_is_restored(self):
        translator = Translator.__new__(Translator)
        translator.glossary = {}
        translator.service = "test"
        translator._canonical_protector = CanonicalTermProtector({"ヴェリナード領西": "Verinard West"})
        translator._Translator__api_translate = lambda text: [f"PT:{item}" for item in text]

        with patch("common.translate.should_translate_text", return_value=True):
            translated = translator.translate(
                "Choose:<select>\nVerinard West\nCancel\n<select_end>",
                wrap_width=40,
                add_brs=False,
                translate_choices=False,
            )

        self.assertIn("<select>\nVerinard West\nCancel\n<select_end>", translated)
        self.assertNotIn("dqxc_", translated)


if __name__ == "__main__":
    unittest.main()
