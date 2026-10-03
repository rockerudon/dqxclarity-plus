# Multilingual core architecture

## Scope of the first milestone

The runtime now treats a translation language as a canonical BCP 47 code (`en`,
`pt-BR`, `es`, `zh-Hant-TW`) instead of treating the legacy `en` column as the
meaning of “translated.” This milestone does not patch game DAT files and does
not ship a complete Portuguese pack.

## Original architecture diagnosis

- Dynamic dialogue, quest, walkthrough, and story caches read and wrote a single
  `en` column. A non-English target could therefore receive cached English.
- Static names/items/quests and glossaries were also modeled as Japanese-to-English
  dictionaries.
- Translation providers had begun reading `target_language`, but DeepL instructions
  and the final runtime normalization were still globally English/ASCII.
- The launcher already supported version-1 CLPK metadata and active-pack ordering.
  Its pack catalog was a C# list containing only English.
- Frida hooks write directly into game-owned buffers. Only some quest fields have
  capacities that can be inferred from adjacent fixed offsets; most other buffer
  capacities remain unknown.

## Language identity

`common/language.py` and `launcher/Models/LanguageCodes.cs` are the canonical
language boundaries. They validate and normalize BCP 47 codes. The user selects
the runtime API target in the launcher's General tab; it is written to
`user_settings.ini` as `target_language` plus a provider-facing English name,
independently of the active DAT language packs.

`pt-BR` resolves to `Brazilian Portuguese`, so LLM prompts request that variant
explicitly. Provider adapters retain their own target mapping; DeepL maps `pt-BR`
to `PT-BR`.

## Persistence and migration

Legacy tables and all existing `en` data remain in place. The idempotent schema
file `001_multilingual_translations.sql` adds:

- `translation_values(domain, source_text, language_code, translated_text,
  translation_kind, context)`.

Nothing is copied, dropped, or renamed. Existing English rows are read directly
from the upstream tables, avoiding a second copy of the complete pack database.
New English writes continue to update the legacy `en` column, preserving
compatibility with upstream importers and tools. Other languages are written
only to `translation_values`, which also permits region tags such as `pt-BR`
that cannot be clean SQL column names.

Manual rows sort before machine and legacy rows. Dynamic cache reads are strict
to the active language by default. An English fallback must be requested
explicitly by a caller; static manual `m00_strings` allow it, while dynamic
dialogue/quest/walkthrough caches and glossaries do not.

The intended display chain is:

1. the active language pack supplies static UI and canonical names;
2. selected-language manual database rows override matching automatic cache rows;
3. when enabled, the API overlay translates only prose fields exposed by safe
   hooks and stores the result for the selected target language;
4. the pack-provided text remains visible when no safe dynamic result exists.

Before a provider request, short title-like entries from the upstream item,
monster, NPC, quest and story tables are combined with conservatively filtered
place/name entries from the English glossary. Japanese matches are canonicalized
to English and both Japanese-origin and already-English pack terms are replaced
with validated opaque markers. The complete sentence is then translated and the
official English spellings are restored. A missing or duplicated marker rejects
the result instead of caching damaged terminology.

The canonical-terminology revision invalidates obsolete machine-generated prose
once through `translation_metadata`. Manual translations, legacy English pack
rows and static database content are never deleted.

Packaging does not generate synthetic or empty language packs. Pack selection
and API target selection are independent. The launcher verifies the SHA and ZIP
structure of local CLPKs before activation.

## Optional API overlay

`api_translation_overlay` is disabled by default. When enabled, providers use
source-language auto-detection and the prose hooks accept both Japanese and
Latin-source text. Field ownership is explicit: dialogue, walkthrough text,
quest descriptions, story summaries and hook-visible event/corner prose may
use the API; menus, map labels, nameplates, quest titles, item names and rewards
remain owned by the pack.

This makes the complete upstream English pack a useful static foundation while
allowing runtime prose to target Portuguese, Spanish or another supported
language. Disabling the overlay restores legacy Japanese-only API behavior.

