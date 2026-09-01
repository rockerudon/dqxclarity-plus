import common.db_ops as db_ops
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from unittest.mock import patch


class TestMultilingualDatabase(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        db_ops.create_db_schema(self.path)
        original_init = db_ops.init_db
        self.patcher = patch("common.db_ops.init_db", side_effect=lambda db_path=None: original_init(self.path))
        self.patcher.start()
        db_ops._dialogue_variant_rows.cache_clear()
        db_ops.generate_canonical_glossary.cache_clear()

    def tearDown(self):
        db_ops._dialogue_variant_rows.cache_clear()
        db_ops.generate_canonical_glossary.cache_clear()
        self.patcher.stop()
        os.remove(self.path)

    def test_english_legacy_column_remains_compatible(self):
        db_ops.sql_write("日本語", "English", "dialog", language_code="en")
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute("SELECT en FROM dialog WHERE ja = ?", ("日本語",)).fetchone()[0], "English")
        self.assertEqual(db_ops.sql_read("日本語", "dialog", language_code="en"), "English")

    def test_dynamic_cache_is_isolated_between_en_and_pt_br(self):
        db_ops.sql_write("日本語", "English", "dialog", language_code="en")
        self.assertIsNone(db_ops.sql_read("日本語", "dialog", language_code="pt-BR"))
        db_ops.sql_write("日本語", "Português completo", "dialog", language_code="pt-BR")
        self.assertEqual(db_ops.sql_read("日本語", "dialog", language_code="pt-BR"), "Português completo")
        self.assertEqual(db_ops.sql_read("日本語", "dialog", language_code="en"), "English")

    def test_full_portuguese_is_preserved_in_cache(self):
        value = "Você recebeu uma bênção no coração."
        db_ops.sql_write("祝福", value, "walkthrough", language_code="pt-BR")
        self.assertEqual(db_ops.sql_read("祝福", "walkthrough", language_code="pt-BR"), value)

    def test_dialogue_keeps_npc_context_for_non_english(self):
        db_ops.write_dialogue_translation("こんにちは", "Olá", "Anlúcia", language_code="pt-BR")
        with closing(sqlite3.connect(self.path)) as conn:
            npc_name, english = conn.execute("SELECT npc_name, en FROM dialog WHERE ja = ?", ("こんにちは",)).fetchone()
        self.assertEqual(npc_name, "Anlúcia")
        self.assertIsNone(english)

    def test_manual_translation_has_priority(self):
        db_ops.write_translation("鍵", "automatic", "quests", language_code="en", translation_kind="machine")
        db_ops.write_translation("鍵", "manual", "quests", language_code="en", translation_kind="manual")
        self.assertEqual(db_ops.sql_read("鍵", "quests", language_code="en"), "manual")

    def test_english_fallback_must_be_explicit(self):
        db_ops.sql_write("町", "Town", "story_so_far", language_code="en")
        self.assertIsNone(db_ops.read_translation("町", "story_so_far", language_code="pt-BR"))
        self.assertEqual(
            db_ops.read_translation("町", "story_so_far", language_code="pt-BR", allow_english_fallback=True),
            "Town",
        )

    def test_dialogue_variant_preserves_choice_control_structure(self):
        db_ops.sql_write(
            "質問<select>\nA\nB\n<select_end>",
            "Question<select>\nA\nB\n<select_end>",
            "dialog",
            language_code="en",
        )
        self.assertIsNone(db_ops.read_dialogue_translation_variant("質問<yesno>", language_code="en"))

    def test_dialogue_variant_accepts_cosmetic_tag_and_spacing_changes(self):
        db_ops.sql_write("「<attr 1>こんにちは<end_attr>」", "Hello", "dialog", language_code="en")
        self.assertEqual(db_ops.read_dialogue_translation_variant(" こんにちは ", language_code="en"), "Hello")

    def test_dialogue_variant_reads_untouched_legacy_english_pack(self):
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute(
                "INSERT INTO dialog (ja, npc_name, en) VALUES (?, ?, ?)",
                ("「<attr 1>古い<end_attr>」", "NPC", "Legacy English"),
            )
            conn.commit()
        db_ops._dialogue_variant_rows.cache_clear()
        self.assertEqual(
            db_ops.read_dialogue_translation_variant(" 古い ", language_code="en"),
            "Legacy English",
        )

    def test_ambiguous_dialogue_variant_is_not_used(self):
        db_ops.write_translation("「同じ」", "First", "dialog", language_code="en", context="one")
        db_ops.write_translation("同 じ", "Second", "dialog", language_code="en", context="two")
        self.assertIsNone(db_ops.read_dialogue_translation_variant("同じ", language_code="en"))

    def test_dialogue_write_invalidates_variant_cache(self):
        self.assertIsNone(db_ops.read_dialogue_translation_variant("新規", language_code="pt-BR"))
        db_ops.sql_write("「新規」", "Novo", "dialog", language_code="pt-BR")
        self.assertEqual(db_ops.read_dialogue_translation_variant("新規", language_code="pt-BR"), "Novo")

    def test_canonical_glossary_keeps_names_but_rejects_descriptions(self):
        with closing(sqlite3.connect(self.path)) as conn:
            conn.executemany(
                "INSERT INTO m00_strings (ja, en, file) VALUES (?, ?, ?)",
                [
                    ("薬草", "Medicinal Herb", "items"),
                    ("説明", "Restores\nsome HP.", "items"),
                ],
            )
            conn.executemany(
                "INSERT INTO glossary (ja, en) VALUES (?, ?)",
                [
                    ("グレン城下町駅", "Glen Castle Town Station"),
                    ("アストルティア", "Astoltia"),
                    ("どうしますか", "What would you like to do"),
                    ("幻惑", "Dazzling"),
                ],
            )
            conn.commit()
        db_ops.generate_canonical_glossary.cache_clear()

        canonical = db_ops.generate_canonical_glossary()

        self.assertEqual(canonical["薬草"], "Medicinal Herb")
        self.assertEqual(canonical["グレン城下町駅"], "Glen Castle Town Station")
        self.assertEqual(canonical["アストルティア"], "Astoltia")
        self.assertNotIn("説明", canonical)
        self.assertNotIn("どうしますか", canonical)
        self.assertNotIn("幻惑", canonical)

    def test_machine_cache_version_invalidates_only_obsolete_generated_text(self):
        db_ops.write_translation("古い機械", "Old machine", "dialog", language_code="pt-BR")
        db_ops.write_translation(
            "手動",
            "Manual",
            "dialog",
            language_code="pt-BR",
            translation_kind="manual",
        )
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute(
                "UPDATE translation_metadata SET value = 'old' WHERE key = 'machine_cache_version'"
            )
            conn.commit()

        db_ops.create_db_schema(self.path)

        self.assertIsNone(db_ops.read_translation("古い機械", "dialog", language_code="pt-BR"))
        self.assertEqual(db_ops.read_translation("手動", "dialog", language_code="pt-BR"), "Manual")

        # Once upgraded, newly generated entries survive ordinary startups.
        db_ops.write_translation("新しい機械", "New machine", "dialog", language_code="pt-BR")
        db_ops.create_db_schema(self.path)
        self.assertEqual(db_ops.read_translation("新しい機械", "dialog", language_code="pt-BR"), "New machine")


class TestLegacyCompatibility(unittest.TestCase):
    def test_old_english_database_remains_readable_without_copying_rows(self):
        handle, path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        try:
            with closing(sqlite3.connect(path)) as conn:
                conn.execute("CREATE TABLE dialog (ja TEXT NOT NULL UNIQUE, npc_name TEXT, en TEXT)")
                conn.execute("INSERT INTO dialog (ja, npc_name, en) VALUES (?, ?, ?)", ("古い", "NPC", "Old"))
                conn.commit()
            db_ops.create_db_schema(path)
            with closing(sqlite3.connect(path)) as conn:
                self.assertEqual(conn.execute("SELECT en FROM dialog WHERE ja = '古い'").fetchone()[0], "Old")
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM translation_values").fetchone()[0], 0)
            original_init = db_ops.init_db
            with patch("common.db_ops.init_db", side_effect=lambda db_path=None: original_init(path)):
                self.assertEqual(db_ops.sql_read("古い", "dialog", language_code="en"), "Old")
            db_ops.create_db_schema(path)
            with closing(sqlite3.connect(path)) as conn:
                self.assertEqual(conn.execute("SELECT en FROM dialog WHERE ja = '古い'").fetchone()[0], "Old")
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
