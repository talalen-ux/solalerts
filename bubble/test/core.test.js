import { test } from 'node:test';
import assert from 'node:assert/strict';
import { openDb, TREASURY, ESCROW } from '../src/db.js';
import { createCore } from '../src/core.js';
import { verifyInitData, signInitData } from '../src/auth.js';

function setup() {
  let t = 1_000_000;
  const clock = { now: () => t, advance: (min) => { t += min * 60_000; } };
  const core = createCore(openDb(), clock);
  const users = {};
  for (const [id, n] of [[1, 'owner'], [2, 'ann'], [3, 'bob'], [4, 'cat'], [5, 'dan'], [6, 'eve'], [7, 'fay']]) {
    users[n] = core.upsertUser({ id, username: n, first_name: n }).id;
  }
  const c = core.createCommunity(users.owner, { slug: 'pixel', name: 'Pixel Club' });
  core.launchToken(c.id, users.owner, { symbol: 'pix', name: 'Pixel', supply: 1_000_000, creator_pct: 10, airdrop_amount: 1000, fee_bps: 500, burn_bps: 100 });
  return { core, clock, cid: c.id, u: users };
}

const totalHeld = (core, cid) => [TREASURY, ESCROW, 1, 2, 3, 4, 5, 6, 7].reduce((s, id) => s + core.balance(cid, id), 0);

test('launch splits supply between creator and treasury', () => {
  const { core, cid, u } = setup();
  assert.equal(core.balance(cid, u.owner), 100_000);
  assert.equal(core.balance(cid, TREASURY), 900_000);
  assert.throws(() => core.launchToken(cid, u.owner, { symbol: 'X', name: 'x', supply: 5000 }), /already launched/);
});

test('only admins launch; symbols are unique', () => {
  const { core, u } = setup();
  const c2 = core.createCommunity(u.ann, { slug: 'other', name: 'Other' });
  assert.throws(() => core.launchToken(c2.id, u.bob, { symbol: 'ABC', name: 'a', supply: 5000 }), /admins only/);
  assert.throws(() => core.launchToken(c2.id, u.ann, { symbol: 'PIX', name: 'a', supply: 5000 }), /symbol already taken/);
});

test('airdrop can be claimed once', () => {
  const { core, cid, u } = setup();
  assert.equal(core.claimAirdrop(cid, u.ann), 1000);
  assert.throws(() => core.claimAirdrop(cid, u.ann), /already claimed/);
  assert.equal(core.balance(cid, u.ann), 1000);
});

test('purchase splits seller / fee / burn and unlocks content', () => {
  const { core, cid, u } = setup();
  core.claimAirdrop(cid, u.ann);
  const p = core.addProduct(cid, u.owner, { title: 'Brush pack', price: 1000, content: 'https://example.com/secret.zip' });
  assert.equal(core.listProducts(cid, u.ann)[0].content, null);
  const res = core.buy(cid, u.ann, p.id);
  assert.deepEqual([res.burned, res.fee], [10, 50]);
  assert.equal(core.balance(cid, u.ann), 0);
  assert.equal(core.balance(cid, u.owner), 100_000 + 940);
  assert.equal(core.overview(cid, u.ann).token.supply, 1_000_000 - 10);
  assert.equal(core.listProducts(cid, u.ann)[0].content, 'https://example.com/secret.zip');
  assert.throws(() => core.buy(cid, u.ann, p.id), /already owned/);
  assert.equal(totalHeld(core, cid), 1_000_000 - 10);
});

test('purchase fails cleanly without funds and respects holder gate and stock', () => {
  const { core, cid, u } = setup();
  const gated = core.addProduct(cid, u.owner, { title: 'VIP', price: 10, content: 'x', min_balance: 5000 });
  core.claimAirdrop(cid, u.bob);
  assert.throws(() => core.buy(cid, u.bob, gated.id), /hold at least 5000/);
  const pricey = core.addProduct(cid, u.owner, { title: 'Big', price: 5000, content: 'x' });
  assert.throws(() => core.buy(cid, u.bob, pricey.id), /costs 5000/);
  assert.equal(core.balance(cid, u.bob), 1000);
  const limited = core.addProduct(cid, u.owner, { title: 'One', price: 1, content: 'x', stock: 1 });
  core.buy(cid, u.bob, limited.id);
  core.claimAirdrop(cid, u.cat);
  assert.throws(() => core.buy(cid, u.cat, limited.id), /sold out/);
});

test('chat gate checks balance', () => {
  const { core, cid, u } = setup();
  core.linkChat(cid, u.owner, { chat_id: -100, kind: 'main', min_balance: 500 });
  assert.equal(core.canEnterChat(-100, u.ann).ok, false);
  core.claimAirdrop(cid, u.ann);
  assert.equal(core.canEnterChat(-100, u.ann).ok, true);
  assert.equal(core.canEnterChat(-999, u.ann).ok, false);
});

test('proposal votes use the snapshot taken at creation', () => {
  const { core, cid, u, clock } = setup();
  core.claimAirdrop(cid, u.ann);
  const p = core.createProposal(cid, u.owner, { title: 'Next drop?', options: ['Fonts', 'Icons'], minutes: 10 });
  core.vote(p.id, u.ann, 1);
  core.transfer(cid, u.ann, u.bob, 1000);
  assert.throws(() => core.vote(p.id, u.bob, 0), /held no tokens/);
  core.vote(p.id, u.owner, 0);
  assert.deepEqual(core.proposal(p.id).tally, [100_000, 1000]);
  clock.advance(11);
  core.tick();
  assert.throws(() => core.vote(p.id, u.ann, 0), /ended/);
});

