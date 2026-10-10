import { EventEmitter } from 'node:events';
import { tx, TREASURY, ESCROW } from './db.js';

export class BubbleError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

const fail = (status, msg) => { throw new BubbleError(status, msg); };
const MAX_SUPPLY = 1_000_000_000_000;
const PRIZE_SPLIT = [50, 30, 20]; // % of the pool for 1st/2nd/3rd room

function int(v, name, { min = 0, max = MAX_SUPPLY } = {}) {
  const n = Number(v);
  if (!Number.isSafeInteger(n) || n < min || n > max) fail(400, `${name} must be an integer between ${min} and ${max}`);
  return n;
}

function str(v, name, { min = 1, max = 200 } = {}) {
  const s = typeof v === 'string' ? v.trim() : '';
  if (s.length < min || s.length > max) fail(400, `${name} must be ${min}-${max} characters`);
  return s;
}

/**
 * All of bubble's rules live here: token launches, the ledger, the shop,
 * token-gated access, governance and build jams. The HTTP API and the bot
 * are thin layers on top. Emits events the bot turns into Telegram messages.
 */
export function createCore(db, { now = () => Date.now() } = {}) {
  const events = new EventEmitter();
  const q = (sql) => db.prepare(sql);

  // ---------- users & communities ----------

  function upsertUser({ id, username = null, first_name = null }) {
    q(`INSERT INTO users (id, username, first_name, created_at) VALUES (?, ?, ?, ?)
       ON CONFLICT(id) DO UPDATE SET username = excluded.username, first_name = excluded.first_name`)
      .run(id, username, first_name, now());
    return q('SELECT * FROM users WHERE id = ?').get(id);
  }

  /** Accepts a numeric Telegram id or an @username. */
  function findUser(ref) {
    const r = String(ref ?? '').trim().replace(/^@/, '');
    const u = /^\d+$/.test(r)
      ? q('SELECT * FROM users WHERE id = ?').get(Number(r))
      : q('SELECT * FROM users WHERE username = ? COLLATE NOCASE').get(r);
    if (!u) fail(404, 'user not found (they need to open bubble once)');
    return u;
  }

  function community(idOrSlug) {
    const c = typeof idOrSlug === 'number'
      ? q('SELECT * FROM communities WHERE id = ?').get(idOrSlug)
      : q('SELECT * FROM communities WHERE slug = ?').get(idOrSlug);
    if (!c) fail(404, 'community not found');
    return c;
  }

  function isAdmin(cid, userId) {
    return !!q('SELECT 1 FROM admins WHERE community_id = ? AND user_id = ?').get(cid, userId);
  }

  function requireAdmin(cid, userId) {
    if (!isAdmin(cid, userId)) fail(403, 'admins only');
  }

  function requireToken(cid) {
    const t = q('SELECT * FROM tokens WHERE community_id = ?').get(cid);
    if (!t) fail(409, 'this community has not launched its token yet');
    return t;
  }

  function createCommunity(ownerId, { slug, name, description = '' }) {
    slug = str(slug, 'slug', { min: 3, max: 32 }).toLowerCase();
    if (!/^[a-z0-9-]+$/.test(slug)) fail(400, 'slug may only contain a-z, 0-9 and -');
    name = str(name, 'name', { max: 64 });
    description = str(description, 'description', { min: 0, max: 500 });
    if (q('SELECT 1 FROM communities WHERE slug = ?').get(slug)) fail(409, 'slug already taken');
    return tx(db, () => {
      const { lastInsertRowid } = q(`INSERT INTO communities (slug, name, description, owner_id, created_at)
        VALUES (?, ?, ?, ?, ?)`).run(slug, name, description, ownerId, now());
      const id = Number(lastInsertRowid);
      q('INSERT INTO admins (community_id, user_id) VALUES (?, ?)').run(id, ownerId);
      join(id, ownerId);
      return community(id);
    });
  }

  function addAdmin(cid, actorId, userId) {
    requireAdmin(cid, actorId);
    q('INSERT OR IGNORE INTO admins (community_id, user_id) VALUES (?, ?)').run(cid, userId);
  }

  function listCommunities() {
    return q(`SELECT c.id, c.slug, c.name, c.description, t.symbol, t.supply,
        (SELECT COUNT(*) FROM members m WHERE m.community_id = c.id) AS members
      FROM communities c LEFT JOIN tokens t ON t.community_id = c.id
      ORDER BY members DESC, c.id DESC LIMIT 100`).all();
  }

  // ---------- token launch & ledger ----------

  /**
   * Mints the community token. creator_pct goes to the launcher, the rest
   * sits in the treasury, which funds airdrops, rewards and jam prizes.
   */
  function launchToken(cid, actorId, { symbol, name, supply, creator_pct = 10, airdrop_amount = 0, fee_bps = 500, burn_bps = 100 }) {
    requireAdmin(cid, actorId);
    if (q('SELECT 1 FROM tokens WHERE community_id = ?').get(cid)) fail(409, 'token already launched');
    symbol = str(symbol, 'symbol', { min: 2, max: 10 }).toUpperCase();
    if (!/^[A-Z0-9]+$/.test(symbol)) fail(400, 'symbol may only contain letters and digits');
    if (q('SELECT 1 FROM tokens WHERE symbol = ?').get(symbol)) fail(409, 'symbol already taken');
    name = str(name, 'token name', { max: 64 });
    supply = int(supply, 'supply', { min: 1000 });
    creator_pct = int(creator_pct, 'creator_pct', { max: 50 });
    airdrop_amount = int(airdrop_amount, 'airdrop_amount', { max: supply });
    fee_bps = int(fee_bps, 'fee_bps', { max: 5000 });
    burn_bps = int(burn_bps, 'burn_bps', { max: 5000 });
    if (fee_bps + burn_bps > 5000) fail(400, 'fee + burn may not exceed 50%');

    return tx(db, () => {
      q(`INSERT INTO tokens (community_id, symbol, name, supply, airdrop_amount, fee_bps, burn_bps, created_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?)`).run(cid, symbol, name, supply, airdrop_amount, fee_bps, burn_bps, now());
      const creatorAmt = Math.floor((supply * creator_pct) / 100);
      mint(cid, TREASURY, supply - creatorAmt, 'launch');
      if (creatorAmt) mint(cid, actorId, creatorAmt, 'launch');
      const token = requireToken(cid);
      events.emit('token_launched', { community: community(cid), token });
      return token;
    });
  }

  function balance(cid, accountId) {
    return q('SELECT amount FROM balances WHERE community_id = ? AND account_id = ?').get(cid, accountId)?.amount ?? 0;
  }

  function credit(cid, accountId, amount) {
    q(`INSERT INTO balances (community_id, account_id, amount) VALUES (?, ?, ?)
       ON CONFLICT(community_id, account_id) DO UPDATE SET amount = amount + excluded.amount`).run(cid, accountId, amount);
  }

  function debit(cid, accountId, amount) {
    if (balance(cid, accountId) < amount) fail(402, 'insufficient balance');
    q('UPDATE balances SET amount = amount - ? WHERE community_id = ? AND account_id = ?').run(amount, cid, accountId);
  }

  function log(cid, from, to, amount, kind, memo = '') {
    q(`INSERT INTO ledger (community_id, from_id, to_id, amount, kind, memo, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)`)
      .run(cid, from, to, amount, kind, memo, now());
  }

  function mint(cid, to, amount, kind) {
    credit(cid, to, amount);
    log(cid, null, to, amount, kind);
  }

  function move(cid, from, to, amount, kind, memo = '') {
    if (amount <= 0) return;
    tx(db, () => {
      debit(cid, from, amount);
      credit(cid, to, amount);
      log(cid, from, to, amount, kind, memo);
    });
  }

  function burn(cid, from, amount) {
    if (amount <= 0) return;
    tx(db, () => {
      debit(cid, from, amount);
      q('UPDATE tokens SET supply = supply - ? WHERE community_id = ?').run(amount, cid);
      log(cid, from, null, amount, 'burn');
    });
  }

  function transfer(cid, fromId, toId, amount, memo = '') {
    requireToken(cid);
    amount = int(amount, 'amount', { min: 1 });
    if (fromId === toId) fail(400, 'cannot send to yourself');
    if (!q('SELECT 1 FROM users WHERE id = ?').get(toId)) fail(404, 'recipient has never opened bubble');
    move(cid, fromId, toId, amount, 'transfer', str(memo, 'memo', { min: 0, max: 140 }));
    join(cid, toId);
    events.emit('transfer', { cid, fromId, toId, amount });
  }

  /** Treasury-funded reward, e.g. for helping out in chat. */
  function reward(cid, actorId, userId, amount, reason = '') {
    requireAdmin(cid, actorId);
    requireToken(cid);
    amount = int(amount, 'amount', { min: 1 });
    if (!q('SELECT 1 FROM users WHERE id = ?').get(userId)) fail(404, 'user has never opened bubble');
    move(cid, TREASURY, userId, amount, 'reward', str(reason, 'reason', { min: 0, max: 140 }));
    join(cid, userId);
    events.emit('reward', { cid, userId, amount, reason });
  }

  // ---------- membership ----------

  function join(cid, userId) {
    q('INSERT OR IGNORE INTO members (community_id, user_id, joined_at) VALUES (?, ?, ?)').run(cid, userId, now());
  }

  /** One-time welcome airdrop from the treasury. */
  function claimAirdrop(cid, userId) {
    const token = requireToken(cid);
    join(cid, userId);
    return tx(db, () => {
      const m = q('SELECT airdropped FROM members WHERE community_id = ? AND user_id = ?').get(cid, userId);
      if (m.airdropped) fail(409, 'airdrop already claimed');
      if (!token.airdrop_amount) fail(409, 'this community has no airdrop');
      if (balance(cid, TREASURY) < token.airdrop_amount) fail(409, 'treasury is empty');
      q('UPDATE members SET airdropped = 1 WHERE community_id = ? AND user_id = ?').run(cid, userId);
      move(cid, TREASURY, userId, token.airdrop_amount, 'airdrop');
      return token.airdrop_amount;
    });
  }

  // ---------- token-gated chats ----------

  function linkChat(cid, actorId, { chat_id, kind, title = '', min_balance = 0 }) {
    requireAdmin(cid, actorId);
    if (!['main', 'room'].includes(kind)) fail(400, 'kind must be main or room');
    min_balance = int(min_balance, 'min_balance');
    q(`INSERT INTO chats (chat_id, community_id, kind, title, min_balance) VALUES (?, ?, ?, ?, ?)
       ON CONFLICT(chat_id) DO UPDATE SET community_id = excluded.community_id, kind = excluded.kind,
         title = excluded.title, min_balance = excluded.min_balance`)
      .run(chat_id, cid, kind, title, min_balance);
    return q('SELECT * FROM chats WHERE chat_id = ?').get(chat_id);
  }

  function chat(chatId) {
    return q('SELECT * FROM chats WHERE chat_id = ?').get(chatId) ?? null;
  }

  function mainChat(cid) {
    return q("SELECT * FROM chats WHERE community_id = ? AND kind = 'main'").get(cid) ?? null;
  }

  /**
   * Decides a Telegram join request. Main chats are gated by balance; room
   * chats only admit the jam participants assigned to that room.
   */
  function canEnterChat(chatId, userId) {
    const c = chat(chatId);
    if (!c) return { ok: false, reason: 'chat is not managed by bubble' };
    if (c.kind === 'room') {
      const inRoom = q(`SELECT 1 FROM jam_participants p JOIN jam_rooms r ON r.id = p.room_id
        JOIN jams j ON j.id = r.jam_id WHERE r.chat_id = ? AND p.user_id = ? AND j.phase != 'closed'`).get(chatId, userId);
      return inRoom ? { ok: true } : { ok: false, reason: 'this room is for its assigned jam team' };
    }
    const bal = balance(c.community_id, userId);
    if (bal >= c.min_balance) return { ok: true };
    const t = requireToken(c.community_id);
    return { ok: false, reason: `hold at least ${c.min_balance} ${t.symbol} to join (you have ${bal})` };
  }

  // ---------- shop ----------

  function addProduct(cid, actorId, { title, description = '', price, content, min_balance = 0, stock = null }) {
    requireToken(cid);
    requireAdmin(cid, actorId);
    const { lastInsertRowid } = q(`INSERT INTO products
      (community_id, seller_id, title, description, price, content, min_balance, stock, created_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`).run(cid, actorId, str(title, 'title', { max: 80 }),
      str(description, 'description', { min: 0, max: 1000 }), int(price, 'price', { min: 1 }),
      str(content, 'content', { max: 4000 }), int(min_balance, 'min_balance'),
      stock === null || stock === '' ? null : int(stock, 'stock'), now());
    return q('SELECT * FROM products WHERE id = ?').get(Number(lastInsertRowid));
  }

  function setProductActive(cid, actorId, productId, active) {
    requireAdmin(cid, actorId);
    q('UPDATE products SET active = ? WHERE id = ? AND community_id = ?').run(active ? 1 : 0, productId, cid);
  }

  /** Products as a given viewer sees them: content only if they own it. */
  function listProducts(cid, viewerId) {
    return q(`SELECT p.*, (SELECT COUNT(*) FROM purchases x WHERE x.product_id = p.id) AS sold,
        EXISTS(SELECT 1 FROM purchases x WHERE x.product_id = p.id AND x.buyer_id = ?) AS owned
      FROM products p WHERE p.community_id = ? AND (p.active = 1 OR p.seller_id = ?) ORDER BY p.id DESC`)
      .all(viewerId, cid, viewerId)
      .map((p) => ({ ...p, owned: !!p.owned, content: p.owned || p.seller_id === viewerId ? p.content : null }));
  }

  /**
   * Buys a digital product with the community token. The price is split:
   * burn_bps is destroyed, fee_bps goes to the treasury, the rest to the seller.
   */
  function buy(cid, buyerId, productId) {
    const token = requireToken(cid);
    return tx(db, () => {
      const p = q('SELECT * FROM products WHERE id = ? AND community_id = ?').get(productId, cid);
      if (!p || !p.active) fail(404, 'product not found');
      if (p.seller_id === buyerId) fail(400, 'you are the seller');
      if (q('SELECT 1 FROM purchases WHERE product_id = ? AND buyer_id = ?').get(productId, buyerId)) fail(409, 'already owned');
      if (p.stock !== null && p.stock <= 0) fail(409, 'sold out');
      const bal = balance(cid, buyerId);
      if (bal < p.min_balance) fail(403, `hold at least ${p.min_balance} ${token.symbol} to unlock this product`);
      if (bal < p.price) fail(402, `costs ${p.price} ${token.symbol}, you have ${bal}`);

      const burnAmt = Math.floor((p.price * token.burn_bps) / 10_000);
      const feeAmt = Math.floor((p.price * token.fee_bps) / 10_000);
      move(cid, buyerId, p.seller_id, p.price - burnAmt - feeAmt, 'purchase', p.title);
      move(cid, buyerId, TREASURY, feeAmt, 'fee', p.title);
      burn(cid, buyerId, burnAmt);
      if (p.stock !== null) q('UPDATE products SET stock = stock - 1 WHERE id = ?').run(p.id);
      q('INSERT INTO purchases (product_id, buyer_id, price, created_at) VALUES (?, ?, ?, ?)').run(p.id, buyerId, p.price, now());
      join(cid, buyerId);
      events.emit('purchase', { cid, buyerId, product: p, token });
      return { product: p, burned: burnAmt, fee: feeAmt };
    });
  }

  // ---------- governance ----------

  /**
   * Token-weighted proposal. Voting power is snapshotted at creation so
   * tokens can't be passed around to vote twice.
   */
  function createProposal(cid, actorId, { title, options, minutes = 1440 }) {
    requireToken(cid);
    requireAdmin(cid, actorId);
    title = str(title, 'title', { max: 200 });
    if (!Array.isArray(options)) fail(400, 'options must be a list');
    options = options.map((o) => str(o, 'option', { max: 80 }));
    if (options.length < 2 || options.length > 8) fail(400, 'give 2-8 options');
    minutes = int(minutes, 'minutes', { min: 1, max: 60 * 24 * 30 });
    return tx(db, () => {
      const { lastInsertRowid } = q(`INSERT INTO proposals (community_id, creator_id, title, options, ends_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?)`).run(cid, actorId, title, JSON.stringify(options), now() + minutes * 60_000, now());
      const id = Number(lastInsertRowid);
      q(`INSERT INTO proposal_snapshots (proposal_id, user_id, weight)
         SELECT ?, account_id, amount FROM balances WHERE community_id = ? AND account_id > 0 AND amount > 0`).run(id, cid);
      const prop = proposal(id);
      events.emit('proposal_created', { cid, proposal: prop });
      return prop;
    });
  }

  function proposal(id, viewerId = null) {
    const p = q('SELECT * FROM proposals WHERE id = ?').get(id);
    if (!p) fail(404, 'proposal not found');
    const options = JSON.parse(p.options);
    const tally = options.map(() => 0);
    for (const v of q('SELECT option_idx, SUM(weight) AS w FROM votes WHERE proposal_id = ? GROUP BY option_idx').all(id)) {
      tally[v.option_idx] = v.w;
    }
    const mine = viewerId ? q('SELECT option_idx FROM votes WHERE proposal_id = ? AND user_id = ?').get(id, viewerId) : null;
    const power = viewerId ? q('SELECT weight FROM proposal_snapshots WHERE proposal_id = ? AND user_id = ?').get(id, viewerId)?.weight ?? 0 : 0;
    return { ...p, options, tally, closed: !!p.closed || p.ends_at <= now(), my_vote: mine?.option_idx ?? null, my_power: power };
  }

  function listProposals(cid, viewerId) {
    return q('SELECT id FROM proposals WHERE community_id = ? ORDER BY id DESC LIMIT 50').all(cid).map((r) => proposal(r.id, viewerId));
  }

  function vote(proposalId, userId, optionIdx) {
    const p = proposal(proposalId);
    if (p.closed) fail(409, 'voting has ended');
    optionIdx = int(optionIdx, 'option', { max: p.options.length - 1 });
    const snap = q('SELECT weight FROM proposal_snapshots WHERE proposal_id = ? AND user_id = ?').get(proposalId, userId);
    if (!snap) fail(403, 'you held no tokens when this proposal opened');
    q(`INSERT INTO votes (proposal_id, user_id, option_idx, weight) VALUES (?, ?, ?, ?)
       ON CONFLICT(proposal_id, user_id) DO UPDATE SET option_idx = excluded.option_idx`).run(proposalId, userId, optionIdx, snap.weight);
    return proposal(proposalId, userId);
  }

  // ---------- build jams ----------

  /**
   * A timed build session. People join and pick a role, get split into
   * mixed-role rooms, build until the deadline, then everyone votes. The
   * prize is escrowed from the treasury up front and paid to the top rooms.
   */
  function createJam(cid, actorId, { title, theme = '', roles = ['builder', 'designer', 'storyteller'], room_size = 3, prize = 0, build_minutes = 60, vote_minutes = 30 }) {
    requireToken(cid);
    requireAdmin(cid, actorId);
    if (!Array.isArray(roles)) fail(400, 'roles must be a list');
    roles = [...new Set(roles.map((r) => str(r, 'role', { max: 24 }).toLowerCase()))];
    if (roles.length < 1 || roles.length > 8) fail(400, 'give 1-8 roles');
    prize = int(prize, 'prize');
    return tx(db, () => {
      move(cid, TREASURY, ESCROW, prize, 'jam_escrow');
      const { lastInsertRowid } = q(`INSERT INTO jams (community_id, title, theme, roles, room_size, prize, build_minutes, vote_minutes, phase, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'lobby', ?)`).run(cid, str(title, 'title', { max: 80 }), str(theme, 'theme', { min: 0, max: 500 }),
        JSON.stringify(roles), int(room_size, 'room_size', { min: 1, max: 20 }), prize,
        int(build_minutes, 'build_minutes', { min: 1, max: 60 * 24 * 7 }), int(vote_minutes, 'vote_minutes', { min: 1, max: 60 * 24 * 7 }), now());
      const j = jam(Number(lastInsertRowid));
      events.emit('jam_created', { cid, jam: j });
      return j;
    });
  }

  function jamRow(jamId) {
    const j = q('SELECT * FROM jams WHERE id = ?').get(jamId);
    if (!j) fail(404, 'jam not found');
    return { ...j, roles: JSON.parse(j.roles) };
  }

  function jam(jamId, viewerId = null) {
    const j = jamRow(jamId);
    const rooms = q('SELECT * FROM jam_rooms WHERE jam_id = ? ORDER BY id').all(jamId).map((r) => ({
      ...r,
      members: q(`SELECT p.user_id, p.role, u.username, u.first_name FROM jam_participants p
        JOIN users u ON u.id = p.user_id WHERE p.room_id = ? ORDER BY p.joined_at`).all(r.id),
      entry: q('SELECT * FROM jam_entries WHERE room_id = ?').get(r.id) ?? null,
      // Vote counts stay hidden until voting ends so they can't steer the vote.
      votes: j.phase === 'closed' ? q('SELECT COUNT(*) AS n FROM jam_votes WHERE room_id = ?').get(r.id).n : null,
      result: q('SELECT rank, payout_each FROM jam_results WHERE room_id = ?').get(r.id) ?? null,
    }));
    const participants = q('SELECT COUNT(*) AS n FROM jam_participants WHERE jam_id = ?').get(jamId).n;
    const me = viewerId ? q('SELECT role, room_id FROM jam_participants WHERE jam_id = ? AND user_id = ?').get(jamId, viewerId) ?? null : null;
    const myVote = viewerId ? q('SELECT room_id FROM jam_votes WHERE jam_id = ? AND voter_id = ?').get(jamId, viewerId)?.room_id ?? null : null;
    return { ...j, rooms, participants, me, my_vote: myVote, now: now() };
  }

  function listJams(cid, viewerId) {
    return q('SELECT id FROM jams WHERE community_id = ? ORDER BY id DESC LIMIT 20').all(cid).map((r) => jam(r.id, viewerId));
  }

  function joinJam(jamId, userId, role = 'any') {
    const j = jamRow(jamId);
    if (!['lobby', 'building'].includes(j.phase)) fail(409, 'this jam is no longer open');
    if (q('SELECT 1 FROM jam_participants WHERE jam_id = ? AND user_id = ?').get(jamId, userId)) fail(409, 'already in this jam');
    role = String(role || 'any').toLowerCase();
    if (role === 'any') {
      // Fill the scarcest role so rooms stay balanced.
      const counts = Object.fromEntries(j.roles.map((r) => [r, 0]));
      for (const r of q('SELECT role, COUNT(*) AS n FROM jam_participants WHERE jam_id = ? GROUP BY role').all(jamId)) counts[r.role] = r.n;
      role = j.roles.reduce((a, b) => (counts[b] < counts[a] ? b : a));
    } else if (!j.roles.includes(role)) {
      fail(400, `role must be one of: ${j.roles.join(', ')}`);
    }
    return tx(db, () => {
      join(j.community_id, userId);
      q('INSERT INTO jam_participants (jam_id, user_id, role, joined_at) VALUES (?, ?, ?, ?)').run(jamId, userId, role, now());
      // Late joiners go straight into the room that needs them most.
      if (j.phase === 'building') placeLateJoiner(j, userId, role);
      return jam(jamId, userId);
    });
  }

  function leaveJam(jamId, userId) {
    const j = jamRow(jamId);
    if (j.phase !== 'lobby') fail(409, 'you can only leave before building starts');
    q('DELETE FROM jam_participants WHERE jam_id = ? AND user_id = ?').run(jamId, userId);
  }

  function freeRoomChats(cid, jamId) {
    return q(`SELECT chat_id, title FROM chats c WHERE c.community_id = ? AND c.kind = 'room' AND NOT EXISTS (
        SELECT 1 FROM jam_rooms r JOIN jams j ON j.id = r.jam_id
        WHERE r.chat_id = c.chat_id AND j.phase != 'closed' AND j.id != ?) ORDER BY chat_id`).all(cid, jamId);
  }

  /**
   * Splits participants into rooms of ~room_size, dealing each role out
   * round-robin so every room gets a mix. Linked Telegram groups become the
   * rooms' chats; rooms without one use the in-app room board.
   */
  function assignRooms(j) {
    const people = q('SELECT user_id, role FROM jam_participants WHERE jam_id = ? ORDER BY joined_at, user_id').all(j.id);
    const nRooms = Math.max(1, Math.ceil(people.length / j.room_size));
    const chats = freeRoomChats(j.community_id, j.id);
    const rooms = [];
    for (let i = 0; i < nRooms; i++) {
      const c = chats[i];
      const { lastInsertRowid } = q('INSERT INTO jam_rooms (jam_id, name, chat_id) VALUES (?, ?, ?)')
        .run(j.id, c?.title || `Room ${i + 1}`, c?.chat_id ?? null);
      rooms.push(Number(lastInsertRowid));
    }
    const byRole = [...j.roles, ...new Set(people.map((p) => p.role))]
      .filter((r, i, a) => a.indexOf(r) === i)
      .flatMap((r) => people.filter((p) => p.role === r));
    byRole.forEach((p, i) => {
      q('UPDATE jam_participants SET room_id = ? WHERE jam_id = ? AND user_id = ?').run(rooms[i % nRooms], j.id, p.user_id);
    });
  }

  function placeLateJoiner(j, userId, role) {
    const room = q(`SELECT r.id,
        (SELECT COUNT(*) FROM jam_participants p WHERE p.room_id = r.id) AS n,
        (SELECT COUNT(*) FROM jam_participants p WHERE p.room_id = r.id AND p.role = ?) AS same
      FROM jam_rooms r WHERE r.jam_id = ? ORDER BY same, n, r.id LIMIT 1`).get(role, j.id);
    let roomId = room?.id;
    if (!room || room.n >= j.room_size) {
      const { lastInsertRowid } = q('INSERT INTO jam_rooms (jam_id, name) VALUES (?, ?)').run(j.id, `Room ${(q('SELECT COUNT(*) AS n FROM jam_rooms WHERE jam_id = ?').get(j.id).n) + 1}`);
      roomId = Number(lastInsertRowid);
    }
    q('UPDATE jam_participants SET room_id = ? WHERE jam_id = ? AND user_id = ?').run(roomId, j.id, userId);
    events.emit('room_assigned', { jam: jam(j.id), userId, roomId });
  }

  function startJam(jamId, actorId) {
    const j = jamRow(jamId);
    requireAdmin(j.community_id, actorId);
    if (j.phase !== 'lobby') fail(409, 'jam already started');
    if (!q('SELECT 1 FROM jam_participants WHERE jam_id = ?').get(jamId)) fail(409, 'nobody has joined yet');
    return tx(db, () => {
      assignRooms(j);
      q("UPDATE jams SET phase = 'building', build_ends_at = ? WHERE id = ?").run(now() + j.build_minutes * 60_000, jamId);
      const out = jam(jamId);
      events.emit('jam_started', { jam: out });
      return out;
    });
  }

  function myRoom(jamId, userId) {
    const p = q('SELECT room_id FROM jam_participants WHERE jam_id = ? AND user_id = ?').get(jamId, userId);
    if (!p?.room_id) fail(403, 'you are not in a room for this jam');
    return p.room_id;
  }

  function submitEntry(jamId, userId, { title, url = '', description = '' }) {
    const j = jamRow(jamId);
    if (j.phase !== 'building') fail(409, 'submissions are closed');
    const roomId = myRoom(jamId, userId);
    title = str(title, 'title', { max: 80 });
    url = str(url, 'url', { min: 0, max: 500 });
    if (url && !/^https?:\/\//i.test(url)) fail(400, 'url must start with http(s)://');
    q(`INSERT INTO jam_entries (room_id, jam_id, title, url, description, submitted_by, submitted_at) VALUES (?, ?, ?, ?, ?, ?, ?)
       ON CONFLICT(room_id) DO UPDATE SET title = excluded.title, url = excluded.url, description = excluded.description,
         submitted_by = excluded.submitted_by, submitted_at = excluded.submitted_at`)
      .run(roomId, jamId, title, url, str(description, 'description', { min: 0, max: 1000 }), userId, now());
    return jam(jamId, userId);
  }

  function voteJam(jamId, voterId, roomId) {
    const j = jamRow(jamId);
    if (j.phase !== 'voting') fail(409, 'voting is not open');
    if (!q('SELECT 1 FROM members WHERE community_id = ? AND user_id = ?').get(j.community_id, voterId)) fail(403, 'join the community to vote');
    if (!q('SELECT 1 FROM jam_entries WHERE room_id = ? AND jam_id = ?').get(roomId, jamId)) fail(404, 'that room has no entry');
    const mine = q('SELECT room_id FROM jam_participants WHERE jam_id = ? AND user_id = ?').get(jamId, voterId);
    if (mine?.room_id === roomId) fail(403, 'you cannot vote for your own room');
    q(`INSERT INTO jam_votes (jam_id, voter_id, room_id) VALUES (?, ?, ?)
       ON CONFLICT(jam_id, voter_id) DO UPDATE SET room_id = excluded.room_id`).run(jamId, voterId, roomId);
    return jam(jamId, voterId);
  }

  function closeJam(j) {
    const ranked = q(`SELECT e.room_id, e.submitted_at, (SELECT COUNT(*) FROM jam_votes v WHERE v.room_id = e.room_id) AS votes
      FROM jam_entries e WHERE e.jam_id = ? ORDER BY votes DESC, e.submitted_at ASC`).all(j.id);
    const winners = ranked.slice(0, PRIZE_SPLIT.length);
    const splitTotal = PRIZE_SPLIT.slice(0, winners.length).reduce((a, b) => a + b, 0);
    let paid = 0;
    ranked.forEach((r, i) => {
      const members = q('SELECT user_id FROM jam_participants WHERE room_id = ?').all(r.room_id);
      const roomShare = i < winners.length ? Math.floor((j.prize * PRIZE_SPLIT[i]) / splitTotal) : 0;
      const each = members.length ? Math.floor(roomShare / members.length) : 0;
      for (const m of members) {
        move(j.community_id, ESCROW, m.user_id, each, 'jam_prize', j.title);
        paid += each;
      }
      q('INSERT INTO jam_results (jam_id, room_id, rank, votes, payout_each) VALUES (?, ?, ?, ?, ?)').run(j.id, r.room_id, i + 1, r.votes, each);
    });
    // Rounding dust and unclaimed prizes go back to the treasury.
    move(j.community_id, ESCROW, TREASURY, j.prize - paid, 'jam_refund', j.title);
    q("UPDATE jams SET phase = 'closed' WHERE id = ?").run(j.id);
  }

  /** Advances every jam whose deadline has passed. Call on a timer. */
  function tick() {
    const t = now();
    for (const { id } of q("SELECT id FROM jams WHERE phase = 'building' AND build_ends_at <= ?").all(t)) {
      tx(db, () => {
        const j = jamRow(id);
        const entries = q('SELECT COUNT(*) AS n FROM jam_entries WHERE jam_id = ?').get(id).n;
        if (entries === 0) {
          closeJam(j);
        } else {
          q("UPDATE jams SET phase = 'voting', vote_ends_at = ? WHERE id = ?").run(t + j.vote_minutes * 60_000, id);
        }
      });
      const j = jam(id);
      events.emit(j.phase === 'voting' ? 'jam_voting' : 'jam_closed', { jam: j });
    }
    for (const { id } of q("SELECT id FROM jams WHERE phase = 'voting' AND vote_ends_at <= ?").all(t)) {
      tx(db, () => closeJam(jamRow(id)));
      events.emit('jam_closed', { jam: jam(id) });
    }
    for (const p of q('SELECT id FROM proposals WHERE closed = 0 AND ends_at <= ?').all(t)) {
      q('UPDATE proposals SET closed = 1 WHERE id = ?').run(p.id);
      events.emit('proposal_closed', { proposal: proposal(p.id) });
    }
  }

  function roomMessages(jamId, userId, afterId = 0) {
    const roomId = myRoom(jamId, userId);
    return q(`SELECT m.id, m.user_id, m.text, m.created_at, u.username, u.first_name FROM room_messages m
      JOIN users u ON u.id = m.user_id WHERE m.room_id = ? AND m.id > ? ORDER BY m.id LIMIT 200`).all(roomId, afterId);
  }

  function postRoomMessage(jamId, userId, text) {
    const roomId = myRoom(jamId, userId);
    if (jamRow(jamId).phase === 'closed') fail(409, 'this jam is over');
    q('INSERT INTO room_messages (room_id, user_id, text, created_at) VALUES (?, ?, ?, ?)').run(roomId, userId, str(text, 'message', { max: 1000 }), now());
  }

  // ---------- overview ----------

  function overview(cid, viewerId) {
    const c = community(cid);
    const token = q('SELECT * FROM tokens WHERE community_id = ?').get(cid) ?? null;
    const m = q('SELECT airdropped FROM members WHERE community_id = ? AND user_id = ?').get(cid, viewerId);
    const holders = q(`SELECT b.account_id AS user_id, b.amount, u.username, u.first_name FROM balances b
      JOIN users u ON u.id = b.account_id WHERE b.community_id = ? AND b.account_id > 0 AND b.amount > 0
      ORDER BY b.amount DESC LIMIT 10`).all(cid);
    return {
      community: c,
      token,
      treasury: balance(cid, TREASURY),
      escrow: balance(cid, ESCROW),
      members: q('SELECT COUNT(*) AS n FROM members WHERE community_id = ?').get(cid).n,
      chat: mainChat(cid),
      holders,
      me: {
        id: viewerId,
        balance: balance(cid, viewerId),
        is_member: !!m,
        can_claim: !!token?.airdrop_amount && !m?.airdropped,
        is_admin: isAdmin(cid, viewerId),
      },
      activity: q(`SELECT l.kind, l.amount, l.memo, l.created_at, l.from_id, l.to_id FROM ledger l
        WHERE l.community_id = ? AND (l.from_id = ? OR l.to_id = ?) ORDER BY l.id DESC LIMIT 20`).all(cid, viewerId, viewerId),
    };
  }

  return {
    events, upsertUser, findUser, community, createCommunity, addAdmin, isAdmin, listCommunities,
    launchToken, balance, transfer, reward, join, claimAirdrop,
    linkChat, chat, mainChat, canEnterChat,
    addProduct, setProductActive, listProducts, buy,
    createProposal, proposal, listProposals, vote,
    createJam, jam, listJams, joinJam, leaveJam, startJam, submitEntry, voteJam, tick,
    roomMessages, postRoomMessage, overview,
  };
}
