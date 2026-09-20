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

    def test_free_google_adapters_avoid_the_browser_widget_client(self):
        config = MagicMock(target_language="pt-BR", source_language="ja")
        with (
            patch("common.translators.googletranslatefree.UserConfig", return_value=config),
            patch("common.translators.googletranslatepa.UserConfig", return_value=config),
        ):
            self.assertEqual(GoogleTranslatePa._CLIENT, GoogleTranslateFree._json_clients[0])
            self.assertNotEqual(GoogleTranslateFree._json_clients[0], "gtx")

    @staticmethod
    def __json_response(*segments: str):
        response = MagicMock()
        response.json.return_value = [[(segment, "", None, None) for segment in segments]]
        return response

    @staticmethod
    def __rate_limited_response():
        response = MagicMock()
        response.raise_for_status.side_effect = requests.HTTPError("429", response=MagicMock(status_code=429))
        return response

    def test_json_request_uses_mapped_target(self):
        config = MagicMock(target_language="pt-BR", source_language="ja")
        with patch("common.translators.googletranslatefree.UserConfig", return_value=config):
            translator = GoogleTranslateFree()
        translator.session.get = MagicMock(return_value=self.__json_response("Olá"))

        self.assertEqual(translator.translate(["こんにちは"]), ["Olá"])
        params = translator.session.get.call_args.kwargs["params"]
        self.assertEqual(params["tl"], "pt")
        self.assertEqual(params["sl"], "ja")

    def test_json_uses_auto_source_for_api_overlay(self):
        config = MagicMock(target_language="pt-BR", source_language="auto")
        with patch("common.translators.googletranslatefree.UserConfig", return_value=config):
            translator = GoogleTranslateFree()
        translator.session.get = MagicMock(return_value=self.__json_response("Bem-vindo"))

        self.assertEqual(translator.translate(["Welcome"]), ["Bem-vindo"])
        self.assertEqual(translator.session.get.call_args.kwargs["params"]["sl"], "auto")

    def test_rate_limited_client_rotates_and_stays_rotated(self):
        config = MagicMock(target_language="pt-BR", source_language="auto")
        with patch("common.translators.googletranslatefree.UserConfig", return_value=config):
            translator = GoogleTranslateFree()
        translator.session.get = MagicMock(
            side_effect=[
                self.__rate_limited_response(),
                self.__json_response("Bem-vindo"),
                self.__json_response("Até logo"),
            ]
        )

        with patch("common.translators.googletranslatefree.time.sleep"):
            self.assertEqual(translator.translate(["Welcome"]), ["Bem-vindo"])
        self.assertEqual(translator.session.get.call_count, 2)
        working_client = translator.session.get.call_args_list[1].kwargs["params"]["client"]
        self.assertNotEqual(working_client, GoogleTranslateFree._json_clients[0])
        self.assertEqual(translator._client_index, 1)
        self.assertEqual(translator._blocked_until, 0.0)

        with patch("common.translators.googletranslatefree.time.sleep"):
            self.assertEqual(translator.translate(["Bye"]), ["Até logo"])
        self.assertEqual(translator.session.get.call_count, 3)
        self.assertEqual(translator.session.get.call_args.kwargs["params"]["client"], working_client)

    def test_free_google_batches_choice_lines_into_one_request(self):
        config = MagicMock(target_language="pt-BR", source_language="auto")
        with patch("common.translators.googletranslatefree.UserConfig", return_value=config):
            translator = GoogleTranslateFree()
        translator.session.get = MagicMock(
            return_value=self.__json_response(
                "Pergunta traduzida\nZXQSEGMENT0001QXZ\nAceitar\nZXQSEGMENT0002QXZ\nRecusar"
            )
        )

        result = translator.translate(["Question", "Accept", "Decline"])

        self.assertEqual(result, ["Pergunta traduzida", "Aceitar", "Recusar"])
        translator.session.get.assert_called_once()
        request_text = translator.session.get.call_args.kwargs["params"]["q"]
        self.assertIn("ZXQSEGMENT0001QXZ", request_text)
        self.assertIn("ZXQSEGMENT0002QXZ", request_text)

    def test_lost_segment_sentinel_tries_the_next_client(self):
        config = MagicMock(target_language="pt-BR", source_language="auto")
        with patch("common.translators.googletranslatefree.UserConfig", return_value=config):
            translator = GoogleTranslateFree()
        translator.session.get = MagicMock(
            side_effect=[
                self.__json_response("Aceitar\nZXQSEGMENT0002QXZ\nRecusar"),
                self.__json_response("Pergunta\nZXQSEGMENT0001QXZ\nAceitar\nZXQSEGMENT0002QXZ\nRecusar"),
            ]
        )

        with patch("common.translators.googletranslatefree.time.sleep"):
            self.assertEqual(
                translator.translate(["Question", "Accept", "Decline"]),
                ["Pergunta", "Aceitar", "Recusar"],
            )
        self.assertEqual(translator.session.get.call_count, 2)

    def test_free_google_reuses_successful_phrase_cache(self):
        config = MagicMock(target_language="pt-BR", source_language="auto")
        with patch("common.translators.googletranslatefree.UserConfig", return_value=config):
            translator = GoogleTranslateFree()
        translator.session.get = MagicMock(return_value=self.__json_response("Bem-vindo"))

        self.assertEqual(translator.translate(["Welcome"]), ["Bem-vindo"])
        self.assertEqual(translator.translate(["Welcome"]), ["Bem-vindo"])
        translator.session.get.assert_called_once()

    def test_free_google_cools_down_only_after_every_client_is_rate_limited(self):
        config = MagicMock(target_language="pt-BR", source_language="auto")
        with patch("common.translators.googletranslatefree.UserConfig", return_value=config):
            translator = GoogleTranslateFree()
        translator.session.get = MagicMock(
            side_effect=[self.__rate_limited_response() for _ in GoogleTranslateFree._json_clients]
        )

        with patch("common.translators.googletranslatefree.time.sleep"):
            self.assertEqual(translator.translate(["Question", "Accept"]), ["", ""])
        self.assertEqual(translator.session.get.call_count, len(GoogleTranslateFree._json_clients))
        self.assertGreater(translator._blocked_until, 0.0)

        self.assertEqual(translator.translate(["Question", "Accept"]), ["", ""])
        self.assertEqual(translator.session.get.call_count, len(GoogleTranslateFree._json_clients))

    def test_free_google_returns_to_google_after_cooldown(self):
        config = MagicMock(target_language="pt-BR", source_language="auto")
        with patch("common.translators.googletranslatefree.UserConfig", return_value=config):
            translator = GoogleTranslateFree()
        translator._blocked_until = 0.0
        translator._consecutive_throttles = 2
        translator.session.get = MagicMock(return_value=self.__json_response("De volta ao Google"))

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

        self.assertEqual(cooldowns, [5.0, 15.0, 30.0, 30.0, 30.0])
        self.assertEqual(translator._blocked_until, 530.0)

    def test_free_google_success_resets_progressive_cooldown(self):
        config = MagicMock(target_language="pt-BR", source_language="auto")
        with patch("common.translators.googletranslatefree.UserConfig", return_value=config):
            translator = GoogleTranslateFree()
        translator._consecutive_throttles = 3
        translator.session.get = MagicMock(return_value=self.__json_response("Bem-vindo"))

        self.assertEqual(translator.translate(["Welcome"]), ["Bem-vindo"])
        self.assertEqual(translator._consecutive_throttles, 0)

    def test_prewarm_selects_a_client_without_cooling_down(self):
        config = MagicMock(target_language="pt-BR", source_language="ja")
        with patch("common.translators.googletranslatefree.UserConfig", return_value=config):
            translator = GoogleTranslateFree()
        translator.session.get = MagicMock(
            side_effect=[self.__rate_limited_response(), self.__json_response("Olá")]
        )

        with patch("common.translators.googletranslatefree.time.sleep"):
            self.assertTrue(translator.prewarm())
        self.assertEqual(translator._client_index, 1)
        self.assertEqual(translator._blocked_until, 0.0)
        self.assertEqual(translator._translation_cache, {})

        translator.session.get.side_effect = None
        translator.session.get.return_value = self.__json_response("Bem-vindo")
        with patch("common.translators.googletranslatefree.time.sleep"):
            self.assertEqual(translator.translate(["Welcome"]), ["Bem-vindo"])
        self.assertEqual(
            translator.session.get.call_args.kwargs["params"]["client"],
            GoogleTranslateFree._json_clients[1],
        )

    def test_prewarm_leaves_no_cooldown_when_every_client_is_blocked(self):
        config = MagicMock(target_language="pt-BR", source_language="ja")
        with patch("common.translators.googletranslatefree.UserConfig", return_value=config):
            translator = GoogleTranslateFree()
        translator.session.get = MagicMock(
            side_effect=[self.__rate_limited_response() for _ in range(2 * len(GoogleTranslateFree._json_clients))]
        )

        with patch("common.translators.googletranslatefree.time.sleep"):
            self.assertFalse(translator.prewarm())
        self.assertEqual(translator._blocked_until, 0.0)

        with patch("common.translators.googletranslatefree.time.sleep"):
            self.assertEqual(translator.translate(["Welcome"]), [""])
        self.assertGreater(translator._blocked_until, 0.0)

    def test_prewarm_stops_after_one_request_when_the_host_is_unreachable(self):
        config = MagicMock(target_language="pt-BR", source_language="ja")
        with patch("common.translators.googletranslatefree.UserConfig", return_value=config):
            translator = GoogleTranslateFree()
        translator.session.get = MagicMock(side_effect=requests.ConnectionError("no route to host"))

        with patch("common.translators.googletranslatefree.time.sleep"):
            self.assertFalse(translator.prewarm())
        translator.session.get.assert_called_once()


if __name__ == "__main__":
    unittest.main()
