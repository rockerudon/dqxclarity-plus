CREATE TABLE IF NOT EXISTS "translation_values" (
    "domain"            TEXT NOT NULL,
    "source_text"       TEXT NOT NULL,
    "language_code"     TEXT NOT NULL,
    "translated_text"   TEXT NOT NULL,
    "translation_kind"  TEXT NOT NULL DEFAULT 'machine'
        CHECK ("translation_kind" IN ('manual', 'machine', 'legacy')),
    "context"           TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (
        "domain", "source_text", "language_code", "translation_kind", "context"
    )
);

CREATE INDEX IF NOT EXISTS "translation_values_lookup"
    ON "translation_values" ("domain", "source_text", "language_code");
