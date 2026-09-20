import unittest
from common.language import LanguageContext
from hooking.hooks import network_text
from unittest.mock import ANY, MagicMock, patch


class NetworkTextTests(unittest.TestCase):
    def setUp(self) -> None:
        network_text._m00_text = {}
        network_text._custom_text_logger = MagicMock()
        network_text._chat_translator = None
        network_text._chat_pending.clear()
        network_text._chat_seen.clear()
        network_text._chat_results.clear()
        network_text._chat_events.clear()
        network_text._chat_occurrences.clear()
        network_text._chat_last_occurrence.clear()
        while not network_text._chat_queue.empty():
            network_text._chat_queue.get_nowait()
            network_text._chat_queue.task_done()

    def test_chat_request_posts_a_replacement_response(self) -> None:
        script = MagicMock()
        with (
            patch(
                "hooking.hooks.network_text.chat_text_replacement",
                return_value="Obrigado!",
            ),
            patch(
                "hooking.hooks.network_text.prepare_game_text",
                side_effect=lambda text, _language: text,
            ),
        ):
            network_text.on_message(
                {
                    "type": "send",
                    "payload": {
                        "type": "get_chat_replacement",
                        "text": "ありがとう！",
                        "category": '<%sM_speaker> "<%sM_chat>"',
                    },
                },
                None,
                script,
            )

        script.post.assert_called_once_with({"type": "chat_replacement", "text": "Obrigado!"})

    def test_chat_worker_translates_without_database_cache(self) -> None:
        translator = MagicMock()
        translator.translate.return_value = "Obrigado!"
        with (
            patch("hooking.hooks.network_text._init_chat_translator", return_value=translator),
            patch("hooking.hooks.network_text.sql_write") as write,
        ):
            result = network_text._translate_chat_text("ありがとう！", "<%sM_chat>")

        self.assertEqual(result, "Obrigado!")
        translator.translate.assert_called_once_with(
            "ありがとう！",
            wrap_width=9999,
            max_lines=None,
            add_brs=False,
        )
        write.assert_not_called()

    def test_event_banner_without_pack_entry_is_translated_live(self) -> None:
        source = "秋イベント「神の月の感謝祭2」 "
        translator = MagicMock()
        translator.translate.return_value = "Autumn Event: Moon Festival 2"
        with (
            patch("hooking.hooks.network_text.Translator", return_value=translator),
            patch("hooking.hooks.network_text._language", LanguageContext.create("en")),
            patch("hooking.hooks.network_text.sql_write") as write,
        ):
            result = network_text.network_text_replacement(source, "<%sEV_QUEST_NAME>")

        self.assertEqual(result, "Autumn Event: Moon Festival 2")
        self.assertLessEqual(len(result.encode("utf-8")), len(source.encode("utf-8")))
        translator.translate.assert_called_once_with(source, wrap_width=9999, add_brs=False)
        write.assert_not_called()
        network_text._custom_text_logger.info.assert_not_called()

    def test_overlong_event_banner_is_cut_to_the_source_buffer_and_logged(self) -> None:
        source = "秋イベント「神の月の感謝祭2」 "
        budget = len(source.encode("utf-8"))
        translator = MagicMock()
        translator.translate.return_value = "The Autumn Moon Thanksgiving Festival Edition Two"
        network_text._m00_text = {}
        with (
            patch("hooking.hooks.network_text.Translator", return_value=translator),
            patch("hooking.hooks.network_text._language", LanguageContext.create("en")),
        ):
            result = network_text.network_text_replacement(source, "<%sM_header>")

        self.assertLessEqual(len(result.encode("utf-8")), budget)
        self.assertTrue(result.startswith("The Autumn Moon"))
        network_text._custom_text_logger.info.assert_called_once_with(f"--\n>><%sM_header> ::\n{source}")

    def test_pack_entry_still_wins_for_event_banners(self) -> None:
        source = "第39回 バトルグランプリ・SP"
        network_text._m00_text = {source: "39th Battle GP SP"}
        with patch("hooking.hooks.network_text.Translator") as translator_class:
            self.assertEqual(network_text.network_text_replacement(source, "<%sM_header>"), "39th Battle GP SP")
        translator_class.assert_not_called()

    def test_failed_banner_translation_keeps_the_original_text_and_logs_it(self) -> None:
        source = "幻の海トラシュカ2026　"
        translator = MagicMock()
        translator.translate.return_value = ""
        with (
            patch("hooking.hooks.network_text.Translator", return_value=translator),
            patch("hooking.hooks.network_text._language", LanguageContext.create("pt-BR")),
        ):
            self.assertEqual(network_text.network_text_replacement(source, "<%sM_header>"), source)
        network_text._custom_text_logger.info.assert_called_once_with(f"--\n>><%sM_header> ::\n{source}")

    def test_standalone_speaker_uses_local_romanization_only(self) -> None:
        for name, expected in (("おぴよ", "Opiyo"), ("カリナ", "Karina"), ("ベンジャミン", "Benjamin")):
            with (
                self.subTest(name=name),
                patch("hooking.hooks.network_text.Translator") as translator,
                patch("hooking.hooks.network_text._init_data") as init_data,
            ):
                result = network_text.network_text_replacement(name, "<%sM_speaker>")
                self.assertEqual(result, "\x04" + expected)
                self.assertLessEqual(len(result.encode("utf-8")), len(name.encode("utf-8")))
                translator.assert_not_called()
                init_data.assert_not_called()

    def test_standalone_speaker_preserves_padding_and_existing_marker(self) -> None:
        self.assertEqual(network_text.chat_speaker_replacement("　 \x04おぴよ  "), "　 \x04Opiyo  ")

    def test_speaker_handler_does_not_reapply_ascii_policy_to_controls(self) -> None:
        script = MagicMock()
        with patch("hooking.hooks.network_text.prepare_game_text") as prepare:
            network_text.on_message(
                {"type": "send", "payload": {
                    "type": "get_replacement", "text": "　 \x04おぴよ  ", "category": "<%sM_speaker>",
                }}, None, script,
            )
        script.post.assert_called_once_with({"type": "replacement", "text": "　 \x04Opiyo  "})
        prepare.assert_not_called()

    def test_speaker_keeps_existing_ascii_unsupported_names_and_too_small_buffers(self) -> None:
        for name in ("Opiyo", "\x04Opiyo", "太郎", "し", "", "\x04"):
            with self.subTest(name=name):
                self.assertEqual(network_text.chat_speaker_replacement(name), name)

    def test_composed_chat_output_preserves_measured_speaker_prefix(self) -> None:
        category = '<%sM_speaker> "<%sM_chat>"'
        source = "ありがとうございます"
        translation = "Você está aqui, José!"
        network_text._chat_results[source] = translation
        # Include native Japanese names, pre-localized names, controls, and
        # both ASCII and full-width padding. None may pass through AnyAscii.
        for language in ("en", "pt-BR", "es", "fr"):
            for prefix in ('   \x04あや "', '　 はじめ "', '  \x04Rokku "', ' \x04~Érudi~ "'):
                for suffix in ('', '"'):
                    with self.subTest(language=language, prefix=prefix, suffix=suffix):
                        script = MagicMock()
                        with (
                            patch("hooking.hooks.network_text._language", LanguageContext.create(language)),
                            patch("hooking.hooks.network_text._init_data"),
                            patch("hooking.hooks.network_text.should_translate_text", return_value=True),
                            patch("hooking.hooks.network_text._emit_chat_translation"),
                        ):
                            network_text.on_message(
                                {"type": "send", "payload": {
                                    "type": "get_chat_replacement",
                                    "text": f"{prefix}{source}{suffix}",
                                    "category": category,
                                }}, None, script,
                            )
                        output = script.post.call_args.args[0]["text"]
                        self.assertEqual(output, f"{prefix}Voce esta aqui, Jose!{suffix}")
                        prefix_bytes = prefix.encode("utf-8")
                        self.assertEqual(output.encode("utf-8")[:len(prefix_bytes)], prefix_bytes)
        self.assertEqual(network_text._chat_results[source], translation)

    def test_standalone_chat_output_still_applies_display_policy(self) -> None:
        network_text._chat_results["ありがとう"] = "Obrigadão!"
        script = MagicMock()
        with (
            patch("hooking.hooks.network_text._language", LanguageContext.create("pt-BR")),
            patch("hooking.hooks.network_text._init_data"),
            patch("hooking.hooks.network_text.should_translate_text", return_value=True),
        ):
            network_text.on_message(
                {"type": "send", "payload": {
                    "type": "get_chat_replacement",
                    "text": "ありがとう",
                    "category": "<%sM_chat>",
                }}, None, script,
            )
        script.post.assert_called_once_with({"type": "chat_replacement", "text": "Obrigadao!"})

    def test_observed_sender_fields_are_romanized_and_repadded(self) -> None:
        for name, padding in (("こめおし", 4), ("ホープスター", 0), ("ルーテシア", 2),
                              ("ジョアンナ", 2), ("ロマ", 8), ("あや", 8), ("いふ", 8), ("カンパチ", 4)):
            for opening in ('"', '['):
                with self.subTest(name=name, opening=opening):
                    prefix = " " * padding + name + " " + opening
                    result = network_text._romanize_chat_prefix(prefix)
                    romanized = network_text.transliterate_player_name(name)
                    self.assertNotEqual(result, prefix)
                    self.assertEqual(result, ("\x04" + romanized).rjust(12) + " " + opening)
                    self.assertLessEqual(len(result.encode("utf-8")), len(prefix.encode("utf-8")))
                    self.assertEqual(network_text._romanize_chat_prefix(result), result)

    def test_unknown_sender_layout_and_existing_localized_names_are_untouched(self) -> None:
        for prefix in ('ロマ "', '　 ロマ "', '    太郎 "', '  \x04Rokku "',
                       '     \x04Kanapi [', '  \x05ルーテシア "', '            "'):
            with self.subTest(prefix=prefix):
                self.assertEqual(network_text._romanize_chat_prefix(prefix), prefix)

    def test_pending_translation_romanizes_only_sender_without_touching_body(self) -> None:
        category = '<%sM_speaker> "<%sM_chat>"'
        body = '  こんにちは！  '
        original = '        ロマ "' + body + '"'
        script = MagicMock()
        with (
            patch("hooking.hooks.network_text.should_translate_text", return_value=True),
            patch("hooking.hooks.network_text._queue_chat_translation", return_value=MagicMock()) as enqueue,
            patch("hooking.hooks.network_text.prepare_game_text") as prepare,
            patch("hooking.hooks.network_text._emit_chat_translation") as emit,
        ):
            network_text.on_message({"type": "send", "payload": {
                "type": "get_chat_replacement", "text": original, "category": category,
            }}, None, script)
        self.assertEqual(script.post.call_args.args[0]["text"], '       \x04Roma "' + body + '"')
        enqueue.assert_called_once_with(body.strip(), category)
        prepare.assert_not_called()
        emit.assert_called_once_with(body.strip(), body.strip(), category, "Roma",
                                     event_id=ANY, is_update=False, recipient="", status="Waiting for translation")

    def test_cached_body_and_composed_name_are_both_replaced(self) -> None:
        network_text._chat_results['ありがとう'] = 'Você está aqui!'
        script = MagicMock()
        with (
            patch("hooking.hooks.network_text.should_translate_text", return_value=True),
            patch("hooking.hooks.network_text._language", LanguageContext.create("pt-BR")),
            patch("hooking.hooks.network_text._init_data"),
            patch("hooking.hooks.network_text._emit_chat_translation") as emit,
        ):
            network_text.on_message({"type": "send", "payload": {
                "type": "get_chat_replacement", "text": '        ロマ "ありがとう"',
                "category": '<%sM_speaker> "<%sM_chat>"',
            }}, None, script)
        self.assertEqual(script.post.call_args.args[0]["text"], '       \x04Roma "Voce esta aqui!"')
        self.assertEqual(emit.call_args.args[3], "Roma")

    def test_bracket_stamp_uses_template_delimiter_even_with_quotes_in_caption(self) -> None:
        category = '<%sM_speaker> [<%sM_chat>]'
        body = 'Say "hello"!'
        with (
            patch("hooking.hooks.network_text.should_translate_text", return_value=False),
            patch("hooking.hooks.network_text._queue_chat_translation") as enqueue,
            patch("hooking.hooks.network_text._emit_chat_translation") as emit,
        ):
            result = network_text.chat_text_replacement('        ロマ [' + body + ']', category)
        self.assertEqual(result, '       \x04Roma [' + body + ']')
        emit.assert_called_once_with(body, body, category, "Roma",
                                     event_id=ANY, is_update=False, recipient="", status="")
        enqueue.assert_not_called()

    def test_bracket_stamp_reuses_body_translation_and_preserves_closing_bracket(self) -> None:
        category = '<%sM_speaker> [<%sM_chat>]'
        network_text._chat_results['ありがとう！'] = 'Thank you!'
        with (
            patch("hooking.hooks.network_text.should_translate_text", return_value=True),
            patch("hooking.hooks.network_text._emit_chat_translation") as emit,
        ):
            result = network_text.chat_text_replacement('     \x04Kanapi [ありがとう！]', category)
        self.assertEqual(result, '     \x04Kanapi [Thank you!]')
        self.assertEqual(emit.call_args.args[3], "Kanapi")

    def test_incomplete_bracket_template_never_becomes_a_player_message(self) -> None:
        with (
            patch("hooking.hooks.network_text._queue_chat_translation") as enqueue,
            patch("hooking.hooks.network_text._emit_chat_translation") as emit,
        ):
            result = network_text.chat_text_replacement('        ロマ', '<%sM_speaker> [<%sM_chat>]')
        self.assertEqual(result, '        ロマ')
        enqueue.assert_not_called()
        emit.assert_not_called()

    def test_chat_history_duplicate_is_queued_only_once(self) -> None:
        with (
            patch("hooking.hooks.network_text.should_translate_text", return_value=True),
            patch("hooking.hooks.network_text._ensure_chat_worker"),
            patch("hooking.hooks.network_text.time.monotonic", return_value=100.0),
        ):
            first = network_text._queue_chat_translation("ありがとう！", "<%sM_chat>")
            duplicate = network_text._queue_chat_translation("ありがとう！", "<%sM_chat>")

        self.assertTrue(first)
        self.assertIs(first, duplicate)
        self.assertEqual(network_text._chat_queue.qsize(), 1)

    def test_busy_chat_never_grows_beyond_bounded_queue(self) -> None:
        with (
            patch("hooking.hooks.network_text.should_translate_text", return_value=True),
            patch("hooking.hooks.network_text._ensure_chat_worker"),
            patch("hooking.hooks.network_text.time.monotonic", return_value=100.0),
        ):
            accepted = [
                network_text._queue_chat_translation(f"日本語{i}", "<%sM_chat>")
                for i in range(network_text._CHAT_QUEUE_LIMIT)
            ]
            overloaded = network_text._queue_chat_translation("混雑", "<%sM_chat>")

        self.assertTrue(all(accepted))
        self.assertFalse(overloaded)
        self.assertEqual(network_text._chat_queue.qsize(), network_text._CHAT_QUEUE_LIMIT)

    def test_composed_chat_history_reuses_cached_translation(self) -> None:
        network_text._chat_results["ちょっとまってね"] = "Espere um pouco"
        with (
            patch("hooking.hooks.network_text.should_translate_text", return_value=True),
            patch("hooking.hooks.network_text._emit_chat_translation") as emit,
        ):
            result = network_text.chat_text_replacement(
                '\x04Misawa "ちょっとまってね',
                '<%sM_speaker> "<%sM_chat>"',
            )

        self.assertEqual(result, '\x04Misawa "Espere um pouco')
        emit.assert_called_once_with(
            "ちょっとまってね",
            "Espere um pouco",
            '<%sM_speaker> "<%sM_chat>"',
            "Misawa",
            event_id=ANY, is_update=False, recipient="", status="",
        )

    def test_same_row_is_not_republished_after_time_or_provider_cache_expiry(self) -> None:
        network_text._chat_results["ありがとう！"] = "Obrigado!"
        with (
            patch("hooking.hooks.network_text.should_translate_text", return_value=True),
            patch("hooking.hooks.network_text._emit_chat_translation") as emit,
            patch("hooking.hooks.network_text.time.monotonic", side_effect=[100.0, 101.0, 1000.0]),
        ):
            for _ in range(3):
                network_text.chat_text_replacement(
                    '\x04Mikko "ありがとう！',
                    '<%sM_speaker> "<%sM_chat>"',
                )

        self.assertEqual(emit.call_count, 1)

    def test_render_identity_cache_is_bounded(self) -> None:
        network_text._chat_results["ありがとう！"] = "Obrigado!"
        with (
            patch("hooking.hooks.network_text._CHAT_OCCURRENCE_LIMIT", 3),
            patch("hooking.hooks.network_text._emit_chat_translation"),
        ):
            for index in range(10):
                network_text._record_chat_occurrence("ありがとう！", "<%sM_chat>", "Mikko", str(index))
        self.assertEqual(len(network_text._chat_last_occurrence), 3)

    def test_identical_text_from_different_senders_is_kept(self) -> None:
        network_text._chat_results["ありがとう！"] = "Obrigado!"
        with patch("hooking.hooks.network_text._emit_chat_translation") as emit:
            for sender in ("Mikko", "Rock"):
                network_text._record_chat_occurrence("ありがとう！", "<%sM_chat>", sender, "0x1000")
        self.assertEqual(emit.call_count, 2)

    def test_replies_use_the_request_specific_channel(self) -> None:
        for kind, handler in (
            ("get_chat_replacement", "chat_text_replacement"),
            ("get_replacement", "network_text_replacement"),
        ):
            with self.subTest(kind=kind):
                script = MagicMock()
                with patch(f"hooking.hooks.network_text.{handler}", return_value="unchanged"):
                    network_text.on_message(
                        {"type": "send", "payload": {
                            "type": kind,
                            "text": "unchanged",
                            "category": "<%sM_chat>",
                            "response_type": "reply:123",
                        }}, None, script,
                    )
                script.post.assert_called_once_with({"type": "reply:123", "text": "unchanged"})

    def test_identical_adjacent_player_messages_in_different_rows_are_kept(self) -> None:
        network_text._chat_results["ありがとう！"] = "Obrigado!"
        with (
            patch("hooking.hooks.network_text.should_translate_text", return_value=True),
            patch("hooking.hooks.network_text._emit_chat_translation") as emit,
            patch("hooking.hooks.network_text.time.monotonic", return_value=100.0),
        ):
            network_text.chat_text_replacement(
                '\x04Mikko "ありがとう！',
                '<%sM_speaker> "<%sM_chat>"',
                "0x1000",
            )
            network_text.chat_text_replacement(
                '\x04Mikko "ありがとう！',
                '<%sM_speaker> "<%sM_chat>"',
                "0x2000",
            )

        self.assertEqual(emit.call_count, 2)

    def test_localized_stamp_is_emitted_with_sender_without_api(self) -> None:
        with (
            patch("hooking.hooks.network_text.should_translate_text", return_value=False),
            patch("hooking.hooks.network_text._emit_chat_translation") as emit,
            patch("hooking.hooks.network_text._queue_chat_translation") as enqueue,
        ):
            result = network_text.chat_text_replacement(
                '\x04Bekkii "[Thank you so much!]',
                '<%sM_speaker> "<%sM_chat>"',
            )

        self.assertEqual(result, '\x04Bekkii "[Thank you so much!]')
        emit.assert_called_once_with(
            "[Thank you so much!]",
            "[Thank you so much!]",
            '<%sM_speaker> "<%sM_chat>"',
            "Bekkii",
            event_id=ANY, is_update=False, recipient="", status="",
        )
        enqueue.assert_not_called()

    def test_incomplete_composed_chat_does_not_translate_speaker_as_message(self) -> None:
        with patch("hooking.hooks.network_text._queue_chat_translation") as enqueue:
            result = network_text.chat_text_replacement(
                "みさわ",
                '<%sM_speaker> "<%sM_chat>"',
            )

        self.assertEqual(result, "みさわ")
        enqueue.assert_not_called()

    def test_history_never_waits_for_provider(self) -> None:
        event = MagicMock()
        with (
            patch("hooking.hooks.network_text.should_translate_text", return_value=True),
            patch("hooking.hooks.network_text._queue_chat_translation", return_value=event),
            patch("hooking.hooks.network_text.time.monotonic", return_value=100.0),
        ):
            network_text.chat_text_replacement(
                '\x04Misawa "ちょっとまってね',
                '<%sM_speaker> "<%sM_chat>"',
                "0x1000",
            )

        event.wait.assert_not_called()

    def test_directed_chat_queues_body_once_and_updates_same_capture(self) -> None:
        category = '<%sM_speaker> "<%sM_chat>"'
        with (
            patch("hooking.hooks.network_text.should_translate_text", return_value=True),
            patch("hooking.hooks.network_text._ensure_chat_worker"),
            patch("hooking.hooks.network_text._emit_chat_translation") as emit,
        ):
            network_text.chat_text_replacement('        ロマ "こんにちは"', category, 'buffer')
            directed = '        ロマ "こんにちは" → \x04Ifu'
            network_text.chat_text_replacement(directed, category, 'buffer')
            network_text.chat_text_replacement(directed, category, 'buffer')
            self.assertEqual(network_text._chat_queue.qsize(), 1)
            self.assertEqual(network_text._chat_queue.queue[0][0], 'こんにちは')
            self.assertEqual(emit.call_count, 2)
            first, update = emit.call_args_list
            self.assertFalse(first.kwargs['is_update'])
            self.assertTrue(update.kwargs['is_update'])
            self.assertEqual(first.kwargs['event_id'], update.kwargs['event_id'])
            self.assertEqual(update.kwargs['recipient'], 'Ifu')
            network_text._chat_results['こんにちは'] = 'Hello'
            network_text._flush_chat_occurrences('こんにちは', 'Hello')
            translated = network_text.chat_text_replacement(directed, category, 'buffer')
        self.assertEqual(translated, '       \x04Roma "Hello" → \x04Ifu')
        self.assertEqual(emit.call_count, 3)

    def test_directed_bracket_message_preserves_recipient_controls(self) -> None:
        category = '<%sM_speaker> [<%sM_chat>]'
        text = '     \x04Kanapi [ありがとう！] → \x04Roma'
        self.assertEqual(network_text._split_chat_display(text, category),
                         ('     \x04Kanapi [', 'ありがとう！', '] → \x04Roma'))
        # An arrow without the template closing delimiter is part of the body.
        self.assertEqual(network_text._split_chat_display('Rock "go → there', '<%sM_speaker> "<%sM_chat>"'),
                         ('Rock "', 'go → there', ''))

    def test_pending_row_reserves_order_before_cache_hit_and_finishes_by_id(self) -> None:
        network_text._chat_results['cached'] = 'Already translated'
        with patch("hooking.hooks.network_text._emit_chat_translation") as emit:
            network_text._record_chat_occurrence('pending', 'chat', 'A', 'one')
            network_text._record_chat_occurrence('cached', 'chat', 'B', 'two')
            network_text._flush_chat_occurrences('pending', 'Translated later')
        first, second, update = emit.call_args_list
        self.assertEqual([first.args[0], second.args[0]], ['pending', 'cached'])
        self.assertFalse(second.kwargs['is_update'])
        self.assertTrue(update.kwargs['is_update'])
        self.assertEqual(update.kwargs['event_id'], first.kwargs['event_id'])
        self.assertNotEqual(second.kwargs['event_id'], first.kwargs['event_id'])

    def test_queue_overflow_retries_and_updates_original_capture(self) -> None:
        category = '<%sM_speaker> "<%sM_chat>"'
        with (
            patch("hooking.hooks.network_text.should_translate_text", return_value=True),
            patch("hooking.hooks.network_text._ensure_chat_worker"),
            patch("hooking.hooks.network_text._emit_chat_translation") as emit,
        ):
            for i in range(network_text._CHAT_QUEUE_LIMIT):
                network_text._queue_chat_translation(f'busy{i}', category)
            network_text.chat_text_replacement('Rock "overflow', category)
            original_id = emit.call_args_list[0].kwargs['event_id']
            self.assertIn('Queue full', emit.call_args.kwargs['status'])
            network_text._chat_queue.get_nowait()
            network_text._chat_queue.task_done()
            network_text.chat_text_replacement('Rock "overflow', category)
            self.assertIn('overflow', network_text._chat_pending)
            network_text._flush_chat_occurrences('overflow', 'Done')
        self.assertTrue(emit.call_args.kwargs['is_update'])
        self.assertEqual(emit.call_args.kwargs['event_id'], original_id)
        self.assertEqual(emit.call_args.args[1], 'Done')

    def test_pending_subscriptions_are_bounded_and_evicted_rows_do_not_return(self) -> None:
        with (
            patch("hooking.hooks.network_text._CHAT_OCCURRENCE_LIMIT", 3),
            patch("hooking.hooks.network_text._emit_chat_translation") as emit,
        ):
            for i in range(10):
                network_text._record_chat_occurrence(f'source{i}', 'chat', 'A', str(i))
            self.assertEqual(sum(len(rows) for rows in network_text._chat_occurrences.values()), 3)
            emit.reset_mock()
            network_text._flush_chat_occurrences('source0', 'Late')
            emit.assert_not_called()

    def test_failed_retry_does_not_erase_completed_launcher_translation(self) -> None:
        network_text._chat_results['source'] = 'Completed'
        with patch("hooking.hooks.network_text._emit_chat_translation") as emit:
            network_text._record_chat_occurrence('source', 'chat', 'A')
            network_text._chat_results.clear()
            network_text._record_chat_occurrence('source', 'chat', 'A')
            network_text._flush_chat_occurrences('source', None, 'Translation unavailable')
        self.assertEqual(emit.call_count, 1)

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
