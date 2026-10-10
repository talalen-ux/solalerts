import { DatabaseSync } from 'node:sqlite';

// Special ledger accounts. Real users are positive Telegram ids.
export const TREASURY = 0;
export const ESCROW = -1; // jam prize pools waiting to be paid out

const SCHEMA = `
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  username TEXT,
  first_name TEXT,
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS communities (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  slug TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  owner_id INTEGER NOT NULL,
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS admins (
  community_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  PRIMARY KEY (community_id, user_id)
);

CREATE TABLE IF NOT EXISTS tokens (
  community_id INTEGER PRIMARY KEY,
  symbol TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  supply INTEGER NOT NULL,
  airdrop_amount INTEGER NOT NULL,
  fee_bps INTEGER NOT NULL,
  burn_bps INTEGER NOT NULL,
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS balances (
  community_id INTEGER NOT NULL,
  account_id INTEGER NOT NULL,
  amount INTEGER NOT NULL DEFAULT 0 CHECK (amount >= 0),
  PRIMARY KEY (community_id, account_id)
);

CREATE TABLE IF NOT EXISTS ledger (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  community_id INTEGER NOT NULL,
  from_id INTEGER,
  to_id INTEGER,
  amount INTEGER NOT NULL,
  kind TEXT NOT NULL,
  memo TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS members (
  community_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  airdropped INTEGER NOT NULL DEFAULT 0,
  joined_at INTEGER NOT NULL,
  PRIMARY KEY (community_id, user_id)
);

CREATE TABLE IF NOT EXISTS chats (
  chat_id INTEGER PRIMARY KEY,
  community_id INTEGER NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('main', 'room')),
  title TEXT NOT NULL DEFAULT '',
  min_balance INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS products (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  community_id INTEGER NOT NULL,
  seller_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  price INTEGER NOT NULL CHECK (price > 0),
  content TEXT NOT NULL,
  min_balance INTEGER NOT NULL DEFAULT 0,
  stock INTEGER,
  active INTEGER NOT NULL DEFAULT 1,
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS purchases (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id INTEGER NOT NULL,
  buyer_id INTEGER NOT NULL,
  price INTEGER NOT NULL,
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS proposals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  community_id INTEGER NOT NULL,
  creator_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  options TEXT NOT NULL,
  ends_at INTEGER NOT NULL,
  closed INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS proposal_snapshots (
  proposal_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  weight INTEGER NOT NULL,
  PRIMARY KEY (proposal_id, user_id)
);

CREATE TABLE IF NOT EXISTS votes (
  proposal_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  option_idx INTEGER NOT NULL,
  weight INTEGER NOT NULL,
  PRIMARY KEY (proposal_id, user_id)
);

CREATE TABLE IF NOT EXISTS jams (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  community_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  theme TEXT NOT NULL DEFAULT '',
  roles TEXT NOT NULL,
  room_size INTEGER NOT NULL,
  prize INTEGER NOT NULL,
  build_minutes INTEGER NOT NULL,
  vote_minutes INTEGER NOT NULL,
  phase TEXT NOT NULL CHECK (phase IN ('lobby', 'building', 'voting', 'closed')),
  build_ends_at INTEGER,
  vote_ends_at INTEGER,
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS jam_rooms (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  jam_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  chat_id INTEGER
);

CREATE TABLE IF NOT EXISTS jam_participants (
  jam_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  role TEXT NOT NULL,
  room_id INTEGER,
  joined_at INTEGER NOT NULL,
  PRIMARY KEY (jam_id, user_id)
);

CREATE TABLE IF NOT EXISTS jam_entries (
  room_id INTEGER PRIMARY KEY,
  jam_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  url TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  submitted_by INTEGER NOT NULL,
  submitted_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS jam_votes (
  jam_id INTEGER NOT NULL,
  voter_id INTEGER NOT NULL,
  room_id INTEGER NOT NULL,
  PRIMARY KEY (jam_id, voter_id)
);

CREATE TABLE IF NOT EXISTS jam_results (
  jam_id INTEGER NOT NULL,
  room_id INTEGER NOT NULL,
  rank INTEGER NOT NULL,
  votes INTEGER NOT NULL,
  payout_each INTEGER NOT NULL,
  PRIMARY KEY (jam_id, room_id)
);

CREATE TABLE IF NOT EXISTS room_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  room_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  text TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
`;

export function openDb(path = ':memory:') {
  const db = new DatabaseSync(path);
  db.exec('PRAGMA journal_mode = WAL; PRAGMA foreign_keys = ON;');
  db.exec(SCHEMA);
  return db;
}

// Runs fn inside a transaction; nested calls join the outer one.
export function tx(db, fn) {
  if (db.__inTx) return fn();
  db.exec('BEGIN IMMEDIATE');
  db.__inTx = true;
  try {
    const out = fn();
    db.exec('COMMIT');
    return out;
  } catch (err) {
    db.exec('ROLLBACK');
    throw err;
  } finally {
    db.__inTx = false;
  }
}
