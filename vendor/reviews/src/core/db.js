// Local persistence via node:sqlite (built into Node >=22, no native compile).
import { DatabaseSync } from 'node:sqlite';
import { mkdirSync } from 'node:fs';
import path from 'node:path';

export const SCHEMA_VERSION = 2;

export function openDb(dbPath = 'data/gmaps-reviews.db') {
  const isMemory = dbPath === ':memory:';
  const abs = isMemory ? ':memory:' : path.resolve(dbPath);
  if (!isMemory) mkdirSync(path.dirname(abs), { recursive: true });
  const db = new DatabaseSync(abs);
  try {
  db.exec(`
    PRAGMA foreign_keys = ON;
    PRAGMA busy_timeout = 5000;
    PRAGMA synchronous = NORMAL;
    PRAGMA journal_mode = WAL;
    CREATE TABLE IF NOT EXISTS businesses (
      placeId       TEXT PRIMARY KEY,
      name          TEXT,
      listingUrl    TEXT NOT NULL,
      inputUrl      TEXT,
      reviewsCount  INTEGER,
      rating        REAL,
      firstSeenAt   TEXT NOT NULL,
      lastSeenAt    TEXT
    );
    CREATE TABLE IF NOT EXISTS reviews (
      reviewId        TEXT,
      placeId         TEXT NOT NULL,
      reviewerName    TEXT,
      reviewerProfileUrl TEXT,
      rating          INTEGER,
      ratingRaw       TEXT,
      reviewText      TEXT,
      originalLanguage TEXT,
      translatedByGoogle INTEGER,
      publishedDateRaw  TEXT,
      publishedDateParsed TEXT,
      datePrecision    TEXT,
      ownerResponse    TEXT,
      ownerResponseDateRaw TEXT,
      ownerResponseDateParsed TEXT,
      ownerResponseDatePrecision TEXT,
      reviewUrl       TEXT,
      firstCollectedAt TEXT NOT NULL,
      lastCollectedAt  TEXT NOT NULL,
      collectedCount  INTEGER NOT NULL DEFAULT 1,
      runId           TEXT,
      PRIMARY KEY (placeId, reviewId),
      FOREIGN KEY (placeId) REFERENCES businesses(placeId)
    );
    CREATE INDEX IF NOT EXISTS idx_reviews_place ON reviews(placeId);
    CREATE TABLE IF NOT EXISTS jobs (
      id          TEXT PRIMARY KEY,
      createdAt   TEXT NOT NULL,
      updatedAt   TEXT,
      status      TEXT NOT NULL,             -- queued|running|paused|completed|failed|canceled
      config      TEXT,                      -- JSON
      totalPlaces INTEGER DEFAULT 0,
      notes       TEXT
    );
    CREATE TABLE IF NOT EXISTS job_items (
      jobId       TEXT NOT NULL,
      placeId     TEXT,
      inputUrl    TEXT NOT NULL,
      idx         INTEGER NOT NULL,
      status      TEXT NOT NULL DEFAULT 'pending', -- pending|running|done|failed|skipped|blocked
      attempt     INTEGER NOT NULL DEFAULT 0,
      error       TEXT,
      termination TEXT,                        -- JSON blob of last termination
      updatedAt   TEXT,
      PRIMARY KEY (jobId, idx)
    );
    CREATE TABLE IF NOT EXISTS runs (
      id          TEXT PRIMARY KEY,
      jobId       TEXT,
      startedAt   TEXT NOT NULL,
      endedAt     TEXT,
      config      TEXT
    );
  `);
  const version = db.prepare('PRAGMA user_version').get().user_version;
  if (version > SCHEMA_VERSION) throw new Error(`Database schema ${version} is newer than supported schema ${SCHEMA_VERSION}`);
  if (version < 2) {
    db.exec('BEGIN IMMEDIATE');
    try {
      const additions = {
        reviews: { textTruncated: 'INTEGER', isEdited: 'INTEGER', ownerResponseIsEdited: 'INTEGER', publishedDateEarliest: 'TEXT', publishedDateLatest: 'TEXT', ownerResponseDateEarliest: 'TEXT', ownerResponseDateLatest: 'TEXT', feedRank: 'INTEGER' },
        businesses: { lastCompletedAt: 'TEXT' },
        job_items: { diagnostics: 'TEXT', expectedCount: 'INTEGER', collectedCount: 'INTEGER', completeness: 'REAL' },
      };
      for (const [table, columns] of Object.entries(additions)) {
        const present = new Set(db.prepare(`PRAGMA table_info(${table})`).all().map(c => c.name));
        for (const [column, type] of Object.entries(columns)) if (!present.has(column)) db.exec(`ALTER TABLE ${table} ADD COLUMN ${column} ${type}`);
      }
      db.exec('PRAGMA user_version = 2; COMMIT');
    } catch (error) { db.exec('ROLLBACK'); throw error; }
  }
  return db;
  } catch (error) { db.close(); throw error; }
}
