import html
import importlib  # Required for lazy loading modules
import pykakasi
import re
import regex
import textwrap
import unicodedata
from common.canonical_terms import CanonicalTermProtector
from common.config import UserConfig
from common.db_ops import (  # Note: translators now imported dynamically via _get_translator_instance helper
    generate_canonical_glossary,
    generate_glossary_dict,
    generate_m00_dict,
    init_db,
)
from common.language import is_suspicious_translation
from functools import cache
from loguru import logger as log


# module constants to prevent re-initialization each run.
_INVALID_CHARS = frozenset(["[", "]", "(", ")", "\\", "/", "*", "_", "+", "?", "$", "^", '"'])
_HIRAGANA_CODEPOINTS = frozenset(list(range(12353, 12430)) + [12431] + list(range(12434, 12436)))
_KATAKANA_CODEPOINTS = frozenset(
    list(range(12449, 12526)) + [12527] + list(range(12530, 12533)) + list(range(12539, 12541)) + [65374]
)
_VALID_CODEPOINTS = _HIRAGANA_CODEPOINTS | _KATAKANA_CODEPOINTS
_JP_REGEX = regex.compile(r"\p{Script=Hiragana}|\p{Script=Katakana}|\p{Script=Han}")

_KKS = pykakasi.kakasi()


@cache
def _shared_canonical_protector() -> CanonicalTermProtector:
    """Build the sizeable canonical-name tries once for all hook translators."""

    return CanonicalTermProtector(generate_canonical_glossary())


