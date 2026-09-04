import os
import unittest
import unittest.mock
from common.config import UserConfig


class TestConfig(unittest.TestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        if os.path.exists("user_settings.ini"):
            os.remove("user_settings.ini")

    def test_init_user_config(self) -> None:
        _ = UserConfig(".")
        self.assertTrue(os.path.exists("user_settings.ini"))

    def test_default_translate_service(self) -> None:
        config = UserConfig(".")
        self.assertEqual(config.translate_service, "googlefree")

    def test_api_translation_overlay_is_opt_in_and_switches_source_to_auto(self) -> None:
        config = UserConfig(".")
        self.assertFalse(config.api_translation_overlay)
        self.assertEqual(config.source_language, "ja")

        config.update(section="translation", key="api_translation_overlay", value="True")
        config = UserConfig(".")
        self.assertTrue(config.api_translation_overlay)
        self.assertEqual(config.source_language, "auto")

        config.update(section="translation", key="api_translation_overlay", value="False")

    def test_googlefree_yandex_fallback_is_opt_in(self) -> None:
        config = UserConfig(".")
        self.assertFalse(config.googlefree_yandex_fallback)

        config.update(section="translation", key="googlefree_yandex_fallback", value="True")
        config = UserConfig(".")
        self.assertTrue(config.googlefree_yandex_fallback)

        config.update(section="translation", key="googlefree_yandex_fallback", value="False")

    def test_update_translate_service(self) -> None:
        config = UserConfig(".")
        config.update(section="translation", key="translate_service", value="deepl")
        config = UserConfig(".")
        self.assertEqual(config.translate_service, "deepl")

    def test_update_translate_key(self) -> None:
        config = UserConfig(".")
        config.update(section="translation", key="translate_service", value="deepl")
        config.update(section="translation", key="translate_key", value="abcd1234")
        config = UserConfig(".")
        self.assertEqual(config.translate_service, "deepl")
        self.assertEqual(config.translate_key, "abcd1234")

    def test_chatgpt_model_default(self) -> None:
        config = UserConfig(".")
        self.assertEqual(config.chatgpt_model, "gpt-4o-mini")

    def test_chatgpt_model_update(self) -> None:
        config = UserConfig(".")
        config.update(section="translation", key="chatgpt_model", value="gpt-4o")
        config = UserConfig(".")
        self.assertEqual(config.chatgpt_model, "gpt-4o")

    def test_ollama_defaults(self) -> None:
        config = UserConfig(".")
        self.assertEqual(config.ollama_url, "http://localhost:11434")
        self.assertEqual(config.ollama_model, "llama3")

    def test_ollama_update(self) -> None:
        config = UserConfig(".")
        config.update(section="translation", key="ollama_url", value="http://192.168.1.10:11434")
        config.update(section="translation", key="ollama_model", value="mistral")
        config = UserConfig(".")
        self.assertEqual(config.ollama_url, "http://192.168.1.10:11434")
        self.assertEqual(config.ollama_model, "mistral")

    def test_libretranslate_default(self) -> None:
        config = UserConfig(".")
        self.assertEqual(config.libretranslate_url, "https://libretranslate.com")

    def test_libretranslate_update(self) -> None:
        config = UserConfig(".")
        config.update(section="translation", key="libretranslate_url", value="http://localhost:5000")
        config = UserConfig(".")
        self.assertEqual(config.libretranslate_url, "http://localhost:5000")

    def test_game_directory_property(self) -> None:
        config = UserConfig(".")
        config.update(section="config", key="installdirectory", value="D:/Games/DQX")
        config = UserConfig(".")
        self.assertEqual(config.game_directory, "D:/Games/DQX")

    def test_game_directory_default(self) -> None:
        config = UserConfig(".")
        self.assertEqual(config.game_directory, "C:/Program Files (x86)/SquareEnix/DRAGON QUEST X")

    def test_migration_from_old_deepl_flags(self) -> None:
        """Old boolean flags in user_settings.ini should migrate to translate_service."""
        import configparser

        # Write an old-format INI manually
        cfg = configparser.ConfigParser()
        cfg["translation"] = {
            "enabledeepltranslate": "True",
            "deepltranslatekey": "migrated_key",
            "enablegoogletranslate": "False",
            "googletranslatekey": "",
            "enablegoogletranslatefree": "False",
        }
        cfg["config"] = {"installdirectory": "C:/Program Files (x86)/SquareEnix/DRAGON QUEST X"}
        with open("user_settings.ini", "w") as f:
            cfg.write(f)

        config = UserConfig(".")
        self.assertEqual(config.translate_service, "deepl")
        self.assertEqual(config.translate_key, "migrated_key")

    def test_migration_from_old_google_flags(self) -> None:
        import configparser

        cfg = configparser.ConfigParser()
        cfg["translation"] = {
            "enabledeepltranslate": "False",
            "deepltranslatekey": "",
            "enablegoogletranslate": "True",
            "googletranslatekey": "gkey",
            "enablegoogletranslatefree": "False",
        }
        cfg["config"] = {"installdirectory": "C:/Program Files (x86)/SquareEnix/DRAGON QUEST X"}
        with open("user_settings.ini", "w") as f:
            cfg.write(f)

        config = UserConfig(".")
        self.assertEqual(config.translate_service, "google")
        self.assertEqual(config.translate_key, "gkey")

    def test_migration_from_old_googlefree_flag(self) -> None:
        import configparser

        cfg = configparser.ConfigParser()
        cfg["translation"] = {
            "enabledeepltranslate": "False",
            "deepltranslatekey": "",
            "enablegoogletranslate": "False",
            "googletranslatekey": "",
            "enablegoogletranslatefree": "True",
        }
        cfg["config"] = {"installdirectory": "C:/Program Files (x86)/SquareEnix/DRAGON QUEST X"}
        with open("user_settings.ini", "w") as f:
            cfg.write(f)

        config = UserConfig(".")
        self.assertEqual(config.translate_service, "googlefree")

    def test_config_auto_cleanup(self) -> None:
        config = UserConfig(".")
        config.config.set("translation", "unknownkey", "value")
        with open(config.file, "w") as f:
            config.config.write(f)
        config = UserConfig(".")
        self.assertFalse(config.config.has_option("translation", "unknownkey"))

    def test_config_auto_add_missing_keys(self) -> None:
        config = UserConfig(".")
        config.config.remove_option("translation", "translate_service")
        with open(config.file, "w") as f:
            config.config.write(f)
        config = UserConfig(".")
        self.assertTrue(config.config.has_option("translation", "translate_service"))

    def test_translation_section_property(self) -> None:
        config = UserConfig(".")
        section = config.translation_section
        self.assertIsNotNone(section)
        self.assertIn("translate_service", section)
        self.assertIn("translate_key", section)

    def test_config_section_property(self) -> None:
        config = UserConfig(".")
        section = config.config_section
        self.assertIsNotNone(section)
        self.assertIn("installdirectory", section)

    def test_target_language_is_normalized(self) -> None:
        config = UserConfig(".")
        config.update(section="translation", key="target_language", value="pt_br")
        config.update(section="translation", key="target_language_name", value="Brazilian Portuguese")
        config = UserConfig(".")
        self.assertEqual(config.target_language, "pt-BR")
        self.assertEqual(config.target_language_name, "Brazilian Portuguese")
        self.assertTrue(config.active_language.ascii_output)

    def test_process_language_overrides_do_not_modify_saved_config(self) -> None:
        config = UserConfig(".")
        config.update(section="translation", key="target_language", value="pt-BR")
        config.update(section="translation", key="target_language_name", value="Brazilian Portuguese")

        with unittest.mock.patch.dict(
            os.environ,
            {
                "DQXCLARITY_TARGET_LANGUAGE_OVERRIDE": "ja",
                "DQXCLARITY_SOURCE_LANGUAGE_OVERRIDE": "auto",
            },
        ):
            overridden = UserConfig(".")
            self.assertEqual(overridden.target_language, "ja")
            self.assertEqual(overridden.target_language_name, "Japanese")
            self.assertEqual(overridden.source_language, "auto")

        restored = UserConfig(".")
        self.assertEqual(restored.target_language, "pt-BR")


if __name__ == "__main__":
    unittest.main()
