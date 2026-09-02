"""SQLite access with language-isolated, backward-compatible translations."""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from common.config import UserConfig
from common.language import DEFAULT_LANGUAGE, LanguageContext, is_suspicious_translation
from common.lib import get_project_root
from common.translation_domains import SUPPORTED_TRANSLATION_DOMAINS
from functools import cache
from loguru import logger as log
from pathlib import Path


_TRANSLATION_TABLE = "translation_values"
_MACHINE_CACHE_VERSION = "canonical-english-v3"
_DYNAMIC_MACHINE_DOMAINS = (
    "corner_text",
    "dialog",
    "fixed_dialog_template",
    "quests",
    "story_so_far",
    "walkthrough",
)
_CANONICAL_M00_FILES = (
    "items",
    "key_items",
    "monsters",
    "npcs",
    "quests",
    "story_names",
    "custom_npc_name_overrides",
    "custom_concierge_mail_names",
)
_CANONICAL_CONNECTORS = frozenset({"a", "an", "and", "at", "for", "from", "in", "of", "on", "the", "to", "with"})
_KATAKANA_NAME_RE = re.compile(r"[\u30a0-\u30ff\uff65-\uff9fー・ ]+")


def init_db(db_path: str | Path | None = None) -> tuple[sqlite3.Connection, sqlite3.Cursor]:
    """Return a SQLite connection and cursor for the runtime database."""

    path = str(db_path or get_project_root("misc_files/clarity_dialog.db"))
    conn = sqlite3.connect(path)
    return conn, conn.cursor()


def _validate_table(table: str) -> str:
    if table not in SUPPORTED_TRANSLATION_DOMAINS:
        raise ValueError(f"Unsupported translation table: {table}")
    return table


def _active_language(language_code: str | None = None) -> LanguageContext:
    return LanguageContext.create(language_code) if language_code is not None else UserConfig().active_language


def _table_exists(cursor: sqlite3.Cursor, table: str) -> bool:
    return cursor.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone() is not None


def _legacy_columns(cursor: sqlite3.Cursor, table: str) -> list[str]:
    if not _table_exists(cursor, table):
        return []
    return [row[1] for row in cursor.execute(f'PRAGMA table_info("{table}")')]


def create_db_schema(db_path: str | Path | None = None) -> None:
    """Create legacy tables and apply additive, idempotent migrations."""

    conn: sqlite3.Connection | None = None
    try:
        conn, cursor = init_db(db_path)
        schema_file = Path(get_project_root("common/db_scripts/schema.sql"))
        cursor.executescript(schema_file.read_text(encoding="utf-8"))
        migrations_dir = Path(get_project_root("common/db_scripts/migrations"))
        for migration in sorted(migrations_dir.glob("*.sql")):
            cursor.executescript(migration.read_text(encoding="utf-8"))
        _refresh_machine_cache_version(cursor)
        conn.commit()
    except (OSError, sqlite3.Error, ValueError) as exc:
        if conn:
            conn.rollback()
        log.exception(f"Failed to create or migrate schema. {exc}.")
        raise
    finally:
        if conn:
            conn.close()


def db_query(query: str) -> None:
    """Execute a legacy freeform query used by the upstream import pipeline."""

    conn: sqlite3.Connection | None = None
    try:
        conn, cursor = init_db()
        cursor.execute(query)
        conn.commit()
    except sqlite3.Error as exc:
        log.exception(f"Query failed. {exc}")
    finally:
        if conn:
            conn.close()


def _parse_legacy_file_filter(files: str | None) -> list[str]:
    return re.findall(r"'([^']+)'", files or "")


def _language_chain(language_code: str | None, allow_english_fallback: bool) -> tuple[str, ...]:
    language = _active_language(language_code)
    if allow_english_fallback:
        return language.fallback_codes(include_english=True, include_source=False)
    return (language.code,)


