import unittest
from common.language import LanguageContext
from hooking.hooks import dialogue
from types import SimpleNamespace
from unittest.mock import Mock, patch


class TestDialoguePipeline(unittest.TestCase):
    def _run(self, original, *, target="pt-BR", translated=None, reads=None, overlay=True):
        translator = SimpleNamespace(
            language=LanguageContext.create(target),
            translate=Mock(return_value=translated),
        )
        reads = reads or {}

        def read_dialogue(_text, language_code):
            return reads.get(language_code)

        with (
            patch("hooking.hooks.dialogue._init_locals"),
            patch("hooking.hooks.dialogue._translator", translator),
            patch("hooking.hooks.dialogue._read_dialogue", side_effect=read_dialogue),
            patch("hooking.hooks.dialogue.search_bad_strings", return_value=None),
            patch("hooking.hooks.dialogue.should_translate_text", return_value=overlay),
            patch("hooking.hooks.dialogue.write_dialogue_translation") as write,
            patch("hooking.hooks.dialogue._prepare_output", side_effect=lambda text: text),
        ):
            result = dialogue.dialogue_replacement(original, "NPC")
        return result, translator.translate, write

    def test_target_cache_wins_without_api_call(self):
        result, translate, write = self._run(
            "こんにちは", reads={"pt-BR": "Ola do cache", "en": "Hello"}
        )
        self.assertEqual(result, "Ola do cache")
        translate.assert_not_called()
        write.assert_not_called()

    def test_choice_translates_prose_and_options_with_identical_controls(self):
        original = "どこへ行きますか？<select>\n入口\n駅\n<select_end>"
        packed = "Where would you like to go?<select>\nEntrance\nStation\n<select_end>"
        translated = "Para onde quer ir?<select>\nEntrada\nEstacao\n<select_end>"
        result, translate, write = self._run(original, translated=translated, reads={"en": packed})
        self.assertEqual(result, translated)
        self.assertEqual(translate.call_args.kwargs["text"], packed)
        self.assertTrue(translate.call_args.kwargs["translate_choices"])
        write.assert_called_once_with(original, result, "NPC", language_code="pt-BR")

    def test_choice_control_without_english_entry_translates_source_block(self):
        original = "質問<yesno>"
        translated = "Voce concorda?<yesno>"
        result, translate, write = self._run(original, translated=translated)
        self.assertEqual(result, translated)
        self.assertEqual(translate.call_args.kwargs["text"], original)
        write.assert_called_once_with(original, translated, "NPC", language_code="pt-BR")

    def test_english_target_translates_japanese_yesno_when_pack_entry_is_missing(self):
        original = "中に入りますか？<yesno><break>"
        translated = "Enter?<yesno><break>"
        result, translate, write = self._run(original, target="en", translated=translated)
        self.assertEqual(result, translated)
        self.assertEqual(translate.call_args.kwargs["text"], original)
        write.assert_called_once_with(original, translated, "NPC", language_code="en")

    def test_choice_without_pack_rejects_changed_controls(self):
        original = "質問<select>\nはい\nいいえ\n<select_end>"
        invalid = "Pergunta<select>\nSim\nNao"
        result, translate, write = self._run(original, translated=invalid)
        self.assertEqual(result, original)
        translate.assert_called_once()
        write.assert_not_called()

    def test_choice_cache_with_missing_control_is_ignored(self):
        original = "質問<select>\n入口\n<select_end>"
        packed = "Question<select>\nEntrance\n<select_end>"
        bad_cache = "Pergunta<select>\nEntrada traduzida"
        result, translate, write = self._run(
            original,
            translated=None,
            reads={"en": packed, "pt-BR": bad_cache},
        )
        self.assertEqual(result, packed)
        translate.assert_called_once()
        write.assert_not_called()

    def test_old_prose_only_choice_cache_is_upgraded(self):
        original = "質問<select>\n入口\n<select_end>"
        packed = "Question<select>\nEntrance\n<select_end>"
        old_cache = "Pergunta<select>\nEntrance\n<select_end>"
        translated = "Pergunta<select>\nEntrada\n<select_end>"
        result, translate, write = self._run(
            original,
            translated=translated,
            reads={"en": packed, "pt-BR": old_cache},
        )
        self.assertEqual(result, translated)
        translate.assert_called_once()
        write.assert_called_once()

    def test_valid_choice_cache_is_reused_without_api(self):
        original = "質問<yesno>"
        packed = "Do you agree?<yesno>"
        cached = "Voce concorda?<yesno>"
        result, translate, write = self._run(original, reads={"en": packed, "pt-BR": cached})
        self.assertEqual(result, cached)
        translate.assert_not_called()
        write.assert_not_called()

    def test_api_failure_falls_back_to_real_english_pack_entry(self):
        result, translate, write = self._run("日本語", translated=None, reads={"en": "English fallback"})
        self.assertEqual(result, "English fallback")
        translate.assert_called_once()
        write.assert_not_called()

    def test_api_failure_without_pack_entry_keeps_original(self):
        result, _translate, write = self._run("日本語", translated="")
        self.assertEqual(result, "日本語")
        write.assert_not_called()

    def test_disabled_overlay_uses_english_pack_without_api(self):
        result, translate, _write = self._run("日本語", reads={"en": "English pack"}, overlay=False)
        self.assertEqual(result, "English pack")
        translate.assert_not_called()

    def test_tagless_choice_list_is_translated_line_by_line(self):
        original = "Buy\nSell\nCancel"
        wrapped = "<select>\nComprar\nVender\nCancelar\n<select_end>"
        result, translate, write = self._run(original, translated=wrapped)
        self.assertEqual(result, "Comprar\nVender\nCancelar")
        self.assertEqual(translate.call_args.kwargs["text"], "<select>\nBuy\nSell\nCancel\n<select_end>")
        write.assert_called_once_with(
            original,
            "Comprar\nVender\nCancelar",
            "NPC",
            language_code="pt-BR",
        )

    def test_long_translation_is_not_shortened_or_given_fake_ellipsis(self):
        translated = "Bem-vindo a Loja de Itens. Como posso ajudar voce hoje?"
        result, _translate, _write = self._run("いらっしゃいませ", translated=translated)
        self.assertEqual(result, translated)
        self.assertNotIn("...", result)

    def test_japanese_provider_failure_is_not_romanized_as_target_output(self):
        translator = SimpleNamespace(language=LanguageContext.create("pt-BR"))
        with patch("hooking.hooks.dialogue._translator", translator):
            self.assertEqual(dialogue._prepare_output("こうして道行く人"), "こうして道行く人")


if __name__ == "__main__":
    unittest.main()
