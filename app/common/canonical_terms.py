"""Protect official English game terms while translating surrounding prose."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping


_END = ""
_TAG_RE = re.compile(r"(<[^>]+>)")
_HIRAGANA_TERM_RE = re.compile(r"[\u3040-\u309fー・]+")


def _is_ascii_word_character(character: str) -> bool:
    return character.isascii() and (character.isalnum() or character == "_")


def _is_japanese_word_character(character: str) -> bool:
    return (
        "\u3040" <= character <= "\u30ff"
        or "\u3400" <= character <= "\u4dbf"
        or "\u4e00" <= character <= "\u9fff"
        or "\uff65" <= character <= "\uff9f"
    )


def _safe_source_match(text: str, start: int, end: int) -> bool:
    """Reject hiragana names found in the middle of ordinary words."""

    term = text[start:end]
    if not _HIRAGANA_TERM_RE.fullmatch(term) or start == 0:
        return True
    return not _is_japanese_word_character(text[start - 1])


class _ReplacementTrie:
    """Small longest-match trie used without adding a runtime dependency."""

    def __init__(self, replacements: Mapping[str, str]):
        self._root: dict = {}
        for source, replacement in replacements.items():
            if not source:
                continue
            node = self._root
            for character in source:
                node = node.setdefault(character, {})
            node[_END] = replacement

    def replace(
        self,
        text: str,
        replacement_factory: Callable[[str], str],
        *,
        ascii_word_boundaries: bool,
        match_filter: Callable[[str, int, int], bool] | None = None,
    ) -> str:
        if not self._root or not text:
            return text

        result: list[str] = []
        index = 0
        while index < len(text):
            if ascii_word_boundaries and index and _is_ascii_word_character(text[index - 1]):
                result.append(text[index])
                index += 1
                continue

            node = self._root
            cursor = index
            best_end = -1
            best_replacement: str | None = None
            while cursor < len(text) and text[cursor] in node:
                node = node[text[cursor]]
                cursor += 1
                if _END in node:
                    has_word_boundary = (
                        not ascii_word_boundaries
                        or cursor == len(text)
                        or not _is_ascii_word_character(text[cursor])
                    )
                    if has_word_boundary and (match_filter is None or match_filter(text, index, cursor)):
                        best_end = cursor
                        best_replacement = node[_END]

            if best_replacement is None:
                result.append(text[index])
                index += 1
                continue

            result.append(replacement_factory(best_replacement))
            index = best_end

        return "".join(result)


class CanonicalTermProtector:
    """Canonicalize Japanese names, then shield their official English form.

    The opaque markers deliberately use the same ``<&...>`` shape already
    used by Clarity for player-name placeholders. Providers receive the whole
    sentence for context, while the game term itself cannot be translated.
    """

    def __init__(self, japanese_to_english: Mapping[str, str] | None = None):
        pairs = {
            source: english
            for source, english in (japanese_to_english or {}).items()
            if source and english and source != english
        }
        self._source_terms = _ReplacementTrie(pairs)
        self._english_terms = _ReplacementTrie({english: english for english in set(pairs.values())})

    @property
    def enabled(self) -> bool:
        return bool(self._english_terms._root)

    @staticmethod
    def _visible_segments(text: str) -> list[str]:
        return _TAG_RE.split(text)

    def prepare(self, text: str) -> tuple[str, dict[str, str]]:
        """Return provider-safe text and a marker-to-English restoration map."""

        if not self.enabled or not text:
            return text, {}

        protected: dict[str, str] = {}

        def marker_for(english: str) -> str:
            marker = f"<&dqxc_{len(protected):04x}>"
            protected[marker] = english
            return marker

        segments = self._visible_segments(text)
        # Never expose a Japanese-to-English replacement to the provider.
        # Adjacent Japanese terms and particles have no ASCII word boundary;
        # replacing them with English first could create strings such as
        # ``Port LendorCocolata Beach`` that the English trie could no longer
        # recognize and shield.  Mark the Japanese match directly instead.
        for index in range(0, len(segments), 2):
            segments[index] = self._source_terms.replace(
                segments[index],
                marker_for,
                ascii_word_boundaries=False,
                match_filter=_safe_source_match,
            )

        # Also protect official English names already supplied by a language
        # pack. Japanese replacements above are opaque tags and cannot be
        # matched again by this pass.
        for index in range(0, len(segments), 2):
            segments[index] = self._english_terms.replace(
                segments[index],
                marker_for,
                ascii_word_boundaries=True,
            )
        return "".join(segments), protected

    @staticmethod
    def restore(text: str, protected: Mapping[str, str]) -> str | None:
        """Restore surviving markers and reject only malformed marker residue.

        Translation providers sometimes omit a repeated name or an entire
        location while naturally restructuring a sentence.  A missing marker
        is therefore not corruption and must not discard the whole translated
        block.  A damaged marker is unsafe because it could reach the game as
        visible control text, so any such residue is still rejected.
        """

        for marker, english in protected.items():
            text = text.replace(marker, english)
        if "dqxc_" in text.lower():
            return None
        return text