def _read_normalized_rows(
    cursor: sqlite3.Cursor,
    domain: str,
    language_code: str,
    contexts: list[str] | None = None,
) -> list[tuple[str, str]]:
    params: list[str] = [domain, language_code]
    context_clause = ""
    if contexts:
        placeholders = ",".join("?" for _ in contexts)
        context_clause = f" AND context IN ({placeholders})"
        params.extend(contexts)
    return cursor.execute(
        f"""
        SELECT source_text, translated_text
        FROM translation_values
        WHERE domain = ? AND language_code = ?{context_clause}
        ORDER BY CASE translation_kind WHEN 'manual' THEN 0 WHEN 'machine' THEN 1 ELSE 2 END
        """,
        params,
    ).fetchall()


def _read_normalized_value(
    cursor: sqlite3.Cursor,
    source_text: str,
    domain: str,
    language_code: str,
    *,
    wildcard: bool,
) -> str | None:
    if not _table_exists(cursor, _TRANSLATION_TABLE):
        return None
    comparator = "source_text LIKE ?" if wildcard else "source_text = ?"
    value = f"%{source_text.replace(chr(10), '%')}%" if wildcard else source_text
    row = cursor.execute(
        f"""
        SELECT translated_text FROM translation_values
        WHERE domain = ? AND language_code = ? AND {comparator}
        ORDER BY CASE translation_kind WHEN 'manual' THEN 0 WHEN 'machine' THEN 1 ELSE 2 END
        LIMIT 1
        """,
        (domain, language_code, value),
    ).fetchone()
    return row[0] if row else None


def generate_m00_dict(
    files: str = "",
    *,
    language_code: str | None = None,
    allow_english_fallback: bool = True,
) -> dict[str, str]:
    """Return localized static strings, with explicit manual-data fallback."""

    conn: sqlite3.Connection | None = None
    try:
        conn, cursor = init_db()
        contexts = _parse_legacy_file_filter(files)
        chain = _language_chain(language_code, allow_english_fallback)
        data: dict[str, str] = {}
        for code in chain:
            if _table_exists(cursor, _TRANSLATION_TABLE):
                for source, translated in _read_normalized_rows(cursor, "m00_strings", code, contexts):
                    data.setdefault(source, translated)

        # English legacy rows remain authoritative for upstream imports made
        # after the one-time migration.
        if DEFAULT_LANGUAGE in chain:
            query = "SELECT ja, en FROM m00_strings"
            params: list[str] = []
            if contexts:
                query += f" WHERE file IN ({','.join('?' for _ in contexts)})"
                params.extend(contexts)
            for source, translated in cursor.execute(query, params):
                if translated:
                    data.setdefault(source, translated)
        return data
    except sqlite3.Error as exc:
        log.exception(f"Query failed. {exc}.")
        return {}
    finally:
        if conn:
            conn.close()


def generate_glossary_dict(*, language_code: str | None = None) -> dict[str, str]:
    """Return only the active-language glossary (never an English cache leak)."""

    conn: sqlite3.Connection | None = None
    try:
        conn, cursor = init_db()
        code = _active_language(language_code).code
        data: dict[str, str] = {}
        if _table_exists(cursor, _TRANSLATION_TABLE):
            for source, translated in _read_normalized_rows(cursor, "glossary", code):
                data.setdefault(source, translated)
        if code == DEFAULT_LANGUAGE:
            for source, translated in cursor.execute("SELECT ja, en FROM glossary"):
                if translated:
                    data.setdefault(source, translated)

        def key_len(item: tuple[str, str]) -> int:
            return len(item[0].split(",", 1)[0].encode("utf-8"))

        return dict(sorted(data.items(), key=key_len, reverse=True))
    except sqlite3.Error as exc:
        log.exception(f"Query failed. {exc}.")
        return {}
    finally:
        if conn:
            conn.close()


