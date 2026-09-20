# dqxclarity plus

A community fork of the original
[`dqxclarity`](https://github.com/dqx-translation-project/dqxclarity), a
translation utility for *Dragon Quest X Online*.

This fork keeps the original launcher, DragonHook support, English language
pack, translation database updates and runtime translation providers. It adds a
target-language selector, language-isolated caches and safer runtime support for
languages other than English.

It also adds optional player-chat history translation and a chat input that
can prepare Japanese messages in the game, with optional automatic translation.

## Fork versions and updates

dqxclarity plus releases use their own tags, starting with **`plus-v1.0.0`**. They are not
official dqxclarity releases. `version.update` retains a numeric version (`1.0.0`)
for Python packaging; the launcher and updater recognize the `plus-v` prefix.
The locally tracked upstream baseline for this release is **v5.27.0**; the old
fork releases numbered v5.26.2–v5.26.6 are not upstream version numbers.

The repository is moving from `rockerudon/dqxclarity-multilang` to
[`rockerudon/dqxclarity-plus`](https://github.com/rockerudon/dqxclarity-plus).
Existing tags and releases are preserved. The executable, release ZIP asset and
package directory remain `dqxclarity.exe`, `dqxclarity.zip` and `dqxclarity/` for
updater compatibility. Do not recreate a repository at the old URL: older
installations rely on GitHub's redirect during migration.

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
When one appears inside translated prose, the runtime takes its official English
spelling from the upstream database, protects it during the provider request and
restores it afterward. The provider still receives the complete sentence for
grammar and context.

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
8. Optionally enable **Translate chat history** beside **Nameplates**. Received
   player messages then appear translated in the launcher's **Chat** tab; player
   speech bubbles are left untouched. With a fresh in-game chat box open, the
   input at the bottom writes text directly into DQX, or translates it to Japanese
   first when its checkbox is enabled. The launcher enforces DQX's 40-character
   chat-message limit and does not press Enter for you.
9. Click **Run**, wait until the console says `Done!`, and then enter the game.

Existing users should close both the game and dqxclarity before replacing
files. Keep a backup of `user_settings.ini` when doing a manual clean install;
normal in-app updates preserve local settings and the multilingual database.

For upstream installation and troubleshooting details, see the
[official dqxclarity documentation](https://dqx-translation-project.github.io/dqxclarity.html)
and its [troubleshooting guide](https://dqx-translation-project.github.io/troubleshooting.html).

## Providers

All original providers can target the selected language. The launcher offers
English, Brazilian and European Portuguese, Spanish, French, German, Italian,
Dutch, Polish and Turkish. Provider-specific language codes are normalized only
at their API boundary, while cache entries retain their full language identity
such as `pt-BR` or `pt-PT`.

The free Google adapter uses Google's keyless JSON endpoint and rotates over four
public client ids, because Google throttles each id separately. At startup
dqxclarity sends one probe request so the first dialogue line does not pay for
that discovery. Only when every id refuses does it apply a bounded cooldown of
5, 15, then 30 seconds and retry Google afterwards. Text arriving during the
cooldown keeps its pack translation and is never forwarded to another provider;
Yandex remains available only as a separately selected provider.

If a provider fails, returns suspicious HTML/CSS, or damages selectable-dialogue
controls, the result is rejected and the pack/source text remains visible.

Server-delivered banners (`<%sM_header>`, `<%sEV_QUEST_NAME>`) have no pack
entry on an event's first day, so they are translated live and never written to
the database - a stale event name would outlive the event. The source buffer is
the byte limit: a translation that only fits when shortened is truncated, and
the string is logged with `>>` so a pack author can supply a shorter name. A
manual pack entry always wins over the live translation.

## Current limitations

- Static UI coverage is determined by the active language pack and is currently
  English-first.
- Arabic, Cyrillic, Chinese and Korean targets are not offered because DQX does
  not reliably render those scripts and ASCII romanization is not sufficiently
  readable. Japanese is the source language and is not a translation target.
- Some game render paths are not exposed to runtime hooks and can remain
  Japanese or English.
- Layout limits vary between game windows. Known walkthrough, quest and story
  fields are constrained; unknown writes use conservative safeguards.
- Event/corner text support is implemented and debug-logged, but uncommon
  scenes still benefit from community testing.

### Player chat

Chat translation is opt-in. Captured messages are sent to the selected
translation provider; names and recognized recipient suffixes are handled
locally. Debug logs may contain message text, so review them before sharing.

The launcher reserves a row when a message is captured and updates it in place
when translation finishes. Provider work runs in the background, with at most
eight requests waiting and one active request. Repeated text shares a translation
request; queue-full and failed-translation states remain visible in the launcher.

Capture currently depends on the game's history formatter, not a server-message
notification. Messages never rendered may not be captured, and capture order is
not guaranteed to be the original conversation order. Render deduplication cannot
reliably distinguish identical messages from the same sender when the game reuses
the same buffer. Long translations can be clipped in the game; the launcher shows
the full translation. Supported kana names are romanized locally, with conservative
fallback for unrecognized names or layouts. Speech bubbles are not modified.

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

**Use this software at your own risk. `dqxclarity` alters process memory to
display translated game text and prepare user-authored chat input. The maintainers accept no responsibility for
warnings, account actions or other consequences resulting from its use.**