test('jam: roles balance, mixed rooms, timed phases, prize payout', () => {
  const { core, cid, u, clock } = setup();
  const before = core.balance(cid, TREASURY);
  const jam = core.createJam(cid, u.owner, { title: 'Ship it', roles: ['dev', 'design'], room_size: 2, prize: 1000, build_minutes: 30, vote_minutes: 10 });
  assert.equal(core.balance(cid, TREASURY), before - 1000);
  assert.equal(core.balance(cid, ESCROW), 1000);

  for (const n of ['ann', 'bob', 'cat', 'dan']) core.joinJam(jam.id, u[n]);
  const roles = core.jam(jam.id).participants;
  assert.equal(roles, 4);
  assert.throws(() => core.joinJam(jam.id, u.ann), /already/);
  assert.throws(() => core.submitEntry(jam.id, u.ann, { title: 'x' }), /closed/);

  const started = core.startJam(jam.id, u.owner);
  assert.equal(started.phase, 'building');
  assert.equal(started.rooms.length, 2);
  for (const r of started.rooms) {
    assert.deepEqual(r.members.map((m) => m.role).sort(), ['design', 'dev'], 'each room gets one of each role');
  }

  // Late joiner lands in a room.
  core.joinJam(jam.id, u.eve, 'dev');
  assert.ok(core.jam(jam.id, u.eve).me.room_id);

  const [r1, r2] = started.rooms;
  const a = r1.members[0].user_id;
  const b = r2.members[0].user_id;
  core.postRoomMessage(jam.id, a, 'hello team');
  assert.equal(core.roomMessages(jam.id, r1.members[1].user_id)[0].text, 'hello team');
  assert.throws(() => core.roomMessages(jam.id, u.fay), /not in a room/);

  core.submitEntry(jam.id, a, { title: 'Alpha', url: 'https://a.example' });
  core.submitEntry(jam.id, b, { title: 'Beta' });
  assert.throws(() => core.submitEntry(jam.id, a, { title: 'x', url: 'javascript:alert(1)' }), /http/);

  clock.advance(31);
  core.tick();
  assert.equal(core.jam(jam.id).phase, 'voting');
  assert.throws(() => core.voteJam(jam.id, a, r1.id), /own room/);
  core.voteJam(jam.id, a, r2.id);
  core.voteJam(jam.id, b, r1.id);
  assert.throws(() => core.voteJam(jam.id, u.fay, r1.id), /join the community/);
  core.join(cid, u.fay);
  core.voteJam(jam.id, u.fay, r2.id);
  assert.equal(core.jam(jam.id).rooms[0].votes, null, 'votes hidden while voting');

  clock.advance(11);
  core.tick();
  const done = core.jam(jam.id);
  assert.equal(done.phase, 'closed');
  const winner = done.rooms.find((r) => r.id === r2.id);
  const second = done.rooms.find((r) => r.id === r1.id);
  assert.equal(winner.result.rank, 1);
  // 2 winning rooms → split 50:30 renormalised to 625 / 375
  assert.equal(winner.result.payout_each, Math.floor(625 / winner.members.length));
  assert.equal(second.result.payout_each, Math.floor(375 / second.members.length));
  assert.equal(core.balance(cid, ESCROW), 0);
  assert.equal(totalHeld(core, cid), 1_000_000);
});

test('jam with no entries refunds the prize', () => {
  const { core, cid, u, clock } = setup();
  const jam = core.createJam(cid, u.owner, { title: 'Empty', prize: 500, build_minutes: 5 });
  core.joinJam(jam.id, u.ann);
  core.startJam(jam.id, u.owner);
  const before = core.balance(cid, TREASURY);
  clock.advance(6);
  core.tick();
  assert.equal(core.jam(jam.id).phase, 'closed');
  assert.equal(core.balance(cid, TREASURY), before + 500);
});

test('jam room chats are only open to the assigned team', () => {
  const { core, cid, u } = setup();
  core.linkChat(cid, u.owner, { chat_id: -200, kind: 'room', title: 'Room A' });
  const jam = core.createJam(cid, u.owner, { title: 'J', room_size: 5 });
  core.joinJam(jam.id, u.ann);
  core.startJam(jam.id, u.owner);
  assert.equal(core.jam(jam.id).rooms[0].chat_id, -200);
  assert.equal(core.canEnterChat(-200, u.ann).ok, true);
  assert.equal(core.canEnterChat(-200, u.bob).ok, false);
});

test('initData signature is verified', () => {
  const data = signInitData({ id: 42, first_name: 'Z' }, 'TOKEN');
  assert.equal(verifyInitData(data, 'TOKEN').id, 42);
  assert.equal(verifyInitData(data, 'OTHER'), null);
  assert.equal(verifyInitData(data.replace('42', '43'), 'TOKEN'), null);
  const old = signInitData({ id: 42 }, 'TOKEN', 1000);
  assert.equal(verifyInitData(old, 'TOKEN'), null);
});
