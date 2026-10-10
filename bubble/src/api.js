import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';
import { verifyInitData } from './auth.js';
import { BubbleError } from './core.js';

const PUBLIC_DIR = fileURLToPath(new URL('../public/', import.meta.url));
const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml' };

/**
 * JSON API for the Mini App. Every /api call must carry Telegram initData
 * in the Authorization header ("tma <initData>"); in dev mode an
 * "x-dev-user: <id>:<name>" header is accepted instead.
 */
export function createApi(core, { botToken, dev = false }) {
  const routes = [];
  const route = (method, pattern, handler) => {
    const keys = [];
    const re = new RegExp('^' + pattern.replace(/:(\w+)/g, (_, k) => (keys.push(k), '([^/]+)')) + '$');
    routes.push({ method, re, keys, handler });
  };
  const cid = (slug) => core.community(slug).id;

  route('GET', '/api/me', ({ user }) => ({ user, communities: core.listCommunities() }));
  route('GET', '/api/communities', () => core.listCommunities());
  route('POST', '/api/communities', ({ user, body }) => core.createCommunity(user.id, body));

  route('GET', '/api/c/:slug', ({ user, p }) => core.overview(cid(p.slug), user.id));
  route('POST', '/api/c/:slug/launch', ({ user, p, body }) => core.launchToken(cid(p.slug), user.id, body));
  route('POST', '/api/c/:slug/join', ({ user, p }) => (core.join(cid(p.slug), user.id), { ok: true }));
  route('POST', '/api/c/:slug/claim', ({ user, p }) => ({ amount: core.claimAirdrop(cid(p.slug), user.id) }));
  route('POST', '/api/c/:slug/transfer', ({ user, p, body }) =>
    (core.transfer(cid(p.slug), user.id, core.findUser(body.to).id, body.amount, body.memo), { ok: true }));
  route('POST', '/api/c/:slug/reward', ({ user, p, body }) =>
    (core.reward(cid(p.slug), user.id, core.findUser(body.to).id, body.amount, body.reason), { ok: true }));
  route('POST', '/api/c/:slug/admins', ({ user, p, body }) =>
    (core.addAdmin(cid(p.slug), user.id, core.findUser(body.user).id), { ok: true }));
  route('POST', '/api/c/:slug/gate', ({ user, p, body }) => {
    const c = cid(p.slug);
    const chat = core.mainChat(c);
    if (!chat) throw new BubbleError(409, 'link a Telegram group first: add the bot to it and send /link ' + p.slug);
    return core.linkChat(c, user.id, { ...chat, min_balance: body.min_balance });
  });

  route('GET', '/api/c/:slug/products', ({ user, p }) => core.listProducts(cid(p.slug), user.id));
  route('POST', '/api/c/:slug/products', ({ user, p, body }) => core.addProduct(cid(p.slug), user.id, body));
  route('POST', '/api/c/:slug/products/:id/buy', ({ user, p }) => core.buy(cid(p.slug), user.id, Number(p.id)));
  route('POST', '/api/c/:slug/products/:id/active', ({ user, p, body }) =>
    (core.setProductActive(cid(p.slug), user.id, Number(p.id), !!body.active), { ok: true }));

  route('GET', '/api/c/:slug/proposals', ({ user, p }) => core.listProposals(cid(p.slug), user.id));
  route('POST', '/api/c/:slug/proposals', ({ user, p, body }) => core.createProposal(cid(p.slug), user.id, body));
  route('POST', '/api/proposals/:id/vote', ({ user, p, body }) => core.vote(Number(p.id), user.id, body.option));

  route('GET', '/api/c/:slug/jams', ({ user, p }) => core.listJams(cid(p.slug), user.id));
  route('POST', '/api/c/:slug/jams', ({ user, p, body }) => core.createJam(cid(p.slug), user.id, body));
  route('GET', '/api/jams/:id', ({ user, p }) => core.jam(Number(p.id), user.id));
  route('POST', '/api/jams/:id/join', ({ user, p, body }) => core.joinJam(Number(p.id), user.id, body.role));
  route('POST', '/api/jams/:id/leave', ({ user, p }) => (core.leaveJam(Number(p.id), user.id), { ok: true }));
  route('POST', '/api/jams/:id/start', ({ user, p }) => core.startJam(Number(p.id), user.id));
  route('POST', '/api/jams/:id/submit', ({ user, p, body }) => core.submitEntry(Number(p.id), user.id, body));
  route('POST', '/api/jams/:id/vote', ({ user, p, body }) => core.voteJam(Number(p.id), user.id, Number(body.room_id)));
  route('GET', '/api/jams/:id/messages', ({ user, p, query }) => core.roomMessages(Number(p.id), user.id, Number(query.get('after') || 0)));
  route('POST', '/api/jams/:id/messages', ({ user, p, body }) => (core.postRoomMessage(Number(p.id), user.id, body.text), { ok: true }));

  function authenticate(req) {
    const auth = req.headers.authorization || '';
    if (auth.startsWith('tma ')) {
      const tgUser = verifyInitData(auth.slice(4), botToken);
      if (tgUser) return core.upsertUser(tgUser);
    }
    if (dev && req.headers['x-dev-user']) {
      const [id, name = 'dev'] = String(req.headers['x-dev-user']).split(':');
      if (/^\d+$/.test(id)) return core.upsertUser({ id: Number(id), username: name, first_name: name });
    }
    return null;
  }

  async function readBody(req) {
    let raw = '';
    for await (const chunk of req) {
      raw += chunk;
      if (raw.length > 64_000) throw new BubbleError(413, 'body too large');
    }
    if (!raw) return {};
    try {
      return JSON.parse(raw);
    } catch {
      throw new BubbleError(400, 'invalid JSON');
    }
  }

  async function serveStatic(pathname, res) {
    const rel = pathname === '/' ? 'index.html' : pathname.slice(1);
    const file = normalize(join(PUBLIC_DIR, rel));
    if (!file.startsWith(PUBLIC_DIR)) return send(res, 404, { error: 'not found' });
    try {
      const data = await readFile(file);
      res.writeHead(200, { 'content-type': MIME[extname(file)] || 'application/octet-stream' });
      res.end(data);
    } catch {
      send(res, 404, { error: 'not found' });
    }
  }

  function send(res, status, payload) {
    res.writeHead(status, { 'content-type': 'application/json' });
    res.end(JSON.stringify(payload));
  }

  async function handle(req, res) {
    const url = new URL(req.url, 'http://local');
    if (!url.pathname.startsWith('/api/')) {
      if (req.method !== 'GET') return send(res, 405, { error: 'method not allowed' });
      return serveStatic(url.pathname, res);
    }
    try {
      const user = authenticate(req);
      if (!user) return send(res, 401, { error: 'open bubble from Telegram' });
      for (const r of routes) {
        if (r.method !== req.method) continue;
        const m = url.pathname.match(r.re);
        if (!m) continue;
        const p = Object.fromEntries(r.keys.map((k, i) => [k, decodeURIComponent(m[i + 1])]));
        const body = req.method === 'POST' ? await readBody(req) : {};
        core.tick();
        return send(res, 200, (await r.handler({ user, p, body, query: url.searchParams })) ?? { ok: true });
      }
      send(res, 404, { error: 'no such endpoint' });
    } catch (err) {
      if (err instanceof BubbleError) return send(res, err.status, { error: err.message });
      console.error(err);
      send(res, 500, { error: 'internal error' });
    }
  }

  return { handle, server: () => createServer(handle) };
}