class Translator:
    _instance_cache = {}  # Class-level cache for translation instances
    _SERVICE_API = {
        "deepl": (
            "common.translators.deepl",
            "DeepLTranslate",
        ),  # Moved APIs into a dictionary for readability and ease of maintenance
        "google": ("common.translators.googletranslate", "GoogleTranslate"),
        "googlefree": ("common.translators.googletranslatefree", "GoogleTranslateFree"),
        "googletranslatepa": ("common.translators.googletranslatepa", "GoogleTranslatePa"),
        "chatgpt": ("common.translators.chatgpt", "ChatGPTTranslate"),
        "ollama": ("common.translators.ollama", "OllamaTranslate"),
        "yandex": ("common.translators.yandex", "YandexTranslate"),
        "libretranslate": ("common.translators.libretranslate", "LibreTranslate"),
    }

    def __init__(self):
        user_settings = UserConfig()
        self.service = user_settings.translate_service
        self.api_key = user_settings.translate_key
        self.language = user_settings.active_language
        self.source_language = user_settings.source_language
        # Glossaries are isolated by target language so one target's terms never
        # leak into another provider request.
        self.glossary = generate_glossary_dict(language_code=self.language.code)
        self._canonical_protector = _shared_canonical_protector()

    def __glossify(self, text):
        for source_text, translated_text in self.glossary.items():
            # use leading and trailing spaces in case two words are replaced back to back.
            text = text.replace(source_text, f" {translated_text} ")

        # if two strings are replaced back to back, they will have a double space.
        text = text.replace("  ", " ")
        text = text.lstrip()

        return text

    def __swap_placeholder_tags(self, text: str, swap_back=False) -> str:
        if not swap_back:
            text = text.replace("<pc_hiryu>", "<&13_aaaaaaa>")
            text = text.replace("<cs_pchero_hiryu>", "<&13_aaaaaab>")
            text = text.replace("<cs_pchero_race>", "<&8_aaa>")
            text = text.replace("<cs_pchero>", "<&13_aaaaaac>")
            text = text.replace("<kyodai_rel1>", "<&7_aa>")
            text = text.replace("<kyodai_rel2>", "<&7_ab>")
            text = text.replace("<kyodai_rel3>", "<&7_ac>")
            text = text.replace("<pc_hometown>", "<&8_aab>")
            text = text.replace("<pc_race>", "<&8_aac>")
            text = text.replace("<%sM_real_race>", "<&8_aad>")
            text = text.replace("<pc_rel1>", "<&7_ad>")
            text = text.replace("<pc_rel2>", "<&7_ae>")
            text = text.replace("<pc_rel3>", "<&7_af>")
            text = text.replace("<kyodai>", "<&13_aaaaaad>")
            text = text.replace("<pc>", "<&13_aaaaaae>")
            text = text.replace("<client_pcname>", "<&13_aaaaaaf>")
            text = text.replace("<heart>", "<&2a>")
            text = text.replace("<diamond>", "<&2b>")
            text = text.replace("<spade>", "<&2c>")
            text = text.replace("<clover>", "<&2d>")
            text = text.replace("<r_triangle>", "<&2e>")
            text = text.replace("<l_triangle>", "<&2f>")
            text = text.replace("<half_star>", "<&2g>")
            text = text.replace("<null_star>", "<&2h>")
            text = text.replace("<npc>", "<&13_aaaaaag>")
            text = text.replace("<pc_syokugyo>", "<&13_aaaaaah>")
            text = text.replace("<pc_original>", "<&13_aaaaaai>")
            text = text.replace("<log_pc>", "<&13_aaaaaaj>")
            text = text.replace("<%sM_NAME>", "<&13_aaaaaak>")
            text = text.replace("<%sM_BEFORE_NAME>", "<&13_aaaaaal>")
            text = text.replace("<%sM_OWNER_OTHER>", "<&13_aaaaaam>")
            text = text.replace("<%sM_OWNER>", "<&13_aaaaaan>")
            text = text.replace("<%sM_SAMA>", "<&6_a>")
            text = text.replace("<1st_title>", "<&20_aaaaaaaaaaaaaa>")
            text = text.replace("<2nd_title>", "<&20_aaaaaaaaaaaaab>")
            text = text.replace("<3rd_title>", "<&20_aaaaaaaaaaaaac>")
            text = text.replace("<4th_title>", "<&20_aaaaaaaaaaaaad>")
            text = text.replace("<5th_title>", "<&20_aaaaaaaaaaaaae>")
            text = text.replace("<6th_title>", "<&20_aaaaaaaaaaaaaf>")
            text = text.replace("<7th_title>", "<&20_aaaaaaaaaaaaag>")
        else:
            text = text.replace("<&13_aaaaaaaa>", "<pc_hiryu>")
            text = text.replace("<&13_aaaaaaa>", "<pc_hiryu>")
            text = text.replace("<&13_aaaaaa>", "<pc_hiryu>")
            text = text.replace("<&13_aaaaaaab>", "<cs_pchero_hiryu>")
            text = text.replace("<&13_aaaaaab>", "<cs_pchero_hiryu>")
            text = text.replace("<&13_aaaaab>", "<cs_pchero_hiryu>")
            text = text.replace("<&8_aaa>", "<cs_pchero_race>")
            text = text.replace("<&13_aaaaaaac>", "<cs_pchero>")
            text = text.replace("<&13_aaaaaac>", "<cs_pchero>")
            text = text.replace("<&13_aaaaac>", "<cs_pchero>")
            text = text.replace("<&7_aa>", "<kyodai_rel1>")
            text = text.replace("<&7_ab>", "<kyodai_rel2>")
            text = text.replace("<&7_ac>", "<kyodai_rel3>")
            text = text.replace("<&8_aab>", "<pc_hometown>")
            text = text.replace("<&8_aac>", "<pc_race>")
            text = text.replace("<&8_aad>", "<%sM_real_race>")
            text = text.replace("<&7_ad>", "<pc_rel1>")
            text = text.replace("<&7_ae>", "<pc_rel2>")
            text = text.replace("<&7_af>", "<pc_rel3>")
            text = text.replace("<&13_aaaaaaad>", "<kyodai>")
            text = text.replace("<&13_aaaaaad>", "<kyodai>")
            text = text.replace("<&13_aaaaad>", "<kyodai>")
            text = text.replace("<&13_aaaaaaae>", "<pc>")
            text = text.replace("<&13_aaaaaae>", "<pc>")
            text = text.replace("<&13_aaaaae>", "<pc>")
            text = text.replace("<&13_aaaaaaaf>", "<client_pcname>")
            text = text.replace("<&13_aaaaaaf>", "<client_pcname>")
            text = text.replace("<&13_aaaaaf>", "<client_pcname>")
            text = text.replace("<&2a>", "<heart>")
            text = text.replace("<&2b>", "<diamond>")
            text = text.replace("<&2c>", "<spade>")
            text = text.replace("<&2d>", "<clover>")
            text = text.replace("<&2e>", "<r_triangle>")
            text = text.replace("<&2f>", "<l_triangle>")
            text = text.replace("<&2g>", "<half_star>")
            text = text.replace("<&2h>", "<null_star>")
            text = text.replace("<&13_aaaaaaag>", "<npc>")
            text = text.replace("<&13_aaaaaag>", "<npc>")
            text = text.replace("<&13_aaaaag>", "<npc>")
            text = text.replace("<&13_aaaaaaah>", "<pc_syokugyo>")
            text = text.replace("<&13_aaaaaah>", "<pc_syokugyo>")
            text = text.replace("<&13_aaaaah>", "<pc_syokugyo>")
            text = text.replace("<&13_aaaaaaai>", "<pc_original>")
            text = text.replace("<&13_aaaaaai>", "<pc_original>")
            text = text.replace("<&13_aaaaai>", "<pc_original>")
            text = text.replace("<&13_aaaaaaaj>", "<log_pc>")
            text = text.replace("<&13_aaaaaaj>", "<log_pc>")
            text = text.replace("<&13_aaaaaj>", "<log_pc>")
            text = text.replace("<&13_aaaaaaak>", "<%sM_NAME>")
            text = text.replace("<&13_aaaaaak>", "<%sM_NAME>")
            text = text.replace("<&13_aaaaak>", "<%sM_NAME>")
            text = text.replace("<&13_aaaaaaal>", "<%sM_BEFORE_NAME>")
            text = text.replace("<&13_aaaaaal>", "<%sM_BEFORE_NAME>")
            text = text.replace("<&13_aaaaal>", "<%sM_BEFORE_NAME>")
            text = text.replace("<&13_aaaaaaam>", "<%sM_OWNER_OTHER>")
            text = text.replace("<&13_aaaaaam>", "<%sM_OWNER_OTHER>")
            text = text.replace("<&13_aaaaam>", "<%sM_OWNER_OTHER>")
            text = text.replace("<&13_aaaaaaan>", "<%sM_OWNER>")
            text = text.replace("<&13_aaaaaan>", "<%sM_OWNER>")
            text = text.replace("<&13_aaaaan>", "<%sM_OWNER>")
            text = text.replace("<&6_a>", "<%sM_SAMA>")
            text = text.replace("<&20_aaaaaaaaaaaaaaa>", "<1st_title>")
            text = text.replace("<&20_aaaaaaaaaaaaaa>", "<1st_title>")
            text = text.replace("<&20_aaaaaaaaaaaaa>", "<1st_title>")
            text = text.replace("<&20_aaaaaaaaaaaaaab>", "<2nd_title>")
            text = text.replace("<&20_aaaaaaaaaaaaab>", "<2nd_title>")
            text = text.replace("<&20_aaaaaaaaaaaab>", "<2nd_title>")
            text = text.replace("<&20_aaaaaaaaaaaaaac>", "<3rd_title>")
            text = text.replace("<&20_aaaaaaaaaaaaac>", "<3rd_title>")
            text = text.replace("<&20_aaaaaaaaaaaac>", "<3rd_title>")
            text = text.replace("<&20_aaaaaaaaaaaaaad>", "<4th_title>")
            text = text.replace("<&20_aaaaaaaaaaaaad>", "<4th_title>")
            text = text.replace("<&20_aaaaaaaaaaaad>", "<4th_title>")
            text = text.replace("<&20_aaaaaaaaaaaaaae>", "<5th_title>")
            text = text.replace("<&20_aaaaaaaaaaaaae>", "<5th_title>")
            text = text.replace("<&20_aaaaaaaaaaaae>", "<5th_title>")
            text = text.replace("<&20_aaaaaaaaaaaaaaf>", "<6th_title>")
            text = text.replace("<&20_aaaaaaaaaaaaaf>", "<6th_title>")
            text = text.replace("<&20_aaaaaaaaaaaaf>", "<6th_title>")
            text = text.replace("<&20_aaaaaaaaaaaaaag>", "<7th_title>")
            text = text.replace("<&20_aaaaaaaaaaaaag>", "<7th_title>")
            text = text.replace("<&20_aaaaaaaaaaaag>", "<7th_title>")

        return text

    def __wrap_text(self, text: str, width: int, max_lines=None) -> str:
        """Wrap text to n characters per line."""
        return textwrap.fill(text, width=width, max_lines=max_lines, replace_whitespace=False)

    def __add_line_endings(self, text: str) -> str:
        """Adds <br> flags every 3 lines to a string. Used to break up the text
        in a dialog window.

        :param text: Text to add the <br> tags to.
        :returns: A new string with the text broken up by <br> tags.
        """
        count_list = [i for i in range(3, 500, 4)]  # 500 is arbitrary, but we should never hit this.
        split_text = text.split("\n")
        try:
            for i in count_list:
                _ = split_text[i]
                split_text.insert(i, "<br>")
        except IndexError:
            split_text = [x for x in split_text if x]
            output = "\n".join(split_text)
            return output

    def __api_translate(self, text: list) -> list:
        """Translates a list of strings using the cached translation service."""
        # Consolidated if-elif list to class-level _SERVICE_API Dict
        for i, phrase in enumerate(text):
            text[i] = self.__glossify(phrase)

        try:
            translator = self._get_translator_instance()  # Retrieve instance via the helper method
            translated = translator.translate(text)
            if not isinstance(translated, list):
                log.error("Translation provider returned a non-list response; ignoring it.")
                return []
            for index, item in enumerate(translated):
                # Google API and some HTML-backed providers entity-escape game
                # placeholders even when they otherwise preserve them exactly.
                item = html.unescape(str(item))
                translated[index] = item
                if is_suspicious_translation(item):
                    source_preview = repr(text[index][:160]) if index < len(text) else "<unknown>"
                    result_preview = repr(str(item)[:160])
                    log.error(
                        f"Translation provider returned an invalid item at index {index}; "
                        f"source={source_preview}, result={result_preview}"
                    )
                    return []
            return translated
        except Exception as e:
            log.exception(f"Translation failed for service '{self.service}': {e}")
            return []

    def _get_translator_instance(self):
        """Retrieve or initialize the translation instance from the class-level cache."""
        # New helper function for instance caching

        if self.service not in Translator._SERVICE_API:  # 1. Check if service is supported
            log.error(f"Service '{self.service}' is not supported.")
            raise ValueError(f"Unsupported translation service: {self.service}")

        cache_key = (self.service, self.language.code, self.source_language)
        if cache_key in Translator._instance_cache:  # 2. Return from cache if already initialized
            return Translator._instance_cache[cache_key]

        try:
            module_path, class_name = Translator._SERVICE_API[self.service]  # 3. Lazy import and initialize the class
            log.info(f"Initializing new {self.service} translator for {self.language.code}...")

            module = importlib.import_module(module_path)
            translator_class = getattr(module, class_name)

            instance = translator_class(self.api_key) if self.api_key else translator_class()

            Translator._instance_cache[cache_key] = instance  # Store in cache and return
            return instance

        except Exception as e:
            log.error(f"Failed to initialize {self.service} from {module_path}: {e}")
            raise

    def translate_outgoing_chat(self, text: str) -> str | None:
        """Translate user-authored chat as one raw phrase.

        The helper process selects Japanese as its target. This deliberately
        bypasses inbound-only Japanese detection, canonical-name protection,
        dialogue wrapping, and game-tag rewriting.
        """

        source = (text or "").strip()
        if not source:
            return None
        translated = self.__api_translate([source])
        if len(translated) != 1 or not translated[0].strip():
            return None
        return translated[0].strip()

    def translate(self, text: str, wrap_width: int, max_lines=None, add_brs=True, translate_choices=True):
        """Sanitizes different tags and symbols, then translates the string.

        :param text: String to be translated.
        :param wrap_width: How many characters the returning string
                should contain per line.
        :param max_lines: The maximum amount of lines to return. Extra
                lines are truncated with "..."
        :param add_brs: Whether to inject "<br>" every three lines to
                break up text. Used for dialog mainly.
        :param translate_choices: Whether selectable option lines may be sent
                to the provider. Callers handling mixed control/prose payloads
                may disable this to preserve the pack's UI controls.
        :returns: The translated string, or None if translation was
                skipped (majority English) or failed. Callers should
                treat a falsy return as "do not cache this result" and
                fall back to displaying the original text.
        """
        log.debug(f"[Original]\n{text}")

        if not should_translate_text(text):
            log.debug("[Skip] Text is outside the active runtime translation layer.")
            return None

        # manage our own line endings later
        output = text.replace("<br>", "　")

        # remove any tag alignments
        alignments = ["<center>", "<right>", "<left>"]
        for alignment in alignments:
            output = output.replace(alignment, "")

        # trim multiple ellipses to a single one
        ellipses = [
            "…………………………………………",
            "………………………………………",
            "……………………………………",
            "…………………………………",
            "………………………………",
            "……………………………",
            "…………………………",
            "………………………",
            "……………………",
            "…………………",
            "………………",
            "……………",
            "…………",
            "………",
            "……",
        ]
        for ellipse in ellipses:
            output = output.replace(ellipse, "…")

        # remove any other oddities that don't look great in english
        oddities = ["「", "～", "♪"]
        for oddity in oddities:
            output = output.replace(oddity, "")

        # "。" is a Japanese period, but we're seeing unwanted behavior when mixing other characters with it
        output = output.replace("…。", ".")
        output = output.replace("。", ".")

        # remove the full width space that starts on a new line
        output = output.replace("\n　", "\n")

        # removes all of the honorifics added at the end of the tags
        name_tags = ["<pc>", "<cs_pchero>", "<kyodai>"]
        honorifics = ["さま", "君", "どの", "ちゃん", "くん", "様", "さーん", "殿", "さん"]
        for tag in name_tags:
            for honorific in honorifics:
                output = output.replace(f"{tag}{honorific}", tag)

        # protect color tags from translator mangling by adding & prefix.
        # the defensive restore below handles the case where the translator strips the leading <.
        output = re.sub(r"<color_(\w+)>", r"<&color_\1>", output)

        # replace all variable name tags that expand to other text
        output = self.__swap_placeholder_tags(output)

        # Replace Japanese game names with their official English equivalents,
        # then shield those names while the provider translates the surrounding
        # sentence. This keeps terms searchable against the English wiki without
        # sacrificing the grammatical context sent to machine translation.
        canonical_protector = getattr(self, "_canonical_protector", None)
        protected_terms: dict[str, str] = {}
        if canonical_protector:
            output, protected_terms = canonical_protector.prepare(output)

        # pass string through our glossary to replace any common words
        output = self.__glossify(output)

        # re-assign this string. this is now our "pristine" string we'll be using later.
        pristine_str = output

        # get the text to translate, splitting on all tags that don't start with % or &
        tag_re = re.compile("(<[^%&]*?>)")
        # Selection controls are not ordinary prose.  Their option payload
        # must remain line-oriented and immediately follow the control tag or
        # the game renders it in the normal dialogue box.
        select_start_re = re.compile(r"<select(?!_end\b)[^>]*>", re.IGNORECASE)
        str_split = [x for x in re.split(tag_re, output) if x]

        str_attrs = []

        # iterate over each string, handling based on condition
        for split_index, string in enumerate(str_split):
            if not re.match(tag_re, string):
                # sole new lines need to stay where they are.
                if string == "\n":
                    continue

                # capture position of the string and replace with placeholder text
                attr_index = len(str_attrs)
                pristine_str = pristine_str.replace(string, f"<replace_me_index_{attr_index}>", 1)

                # A selection payload normally starts with a newline, but
                # accepting a missing one lets us repair old cached entries.
                is_list = split_index > 0 and bool(select_start_re.fullmatch(str_split[split_index - 1]))
                if is_list:
                    str_attrs.append(
                        {
                            "text": string,
                            "is_list": True,
                            "translate": translate_choices,
                            # The game parser requires the option payload and
                            # closing marker to be on their own lines.  Repair
                            # packs that omitted either boundary.
                            "prepend_newline": True,
                            "append_newline": True,
                        }
                    )
                    continue

                # capture how the newline was originally placed
                append_newline = False
                if string.endswith("\n"):
                    append_newline = True

                prepend_newline = False
                if string.startswith("\n"):
                    prepend_newline = True

                # Pack line wrapping is presentation, not word separation.
                # Removing newlines outright produced requests such as
                # ``placewhere`` and ``aretraveling``. Collapse them to one
                # space while leaving selectable list payloads untouched.
                string = re.sub(r"\s*\n\s*", " ", string).strip()

                str_attrs.append(
                    {
                        "text": string,
                        "is_list": False,
                        "translate": True,
                        "prepend_newline": prepend_newline,
                        "append_newline": append_newline,
                    }
                )

        # translate our list of strings
        to_translate = []
        for attr in str_attrs:
            attr["translation_start"] = len(to_translate)
            if not attr["translate"]:
                attr["translation_count"] = 0
            elif not attr["is_list"]:
                to_translate.append(attr["text"])
                attr["translation_count"] = 1
            else:
                lines = [line for line in attr["text"].splitlines() if line]
                for line in lines:
                    if line:
                        to_translate.append(line)
                attr["translation_count"] = len(lines)

        log.debug(f"[Post-glossary]\n{to_translate}")
        translated_list = self.__api_translate(text=to_translate) if to_translate else []
        log.debug(f"[Post-translated]\n{translated_list}")

        if len(translated_list) != len(to_translate):
            log.error(
                f"{self.service} translation failed: expected {len(to_translate)} "
                f"items, received {len(translated_list)}."
            )
            return ""

        # Update each attribute from its own slice.  The previous implementation
        # used the attribute index as a translation index, so a list following
        # prose consumed the wrong entries and lost its leading newline.
        for attr in str_attrs:
            if not attr["translate"]:
                continue
            start = attr["translation_start"]
            end = start + attr["translation_count"]
            translated_items = translated_list[start:end]
            if attr["is_list"]:
                joined_list = "\n".join(translated_items)
                if attr["prepend_newline"]:
                    joined_list = "\n" + joined_list
                if attr["append_newline"]:
                    joined_list += "\n"
                attr["text"] = joined_list
            else:
                attr["text"] = translated_items[0]

        # Validate and restore every canonical marker before wrapping. Markers
        # are deliberately short; wrapping first could make a restored long
        # location or item name overflow the game's dialogue box.
        if canonical_protector and protected_terms:
            separator = "\0"
            restored_attrs = canonical_protector.restore(
                separator.join(attr["text"] for attr in str_attrs),
                protected_terms,
            )
            if restored_attrs is None:
                log.error("Translation provider changed a protected canonical-term marker; using the source text.")
                return ""
            for attr, restored_text in zip(str_attrs, restored_attrs.split(separator), strict=True):
                attr["text"] = restored_text

        # search for any weird space usage and remove it.
        # this comes from deepl and are all scenarios that have been seen with
        # translations coming back from machine translation.
        for count, _ in enumerate(str_attrs):
            if not str_attrs[count]["translate"]:
                pristine_str = pristine_str.replace(
                    f"<replace_me_index_{count}>",
                    str_attrs[count]["text"],
                    1,
                )
                continue
            str_text = str_attrs[count]["text"]
            str_text = str_text.replace("　 ", " ")
            str_text = str_text.replace(" 　", " ")
            str_text = str_text.replace("　", " ")
            str_text = str_text.replace("  ", " ")
            str_text = str_text.replace("..................", "...")
            str_text = str_text.replace("...............", "...")
            str_text = str_text.replace("............", "...")
            str_text = str_text.replace(".........", "...")
            str_text = str_text.replace("......", "...")
            str_text = str_text.replace("....", "...")

            # game doesn't render curly apostrophes, replace with straight apostrophes.
            str_text = str_text.replace("’", "'")

            # game doesn't render em-dash. use two ASCII hyphens instead.
            updated_str = str_text.replace("—", "--")
            if str_attrs[count]["is_list"]:
                # Selection lists contain multiple entries and must retain their
                # original line boundaries after provider translation.
                updated_str = self.__swap_placeholder_tags(updated_str, swap_back=True)
                updated_str = re.sub(r"<&color_(\w+)>", r"<color_\1>", updated_str)
                updated_str = re.sub(r"(?<![<])&color_(\w+)>", r"<color_\1>", updated_str)

                # deepl occasionally indents our list lines.. even though they weren't originally indented
                updated_str = updated_str.replace("\n ", "\n")
                updated_str = updated_str.replace("\n　", "\n")
                pristine_str = pristine_str.replace(f"<replace_me_index_{count}>", updated_str)

            else:
                # wrap the text and inject <br>'s to break the text up
                updated_str = self.__wrap_text(updated_str, width=wrap_width, max_lines=max_lines)
                updated_str = self.__swap_placeholder_tags(updated_str, swap_back=True)
                updated_str = re.sub(r"<&color_(\w+)>", r"<color_\1>", updated_str)
                updated_str = re.sub(r"(?<![<])&color_(\w+)>", r"<color_\1>", updated_str)

                if add_brs:
                    updated_str = self.__add_line_endings(updated_str)
                if str_attrs[count]["prepend_newline"]:
                    updated_str = "\n" + updated_str
                if str_attrs[count]["append_newline"]:
                    updated_str += "\n"

                # if we see a voice line tag (<voice_nw>), a <br> must exist at the end of the string no matter what.
                # this is required to make the dialog pause while the voice line continues.
                voice_re = re.compile("<voice.*>")

                # unfortunately, this rule does not apply if it belongs to a voiced cutscene in
                # Asfeld. For some reason, these dialog boxes are handled differently, but all Asfeld
                # cutscenes have a specific voice tag of <voice_nw IEV_GS####_# ##>. If we see one, don't include a <br>
                # tag in that string at all.

                if re.search(voice_re, pristine_str) and "IEV_GS" not in pristine_str:
                    tag_list = re.findall(tag_re, pristine_str)

                    # get the current index from our pristine_str
                    cur_index = tag_list.index(f"<replace_me_index_{count}>")

                    # don't add a <br> to the very last line. subtract 1 as length doesn't start at 0 like index does.
                    if len(tag_list) - 1 != cur_index:
                        # get the index of the previous string to read
                        lookback_index = cur_index - 1

                        # make sure we get a valid number before checking the index
                        if lookback_index > -1 and re.match(voice_re, tag_list[lookback_index]):  # noqa: SIM102
                            # don't add a <br> if it already exists
                            if not updated_str.endswith("<br>"):
                                updated_str += "<br>\n"

                pristine_str = pristine_str.replace(f"<replace_me_index_{count}>", updated_str)

            count += 1

        log.debug(f"[Final]\n{pristine_str}")
        return pristine_str


