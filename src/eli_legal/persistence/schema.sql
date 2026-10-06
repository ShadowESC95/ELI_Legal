-- Starter schema notes only; replace through migrations before production.
CREATE TABLE IF NOT EXISTS matters (
  matter_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  jurisdiction TEXT NOT NULL,
  status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  matter_id TEXT NOT NULL,
  status TEXT NOT NULL,
  FOREIGN KEY(matter_id) REFERENCES matters(matter_id)
);