The launcher exposes only Latin-script runtime targets that remain readable
after DQX's ASCII safety conversion: English, Brazilian and European Portuguese,
Spanish, French, German, Italian, Dutch, Polish and Turkish. Arabic, Cyrillic,
Chinese and Korean targets are intentionally omitted. Japanese is the source
language rather than a translation target. The lower-level language and cache
model remains BCP 47-compatible so future renderer work or community tooling
does not require another database redesign.

## Unicode storage and game output

Full Unicode is stored in SQLite. `ascii_output_languages = *` enables the safe
game boundary for every non-Japanese target. For `pt-BR`, `você`, `ação`,
`coração`, and `bênção` remain intact in the cache and become `voce`, `acao`,
`coracao`, and `bencao` only immediately before a hook response. Spanish
diacritics and punctuation are handled the same way. Untranslated Japanese inside
a replacement stays native: the client renders its own script, and romanizing it
produces Mandarin readings such as `inishienoHuangZi`. Other non-Latin scripts are
still romanized defensively if a legacy or manually edited
configuration reaches the runtime, but those targets are not offered by the
launcher because the result is generally not readable enough for normal use.

Game tags and placeholders are split out before ASCII transformation. UTF-8
length and truncation helpers count bytes, never characters, and never cut through
an angle-bracket tag.

Every translated hook write now passes through a Frida-side UTF-8 capacity guard.
Quest fields whose adjacent offsets establish capacities use their measured
fixed limits. For dialogue, names, corner text, network text, and the remaining
quest field whose full structure is not known, the guard uses the original
string's byte length as a conservative upper bound; an oversized translation is
rejected and the original text remains visible.

Prose boxes also use the measured line layouts from the complete English pack:
walkthrough `31 x 3`, Story So Far `39 x 8`, and quest descriptions `45 x 6`.
Cached machine text is reflowed on display, so changing a layout does not require
deleting or retranslating the stored Unicode value. Hook-side replacement guards
prevent a game-owned buffer from feeding its translated output back into the API.

Selectable dialogue is translated as one atomic block. The runtime accepts the
result only when parser-control tags remain identical and every selector retains
the original number and order of options; otherwise it displays the English pack
block. If the English pack has no matching block, the same validation permits a
direct Japanese-to-target translation and falls back to Japanese on failure.
Short unmarked option lists use the same structural validation. Network category
`<%sM_text01>` is treated as constrained story/progress prose rather than an
unknown static string.

The anonymous Google provider batches related phrases, caches successful results
and uses a bounded `5 / 15 / 30 / 60` second backoff after consecutive HTTP 429
responses. A successful request resets the backoff. It never switches providers
without the user's selection.

## CLPK and catalog compatibility

CLPK magic, version, byte layout, metadata names, and payload SHA behavior are
unchanged. Pack language metadata is normalized when read or built. The launcher
continues to download only the complete upstream English pack; other local CLPKs
can still be loaded manually, but this fork does not synthesize per-language packs.

## Upstream synchronization workflow

Keep multilingual changes in small topic commits when commits are requested:

1. `git fetch upstream`;
2. review `git log --left-right --cherry-pick multilanguage-core...upstream/main`;
3. merge or rebase only with an explicit choice for the current integration;
4. resolve upstream changes by retaining legacy `en` paths as compatibility
   adapters and keeping language-specific behavior in the central policy modules;
5. run Python unit tests, launcher core tests, and the Release launcher build;
6. inspect `git diff` for DAT files, binary database changes, and generated build
   output before committing.

Do not rewrite the shipped database schema into per-language columns and do not
modify real DAT files as part of a core synchronization.

The application updater defaults to `rockerudon/dqxclarity-plus`; otherwise
an upstream release could replace the fork. Development builds may override this
with `DQXCLARITY_UPDATE_REPOSITORY=owner/repository` or updater `--repository`.
Stable fork tags use `plus-vMAJOR.MINOR.PATCH`; `version.update` remains numeric
for Python packaging. Explicit legacy `v5.x` tags remain supported by the updater.