def read_translation(
    source_text: str,
    domain: str,
    *,
    language_code: str | None = None,
    wildcard: bool = False,
    allow_english_fallback: bool = False,
) -> str | None:
    """Read a translation with manual-over-machine priority.

    Dynamic callers default to strict active-language isolation. English fallback
    must be explicitly enabled by a caller that knows it is appropriate.
    """

    _validate_table(domain)
    conn: sqlite3.Connection | None = None
    try:
        conn, cursor = init_db()
        for code in _language_chain(language_code, allow_english_fallback):
            value = _read_normalized_value(cursor, source_text, domain, code, wildcard=wildcard)
            if value is not None and not is_suspicious_translation(value):
                return value

            # Preserve untouched English databases even before migration.
            columns = _legacy_columns(cursor, domain)
            if code == DEFAULT_LANGUAGE and "en" in columns:
                comparator = "ja LIKE ?" if wildcard else "ja = ?"
                value = f"%{source_text.replace(chr(10), '%')}%" if wildcard else source_text
                row = cursor.execute(f'SELECT en FROM "{domain}" WHERE {comparator} LIMIT 1', (value,)).fetchone()
                if row and row[0] and not is_suspicious_translation(row[0]):
                    return row[0]
        return None
    except sqlite3.Error:
        log.exception(f"Failed to query {domain}.")
        return None
    finally:
        if conn:
            conn.close()


def sql_read(text: str, table: str, wildcard: bool = False, *, language_code: str | None = None) -> str | None:
    """Backward-compatible name for a strict language-isolated cache read."""

    return read_translation(text, table, language_code=language_code, wildcard=wildcard)


_COSMETIC_DIALOGUE_TAGS = frozenset({"attr", "end_attr", "center", "right", "left"})


def _strip_cosmetic_dialogue_tag(match: re.Match[str]) -> str:
    """Drop presentation-only tags while retaining parser control tags."""

    tag = match.group(0)
    name_match = re.match(r"<\s*/?\s*([^\s/>]+)", tag)
    if not name_match:
        return tag
    name = name_match.group(1).lower()
    if name in _COSMETIC_DIALOGUE_TAGS or name.startswith("color_"):
        return ""
    return tag


def _dialogue_variant_key(text: str) -> str:
    """Normalize only harmless dialogue presentation differences.

    Selection, line-break, voice and placeholder tags intentionally remain in
    the key. Removing every tag made unrelated game states collide and could
    display a cached line for the wrong dialogue.
    """

    normalized = re.sub(r"<[^>]+>", _strip_cosmetic_dialogue_tag, text or "")
    normalized = unicodedata.normalize("NFKC", normalized)
    normalized = normalized.translate(str.maketrans({"「": "", "」": "", "『": "", "』": ""}))
    return re.sub(r"\s+", "", normalized)


@cache
def _dialogue_variant_rows(language_code: str) -> dict[str, str]:
    """Load normalized dialogue cache keys once per language for tag variants."""

    conn: sqlite3.Connection | None = None
    try:
        conn, cursor = init_db()
        rows: list[tuple[str, str]] = []
        if _table_exists(cursor, _TRANSLATION_TABLE):
            rows.extend(
                cursor.execute(
                    """
                    SELECT source_text, translated_text
                    FROM translation_values
                    WHERE domain = ? AND language_code = ?
                    ORDER BY CASE translation_kind WHEN 'manual' THEN 0 WHEN 'machine' THEN 1 ELSE 2 END
                    """,
                    ("dialog", language_code),
                ).fetchall()
            )

        # Untouched upstream English databases intentionally remain in the
        # legacy table. Include them here so cosmetic source variants still
        # find the hand-authored pack without requiring a destructive import.
        if language_code == DEFAULT_LANGUAGE and "en" in _legacy_columns(cursor, "dialog"):
            rows.extend(cursor.execute("SELECT ja, en FROM dialog WHERE en IS NOT NULL AND en != ''").fetchall())

        result: dict[str, str] = {}
        ambiguous: set[str] = set()
        preferred_by_source: dict[str, str] = {}
        for source, translated in rows:
            if translated and not is_suspicious_translation(translated):
                preferred_by_source.setdefault(source, translated)

        for source, translated in preferred_by_source.items():
            if translated and not is_suspicious_translation(translated):
                key = _dialogue_variant_key(source)
                existing = result.get(key)
                if existing is None:
                    result[key] = translated
                elif existing != translated:
                    ambiguous.add(key)
        for key in ambiguous:
            result.pop(key, None)
        return result
    except sqlite3.Error:
        log.exception("Failed to load normalized dialogue cache.")
        return {}
    finally:
        if conn:
            conn.close()