def clean_up_and_return_items(text: str) -> str:
    """Cleans up unnecessary text from item strings and searches for the name
    in items.json.

    Used specifically for the quest window.
    """
    quest_rewards = generate_m00_dict(files="'custom_quest_rewards', 'items', 'key_items'")

    line_count = text.count("\n")
    sanitized = re.sub("男は ", "", text)  # remove boy reference from start of string
    sanitized = re.sub("女は ", "", sanitized)  # remove girl reference from start of string
    sanitized = re.sub("男は　", "", sanitized)  # remove boy reference from start of string (fullwidth space)
    sanitized = re.sub("女は　", "", sanitized)  # remove girl reference from start of string (fullwidth space)
    final_string = ""
    for item in sanitized.split("\n"):
        quantity = ""
        no_bullet = re.sub(r"(^\・)", "", item)
        points = no_bullet[6:18]
        if no_bullet.endswith("こ"):
            quantity = "(" + unicodedata.normalize("NFKC", no_bullet[-3:-1]) + ")"
            quantity = re.sub(" ", "", quantity)
        if no_bullet.endswith("他"):
            bad_strings = ["必殺技を覚える", "入れられるよう"]
            quantity = "" if any(string in no_bullet for string in bad_strings) else "(1)"
        no_bullet = re.sub("(　　.*)", "", no_bullet)
        if no_bullet in quest_rewards:
            value = quest_rewards.get(no_bullet)
            if value:
                value_length = len(value)
                quant_length = len(quantity)
                byte_count = len(value.encode("utf-8"))
                num_spaces = 31 - value_length - quant_length - ((byte_count - value_length) // 2)
                if "・" in item:
                    if line_count == 0:
                        return "・" + value + (" " * num_spaces) + quantity
                    else:
                        final_string += "・" + value + (" " * num_spaces) + quantity + "\n"
                else:
                    if line_count == 0:
                        return value + (" " * num_spaces) + quantity
                    else:
                        final_string += value + (" " * num_spaces) + quantity + "\n"
        else:
            if line_count == 0:
                if "討伐ポイント" in item:
                    return "・" + "Experience Points" + points
                else:
                    return text
            else:
                final_string += item + "\n"
    return final_string.rstrip()


def is_text_japanese(text: str) -> bool:
    """
    Checks text to see if it contains any Japanese.

    :param text: Text to check against.
    :returns: True if text contains Japanese.
    """
    # remove any tags that use ascii alphabet
    sanitized = re.sub("<.+?>", "", text)

    return bool(_JP_REGEX.search(sanitized))


@cache
def _runtime_translation_policy() -> tuple[str, bool]:
    """Load immutable per-process translation settings once."""

    config = UserConfig()
    return config.target_language, config.api_translation_overlay


def should_translate_text(text: str) -> bool:
    """Return whether a hook-visible prose field should use the API layer.

    Legacy mode accepts Japanese only. The opt-in overlay also accepts Latin
    prose from a language pack, but leaves symbols, numbers and English-to-
    English requests alone. Hooks decide which fields are prose, so static UI
    and canonical names never reach this function.
    """

    if not text or not text.strip():
        return False
    target_language, overlay_enabled = _runtime_translation_policy()
    if is_text_japanese(text):
        return target_language != "ja"
    if not overlay_enabled or target_language == "en":
        return False
    visible = re.sub(r"<[^>]+>", "", text)
    return any(character.isascii() and character.isalpha() for character in visible)


@cache
def transliterate_player_name(word: str) -> str:
    """Uses the pykakasi library to phonetically convert a Japanese word into
    English.

    :param word: Word to convert.
    :returns: Returns up to a 10 character name in English.
    """
    # dqx character names are limited to 6 characters. if we receive something longer
    # than 6 characters, just return the word.
    if len(word) > 6:
        return word

    # check for invalid characters
    if set(word) & _INVALID_CHARS:
        return word

    # validate all characters are hiragana/katakana
    if not all(ord(char) in _VALID_CODEPOINTS for char in word):
        return word

    # use constant kakasi instance for conversion
    result = _KKS.convert(word)
    romaji = "".join([char["hepburn"] for char in result]).title().replace("・", "")

    # a player can name themselves "・". since we replace all instances of this, romaji
    # could be blank. if this is the case, we'll keep the same number of interpunct chars
    # and replace them with periods.
    if not romaji:
        romaji = "." * word.count("・")

    return romaji[0:10]


def get_player_name() -> tuple:
    """Queries the player and sibling name from the database.

    Returns a tuple of (player_name, sibling_name).
    """
    conn, cursor = init_db()

    player_query = "SELECT name FROM player WHERE type = 'player'"
    sibling_query = "SELECT name FROM player WHERE type = 'sibling'"

    results = cursor.execute(player_query)
    player = results.fetchone()[0]

    results = cursor.execute(sibling_query)
    sibling = results.fetchone()[0]

    conn.close()

    return (player, sibling)
