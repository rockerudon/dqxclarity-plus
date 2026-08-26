# dqxclarity multilingual

A multilingual fork of the original
[`dqxclarity`](https://github.com/dqx-translation-project/dqxclarity), a
translation utility for *Dragon Quest X Online*.

This fork keeps the original launcher, DragonHook support, English language
pack, translation database updates and runtime translation providers. It adds a
target-language selector, language-isolated caches and safer runtime support for
languages other than English.

## How translation works

The two translation layers are independent:

1. The **English language pack** supplies static game text such as menus, map
   labels, canonical names, items, skills and quest titles.
2. The **runtime translation provider** translates text exposed by the hooks,
   including dialogue, selectable dialogue, walkthroughs, quest descriptions,
   story summaries and supported event prose.

The optional **API translation overlay** lets the provider translate supported
prose even after the English pack has already replaced its Japanese source. It
is disabled by default. Enable it when the target language is not English and
you want supported English-pack prose translated again into that language.

The project does not generate automatic full language packs. At present, the
launcher downloads the maintained English pack as the static foundation. Text
which is neither in that pack nor exposed through a safe hook may remain in
Japanese. Canonical/wiki-searchable names intentionally remain in English.

Because injected DQX text does not reliably render every Unicode glyph, the
database preserves full Unicode while non-Japanese output is converted to a
game-safe ASCII representation at the final write boundary. For example,
`você` is displayed as `voce`.

## Installation

The base setup remains the same as original dqxclarity:

1. Download `dqxclarity.zip` from this repository's latest release.
2. Extract the complete `dqxclarity` folder to a writable location. Antivirus
   software may flag or remove the unsigned executable because it attaches to
   the game process; add an exclusion if necessary.
3. Run `dqxclarity.exe` and configure the Dragon Quest X installation folder.
4. In the installation/configuration area, add **DragonHook** support.
5. Open the **Language** tab, download the English language pack and activate
   it. Without DragonHook and an active pack, static menus remain Japanese.
6. In **General**, select the runtime provider and target language. Google
   Translate Mobile is the free provider and does not require an API key.
7. For a non-English target, optionally enable **API translation overlay** so
   supported prose from the English pack receives a second translation pass.
8. Click **Run**, wait until the console says `Done!`, and then enter the game.

Existing users should close both the game and dqxclarity before replacing
files. Keep a backup of `user_settings.ini` when doing a manual clean install;
normal in-app updates preserve local settings and the multilingual database.

For upstream installation and troubleshooting details, see the
[official dqxclarity documentation](https://dqx-translation-project.github.io/dqxclarity.html)
and its [troubleshooting guide](https://dqx-translation-project.github.io/troubleshooting.html).

## Providers and fallback

All original providers can target the selected language. Provider-specific
language codes are normalized only at their API boundary, while cache entries
retain their full language identity such as `pt-BR` or `zh-Hant`.

When Google Translate Mobile (free) is selected, an additional opt-in setting
can use Yandex only while Google is rate limited. Google is retried when its
bounded cooldown ends. This fallback is disabled by default because affected
text is sent to Yandex.

If a provider fails, returns suspicious HTML/CSS, or damages selectable-dialogue
controls, the result is rejected and the pack/source text remains visible.

## Current limitations

- Static UI coverage is determined by the active language pack and is currently
  English-first.
- Some game render paths are not exposed to runtime hooks and can remain
  Japanese or English.
- Layout limits vary between game windows. Known walkthrough, quest and story
  fields are constrained; unknown writes use conservative safeguards.
- Event/corner text support is implemented and debug-logged, but uncommon
  scenes still benefit from community testing.

## Documentation and development

- [Multilingual architecture](docs/multilingual-architecture.md)
- [Language-pack and API-overlay policy](docs/multilingual-pack-authoring.md)
- [Local build and CLPK guide](scripts/README.md)

Local validation currently covers the Python runtime, multilingual database,
translation providers, structured dialogue and launcher configuration.

## Upstream project and credits

This repository is a fork, not a replacement for the original project. The core
application and English translation ecosystem are maintained by the
[DQX Translation Project](https://github.com/dqx-translation-project).

`dqxclarity` has been in active development since April 2021. The upstream
contributors listed by the original project include:

- @xshobux
- @SuperFirm84
- @Sevithian (built the initial launcher)

Additional history and contributors remain available in the Git history.

## Disclaimer

**Use this software at your own risk. `dqxclarity` alters process memory solely
to display translated game text. The maintainers accept no responsibility for
warnings, account actions or other consequences resulting from its use.**
