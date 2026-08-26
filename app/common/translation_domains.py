"""Translation-domain identifiers and measured game-layout constraints."""

import textwrap
from dataclasses import dataclass


SUPPORTED_TRANSLATION_DOMAINS = frozenset(
    {
        "dialog",
        "fixed_dialog_template",
        "bad_strings",
        "corner_text",
        "quests",
        "story_so_far",
        "story_so_far_template",
        "walkthrough",
        "m00_strings",
        "glossary",
    }
)


@dataclass(frozen=True)
class ProseLayout:
    """Line constraints observed in the complete upstream English pack."""

    wrap_width: int
    max_lines: int


PROSE_LAYOUTS = {
    "walkthrough": ProseLayout(wrap_width=31, max_lines=3),
    "story_so_far": ProseLayout(wrap_width=39, max_lines=8),
    # The quest detail panel reaches its reward divider after six rendered
    # lines. More lines visibly escape into the reward section.
    "quests": ProseLayout(wrap_width=45, max_lines=6),
}


def fit_prose_layout(text: str, layout: ProseLayout) -> str:
    """Reflow cached prose to the measured box without splitting game names."""

    flattened = " ".join(line.strip() for line in text.splitlines() if line.strip())
    return textwrap.fill(
        flattened,
        width=layout.wrap_width,
        max_lines=layout.max_lines,
        replace_whitespace=True,
        break_long_words=False,
        break_on_hyphens=False,
    )
