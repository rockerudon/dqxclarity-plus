"""Protect official English game terms while translating surrounding prose."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping


_END = ""
_TAG_RE = re.compile(r"(<[^>]+>)")


def _is_ascii_word_character(character: str) -> bool:
    return character.isascii() and (character.isalnum() or character == "_")


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
                    if not ascii_word_boundaries or cursor == len(text) or not _is_ascii_word_character(text[cursor]):
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

        segments = self._visible_segments(text)
        for index in range(0, len(segments), 2):
            segments[index] = self._source_terms.replace(
                segments[index],
                lambda english: english,
                ascii_word_boundaries=False,
            )

        protected: dict[str, str] = {}

        def marker_for(english: str) -> str:
            marker = f"<&dqxc_{len(protected):04x}>"
            protected[marker] = english
            return marker

        for index in range(0, len(segments), 2):
            segments[index] = self._english_terms.replace(
                segments[index],
                marker_for,
                ascii_word_boundaries=True,
            )
        return "".join(segments), protected

    @staticmethod
    def restore(text: str, protected: Mapping[str, str]) -> str | None:
        """Restore markers, rejecting provider output that lost or duplicated one."""

        for marker in protected:
            if text.count(marker) != 1:
                return None
        for marker, english in protected.items():
            text = text.replace(marker, english)
        return text