def _refresh_machine_cache_version(cursor: sqlite3.Cursor) -> None:
    """Invalidate obsolete MTL output once, preserving manual and pack data."""

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS translation_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    row = cursor.execute(
        "SELECT value FROM translation_metadata WHERE key = 'machine_cache_version'"
    ).fetchone()
    if row and row[0] == _MACHINE_CACHE_VERSION:
        return

    placeholders = ",".join("?" for _ in _DYNAMIC_MACHINE_DOMAINS)
    cursor.execute(
        f"DELETE FROM translation_values WHERE translation_kind = 'machine' AND domain IN ({placeholders})",
        _DYNAMIC_MACHINE_DOMAINS,
    )
    cursor.execute(
        """
        INSERT INTO translation_metadata (key, value)
        VALUES ('machine_cache_version', ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (_MACHINE_CACHE_VERSION,),
    )


def _canonical_title_case(text: str) -> bool:
    """Conservatively distinguish names/titles from ordinary glossary prose."""

    if not text or "\n" in text or len(text) > 80 or re.search(r"[.!?;:<>{}=+%]", text):
        return False
    words = re.findall(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*", text)
    if not words:
        return False
    for index, word in enumerate(words):
        plain = word.strip("'’-")
        if not plain or plain.isdigit() or re.fullmatch(r"[IVXLCDM]+", plain):
            continue
        if index and plain.lower() in _CANONICAL_CONNECTORS:
            continue
        if not plain[0].isupper():
            return False
    return True


@cache
def generate_canonical_glossary() -> dict[str, str]:
    """Return Japanese-to-official-English pairs safe to preserve during MTL.

    Static tables contain item descriptions as well as names, so this loader
    intentionally accepts only short title-like values. The broad glossary is
    filtered more strictly; single-word entries must look like transliterated
    Japanese names or also occur inside a trusted static name.
    """

    conn: sqlite3.Connection | None = None
    try:
        conn, cursor = init_db()
        placeholders = ",".join("?" for _ in _CANONICAL_M00_FILES)
        strong_rows = cursor.execute(
            f"SELECT ja, en FROM m00_strings WHERE file IN ({placeholders}) AND en IS NOT NULL AND en != ''",
            _CANONICAL_M00_FILES,
        ).fetchall()
        pairs: dict[str, str] = {
            source: english
            for source, english in strong_rows
            if source and _canonical_title_case(english)
        }
        trusted_words = {
            word
            for english in pairs.values()
            for word in re.findall(r"[A-Za-z][A-Za-z'’-]+", english)
            if word[0].isupper()
        }

        for source, english in cursor.execute("SELECT ja, en FROM glossary WHERE en IS NOT NULL AND en != ''"):
            if not source or not _canonical_title_case(english):
                continue
            words = re.findall(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*", english)
            if len(words) > 1 or english in trusted_words or _KATAKANA_NAME_RE.fullmatch(source):
                pairs.setdefault(source, english)

        # Long Japanese keys win when a location contains a shorter place name.
        return dict(sorted(pairs.items(), key=lambda item: len(item[0]), reverse=True))
    except sqlite3.Error as exc:
        log.exception(f"Unable to load canonical English terms. {exc}.")
        return {}
    finally:
        if conn:
            conn.close()


def read_dialogue_translation_variant(source_text: str, *, language_code: str | None = None) -> str | None:
    """Read a cached dialogue when only tags/quote/spacing differ."""

    code = _active_language(language_code).code
    return _dialogue_variant_rows(code).get(_dialogue_variant_key(source_text))


def write_translation(
    source_text: str,
    translated_text: str,
    domain: str,
    *,
    language_code: str | None = None,
    translation_kind: str = "machine",
    context: str = "",
) -> None:
    """Upsert full-Unicode translated text for exactly one language."""

    _validate_table(domain)
    if is_suspicious_translation(translated_text):
        log.warning("Refusing to cache suspicious HTML/CSS translation output.")
        return
    if translation_kind not in {"manual", "machine", "legacy"}:
        raise ValueError(f"Invalid translation kind: {translation_kind}")
    code = _active_language(language_code).code
    conn: sqlite3.Connection | None = None
    try:
        conn, cursor = init_db()
        cursor.execute(
            """
            INSERT INTO translation_values
                (domain, source_text, language_code, translated_text, translation_kind, context)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(domain, source_text, language_code, translation_kind, context)
            DO UPDATE SET translated_text = excluded.translated_text
            """,
            (domain, source_text, code, translated_text, translation_kind, context),
        )

        # English keeps the original column updated for upstream compatibility.
        columns = _legacy_columns(cursor, domain)
        if code == DEFAULT_LANGUAGE and "ja" in columns and "en" in columns:
            if domain == "m00_strings":
                if context:
                    cursor.execute(
                        "UPDATE m00_strings SET en = ? WHERE ja = ? AND COALESCE(file, '') = ?",
                        (translated_text, source_text, context),
                    )
                else:
                    cursor.execute("UPDATE m00_strings SET en = ? WHERE ja = ?", (translated_text, source_text))
                if cursor.rowcount == 0:
                    cursor.execute(
                        "INSERT INTO m00_strings (ja, en, file) VALUES (?, ?, ?)",
                        (source_text, translated_text, context or None),
                    )
            else:
                cursor.execute(
                    f"""
                    INSERT INTO "{domain}" (ja, en) VALUES (?, ?)
                    ON CONFLICT(ja) DO UPDATE SET en = excluded.en
                    """,
                    (source_text, translated_text),
                )
        conn.commit()
        if domain == "dialog":
            _dialogue_variant_rows.cache_clear()
    except sqlite3.Error:
        if conn:
            conn.rollback()
        log.exception(f"Unable to write data to {domain}.")
        raise
    finally:
        if conn:
            conn.close()


def sql_write(
    source_text: str,
    translated_text: str,
    table: str,
    *,
    language_code: str | None = None,
) -> None:
    """Backward-compatible name for a machine-translation cache write."""

    write_translation(source_text, translated_text, table, language_code=language_code)


def write_dialogue_translation(
    source_text: str,
    translated_text: str,
    npc_name: str,
    *,
    language_code: str | None = None,
) -> None:
    """Write dialogue text while retaining the legacy NPC context field."""

    write_translation(source_text, translated_text, "dialog", language_code=language_code)
    conn: sqlite3.Connection | None = None
    try:
        conn, cursor = init_db()
        cursor.execute(
            """
            INSERT INTO dialog (ja, npc_name) VALUES (?, ?)
            ON CONFLICT(ja) DO UPDATE SET npc_name = excluded.npc_name
            """,
            (source_text, npc_name),
        )
        conn.commit()
    except sqlite3.Error:
        if conn:
            conn.rollback()
        log.exception("Unable to retain dialogue NPC context.")
        raise
    finally:
        if conn:
            conn.close()


def search_bad_strings(text: str, *, language_code: str | None = None) -> str | None:
    """Find an active-language manual correction contained in ``text``."""

    conn: sqlite3.Connection | None = None
    try:
        conn, cursor = init_db()
        code = _active_language(language_code).code
        if _table_exists(cursor, _TRANSLATION_TABLE):
            rows = cursor.execute(
                """
                SELECT source_text, translated_text FROM translation_values
                WHERE domain = 'bad_strings' AND language_code = ?
                ORDER BY length(CAST(source_text AS BLOB)) DESC,
                    CASE translation_kind WHEN 'manual' THEN 0 WHEN 'machine' THEN 1 ELSE 2 END
                """,
                (code,),
            ).fetchall()
            for source, translated in rows:
                if source in text:
                    return translated
        if code == DEFAULT_LANGUAGE:
            for source, translated in cursor.execute("SELECT ja, en FROM bad_strings"):
                if source in text:
                    return translated
        return None
    except sqlite3.Error as exc:
        log.exception(f"Query failed. {exc}.")
        return None
    finally:
        if conn:
            conn.close()
