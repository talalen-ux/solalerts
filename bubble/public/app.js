const tg = window.Telegram?.WebApp;
const inTelegram = !!tg?.initData;
if (inTelegram) {
  tg.ready();
  tg.expand();
  document.documentElement.dataset.tg = '1';
}

// ---------- tiny helpers ----------

const $ = (s, el = document) => el.querySelector(s);
const view = $('#view');
class Raw { constructor(s) { this.s = s; } }
const raw = (s) => new Raw(s);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
// Auto-escaping template: interpolations are escaped unless wrapped in raw() or are arrays of html.
function html(strings, ...vals) {
  return raw(strings.reduce((out, s, i) => {
    if (i === 0) return s;
    const v = vals[i - 1];
    const str = v instanceof Raw ? v.s : Array.isArray(v) ? v.map((x) => (x instanceof Raw ? x.s : esc(x))).join('') : esc(v);
    return out + str + s;
  }, ''));
}
const render = (r) => { view.innerHTML = r.s; };
const fmt = (n) => Number(n ?? 0).toLocaleString();
const who = (u) => (u?.username ? '@' + u.username : u?.first_name || `user ${u?.user_id ?? u?.id}`);
const ago = (ms) => {
  const s = Math.max(0, Math.round(ms / 1000));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  return h ? `${h}h ${String(m).padStart(2, '0')}m` : `${m}:${String(r).padStart(2, '0')}`;
};

function toast(msg, err = false) {
  const t = $('#toast');
  t.textContent = msg;
  t.className = err ? 'err' : '';
  t.hidden = false;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => (t.hidden = true), 2600);
  tg?.HapticFeedback?.notificationOccurred(err ? 'error' : 'success');
}

function devUser() {
  let u = localStorage.getItem('bubble-dev-user');
  if (!u) {
    u = prompt('Dev mode: enter "<id>:<name>" to act as a test user', `${Math.floor(Math.random() * 1e6)}:tester`) || '1:tester';
    localStorage.setItem('bubble-dev-user', u);
  }
  return u;
}

async function api(path, body) {
  const headers = { 'content-type': 'application/json' };
  if (inTelegram) headers.authorization = 'tma ' + tg.initData;
  else headers['x-dev-user'] = devUser();
  const res = await fetch('/api' + path, { method: body ? 'POST' : 'GET', headers, body: body ? JSON.stringify(body) : undefined });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `request failed (${res.status})`);
  return data;
}

// Wires every <form data-action> to a handler that receives its fields.
function bindForms(handlers) {
  for (const form of view.querySelectorAll('form[data-action]')) {
    form.onsubmit = async (e) => {
      e.preventDefault();
      const btn = form.querySelector('button[type=submit]');
      btn && (btn.disabled = true);
      try {
        await handlers[form.dataset.action](Object.fromEntries(new FormData(form)), form);
      } catch (err) {
        toast(err.message, true);
      } finally {
        btn && (btn.disabled = false);
      }
    };
  }
}

function bindClicks(handlers) {
  for (const el of view.querySelectorAll('[data-click]')) {
    el.onclick = async () => {
      el.disabled = true;
      try {
        await handlers[el.dataset.click](el.dataset);
      } catch (err) {
        toast(err.message, true);
      } finally {
        el.disabled = false;
      }
    };
  }
}

// ---------- state & routing ----------

const state = { me: null, slug: null, tab: 'token', ov: null, jamId: null, timers: [] };
const clearTimers = () => { state.timers.forEach(clearInterval); state.timers = []; };

function initialSlug() {
  return tg?.initDataUnsafe?.start_param || new URLSearchParams(location.search).get('c') || null;
}

$('#back').onclick = () => {
  if (state.jamId) { state.jamId = null; return show(); }
  state.slug = null;
  show();
};
for (const b of document.querySelectorAll('#tabs button')) {
  b.onclick = () => { state.tab = b.dataset.tab; state.jamId = null; show(); };
}

async function show() {
  clearTimers();
  $('#back').hidden = !state.slug;
  $('#tabs').hidden = !state.slug;
  if (!state.slug) return home();
  try {
    state.ov = await api(`/c/${state.slug}`);
  } catch (err) {
    toast(err.message, true);
    state.slug = null;
    return home();
  }
  const { community, token, me } = state.ov;
  $('#title').textContent = token ? `${community.name} · $${token.symbol}` : community.name;
  $('#admin-tab').hidden = !me.is_admin;
  if (!token && me.is_admin && state.tab !== 'admin') state.tab = 'admin';
  for (const b of document.querySelectorAll('#tabs button')) b.classList.toggle('on', b.dataset.tab === state.tab);
  if (!token && state.tab !== 'admin') {
    return render(html`<div class="card"><h3>No token yet</h3><p class="muted">The admins of ${community.name} haven't launched their token. Check back soon.</p></div>`);
  }
  const pages = { token: tokenPage, shop: shopPage, jams: jamsPage, vote: votePage, admin: adminPage };
  await pages[state.tab]();
}

const open = (slug) => { state.slug = slug; state.tab = 'token'; state.jamId = null; show(); };

// ---------- home ----------

async function home() {
  $('#title').textContent = '🫧 bubble';
  const list = await api('/communities').catch((e) => (toast(e.message, true), []));
  render(html`
    <div class="card">
      <h3>Communities</h3>
      <p class="muted">Each one runs on its own token: it buys products, unlocks chats, pays rewards and decides votes.</p>
      <div class="list">${list.length ? list.map((c) => html`
        <div><span><b>${c.name}</b> ${c.symbol ? html`<span class="pill">$${c.symbol}</span>` : ''}<br><span class="muted">${fmt(c.members)} members</span></span>
        <button class="soft" data-click="open" data-slug="${c.slug}">Open</button></div>`) : html`<div class="muted">None yet. Start the first one.</div>`}
      </div>
    </div>
    <details class="card"><summary>Start a community</summary>
      <form data-action="create">
        <label>Name</label><input name="name" required maxlength="64" placeholder="Pixel Club">
        <label>Handle (used in links)</label><input name="slug" required minlength="3" maxlength="32" pattern="[a-z0-9]+(-[a-z0-9]+)*" placeholder="pixel-club">
        <label>What is it about?</label><textarea name="description" maxlength="500"></textarea>
        <button type="submit">Create</button>
      </form>
    </details>`);
  bindClicks({ open: (d) => open(d.slug) });
  bindForms({
    create: async (f) => {
      const c = await api('/communities', f);
      toast('Community created. Now launch its token.');
      state.slug = c.slug;
      state.tab = 'admin';
      show();
    },
  });
}

// ---------- token ----------

function tokenPage() {
  const { token, me, treasury, members, holders, activity, chat, community } = state.ov;
  const sign = (a) => (a.to_id === me.id ? '+' : '−');
  render(html`
    <div class="card">
      <div class="muted">Your balance</div>
      <div class="big">${fmt(me.balance)} <span class="muted">$${token.symbol}</span></div>
      ${me.can_claim ? html`<button data-click="claim">🎁 Claim ${fmt(token.airdrop_amount)} $${token.symbol} welcome airdrop</button>` : ''}
    </div>
    <div class="card">
      <div class="row"><div class="grow"><div class="muted">Supply</div><b>${fmt(token.supply)}</b></div>
      <div class="grow"><div class="muted">Treasury</div><b>${fmt(treasury)}</b></div>
      <div class="grow"><div class="muted">Members</div><b>${fmt(members)}</b></div></div>
      <p class="muted">Every purchase burns ${token.burn_bps / 100}% and sends ${token.fee_bps / 100}% to the treasury, which funds rewards and jam prizes.</p>
      ${community.description ? html`<p>${community.description}</p>` : ''}
      ${chat ? html`<span class="pill">🔒 Group chat: hold ${fmt(chat.min_balance)} $${token.symbol}</span> ${me.balance >= chat.min_balance ? html`<span class="pill ok">you qualify</span>` : ''}` : ''}
    </div>
    <details class="card"><summary>Send $${token.symbol}</summary>
      <form data-action="send">
        <label>To (@username or Telegram id)</label><input name="to" required>
        <label>Amount</label><input name="amount" type="number" min="1" required>
        <label>Note</label><input name="memo" maxlength="140">
        <button type="submit">Send</button>
      </form>
    </details>
    <div class="card"><h3>Top holders</h3><div class="list">${holders.map((h, i) => html`<div><span>${i + 1}. ${who(h)}</span><b>${fmt(h.amount)}</b></div>`)}</div></div>
    <div class="card"><h3>Your activity</h3><div class="list">${activity.length ? activity.map((a) => html`
      <div><span>${a.kind.replace('_', ' ')} ${a.memo ? html`<span class="muted">· ${a.memo}</span>` : ''}</span><b>${sign(a)}${fmt(a.amount)}</b></div>`) : html`<div class="muted">Nothing yet.</div>`}</div></div>`);
  bindClicks({ claim: async () => { const r = await api(`/c/${state.slug}/claim`, {}); toast(`+${fmt(r.amount)} $${token.symbol}`); show(); } });
  bindForms({ send: async (f) => { await api(`/c/${state.slug}/transfer`, f); toast('Sent'); show(); } });
}

// ---------- shop ----------

async function shopPage() {
  const { token, me } = state.ov;
  const products = await api(`/c/${state.slug}/products`);
  render(html`
    ${products.length ? '' : html`<div class="card muted">The shop is empty. Admins can list digital products from the Admin tab.</div>`}
    ${products.map((p) => html`
      <div class="card">
        <div class="row"><h3 class="grow">${p.title}</h3><b>${fmt(p.price)} $${token.symbol}</b></div>
        ${p.description ? html`<p>${p.description}</p>` : ''}
        <div>
          ${p.min_balance ? html`<span class="pill">holders of ${fmt(p.min_balance)}+</span>` : ''}
          ${p.stock !== null ? html`<span class="pill">${fmt(p.stock)} left</span>` : ''}
          <span class="pill">${fmt(p.sold)} sold</span>
          ${p.active ? '' : html`<span class="pill">hidden</span>`}
        </div>
        ${p.content !== null
          ? html`<div class="secret">${p.content}</div>`
          : html`<button style="width:100%;margin-top:10px" data-click="buy" data-id="${p.id}" ${raw(me.balance < p.price ? 'disabled' : '')}>
              ${me.balance < p.price ? `Need ${fmt(p.price - me.balance)} more` : 'Buy'}</button>`}
      </div>`)}`);
  bindClicks({
    buy: async (d) => {
      const p = products.find((x) => x.id === Number(d.id));
      const ok = await confirmDialog(`Buy "${p.title}" for ${fmt(p.price)} $${token.symbol}?`);
      if (!ok) return;
      await api(`/c/${state.slug}/products/${d.id}/buy`, {});
      toast('Unlocked! Also sent to your DMs.');
      show();
    },
  });
}

function confirmDialog(msg) {
  if (tg?.showConfirm && inTelegram) return new Promise((r) => tg.showConfirm(msg, r));
  return Promise.resolve(confirm(msg));
}

// ---------- governance ----------

async function votePage() {
  const { token } = state.ov;
  const props = await api(`/c/${state.slug}/proposals`);
  render(html`
    ${props.length ? '' : html`<div class="card muted">No proposals yet.</div>`}
    ${props.map((p) => {
      const total = p.tally.reduce((a, b) => a + b, 0) || 1;
      return html`<div class="card">
        <h3>${p.title}</h3>
        <div class="muted">${p.closed ? 'Closed' : `Ends in ${ago(p.ends_at - Date.now())}`} · your power: ${fmt(p.my_power)} $${token.symbol}</div>
        ${p.options.map((o, i) => html`
          <div class="row" style="margin-top:8px"><span class="grow">${p.my_vote === i ? '✅ ' : ''}${o}</span><span class="muted">${Math.round((p.tally[i] / total) * 100)}%</span>
            ${!p.closed && p.my_power ? html`<button class="soft" data-click="vote" data-id="${p.id}" data-opt="${i}">Vote</button>` : ''}</div>
          <div class="bar"><i style="width:${(p.tally[i] / total) * 100}%"></i></div>`)}
        ${!p.closed && !p.my_power ? html`<div class="muted">Only wallets holding $${token.symbol} when this opened can vote.</div>` : ''}
      </div>`;
    })}`);
  bindClicks({ vote: async (d) => { await api(`/proposals/${d.id}/vote`, { option: Number(d.opt) }); toast('Vote counted'); show(); } });
}

// ---------- jams ----------

const PHASE = { lobby: '🟡 Lobby: join now', building: '🔨 Building', voting: '🗳 Voting', closed: '🏁 Finished' };

async function jamsPage() {
  if (state.jamId) return jamPage(state.jamId);
  const jams = await api(`/c/${state.slug}/jams`);
  render(html`
    <div class="card"><h3>Build jams</h3><p class="muted">Join, get a role and a team room, build something before the clock runs out. Everyone votes; the top rooms split the prize.</p></div>
    ${jams.length ? '' : html`<div class="card muted">No jams yet.</div>`}
    ${jams.map((j) => html`
      <div class="card" data-click="jam" data-id="${j.id}" style="cursor:pointer">
        <div class="row"><h3 class="grow">${j.title}</h3><span class="pill">${PHASE[j.phase]}</span></div>
        <div class="muted">${fmt(j.participants)} builders · prize ${fmt(j.prize)} $${state.ov.token.symbol} ${j.me ? '· you\'re in' : ''}</div>
      </div>`)}`);
  bindClicks({ jam: (d) => { state.jamId = Number(d.id); show(); } });
}

async function jamPage(id) {
  const j = await api(`/jams/${id}`);
  const sym = state.ov.token.symbol;
  const myRoom = j.rooms.find((r) => r.id === j.me?.room_id);
  const deadline = j.phase === 'building' ? j.build_ends_at : j.phase === 'voting' ? j.vote_ends_at : null;
  const skew = Date.now() - j.now;
  const sorted = j.phase === 'closed' ? [...j.rooms].sort((a, b) => (a.result?.rank ?? 99) - (b.result?.rank ?? 99)) : j.rooms;

  render(html`
    <div class="card">
      <div class="row"><h3 class="grow">${j.title}</h3><span class="pill">${PHASE[j.phase]}</span></div>
      ${j.theme ? html`<p>${j.theme}</p>` : ''}
      <div class="muted">Prize ${fmt(j.prize)} $${sym} · rooms of ${j.room_size} · ${j.build_minutes} min build · ${j.vote_minutes} min vote</div>
      <div>${j.roles.map((r) => html`<span class="pill">${r}</span>`)}</div>
      ${deadline ? html`<div class="clock" id="clock"></div>` : ''}
    </div>

    ${!j.me && ['lobby', 'building'].includes(j.phase) ? html`
      <form class="card" data-action="join"><h3>Join this jam</h3>
        <label>Pick a role</label>
        <select name="role"><option value="any">Any (fill what's needed)</option>${j.roles.map((r) => html`<option>${r}</option>`)}</select>
        <button type="submit">Join</button>
      </form>` : ''}

    ${j.me ? html`<div class="card">
      <div>You're a <span class="pill ok">${j.me.role}</span> ${myRoom ? html`in <b>${myRoom.name}</b>` : html`<span class="muted">· room assigned when the jam starts</span>`}</div>
      ${j.phase === 'lobby' ? html`<button class="ghost" data-click="leave">Leave</button>` : ''}
    </div>` : ''}

    ${myRoom ? html`<div class="card">
      <h3>${myRoom.name}</h3>
      <div>${myRoom.members.map((m) => html`<span class="pill">${who(m)} · ${m.role}</span>`)}</div>
      ${myRoom.chat_id ? html`<p class="muted">Your team's Telegram group invite is in your DMs.</p>` : ''}
      ${j.phase !== 'closed' ? html`
        <div class="chat" id="chat"></div>
        <form data-action="say" class="row"><input name="text" class="grow" placeholder="Message your room" maxlength="1000" autocomplete="off" required><button type="submit">Send</button></form>` : ''}
    </div>` : ''}

    ${myRoom && j.phase === 'building' ? html`
      <form class="card" data-action="submit"><h3>${myRoom.entry ? 'Update your entry' : 'Submit your entry'}</h3>
        <label>Title</label><input name="title" required maxlength="80" value="${myRoom.entry?.title ?? ''}">
        <label>Link (demo, repo, Figma…)</label><input name="url" type="url" maxlength="500" value="${myRoom.entry?.url ?? ''}">
        <label>What did you build?</label><textarea name="description" maxlength="1000">${myRoom.entry?.description ?? ''}</textarea>
        <button type="submit">Save entry</button>
      </form>` : ''}

    ${j.phase !== 'lobby' ? html`<div class="card"><h3>${j.phase === 'closed' ? 'Results' : 'Rooms'}</h3>
      ${sorted.map((r) => html`<div style="margin:10px 0">
        <div class="row"><b class="grow">${r.result ? ['🥇', '🥈', '🥉'][r.result.rank - 1] ?? `#${r.result.rank}` : ''} ${r.name}</b>
          ${r.votes !== null ? html`<span class="muted">${r.votes} votes</span>` : ''}
          ${j.phase === 'voting' && r.entry && r.id !== j.me?.room_id ? html`<button class="${j.my_vote === r.id ? '' : 'soft'}" data-click="vote" data-room="${r.id}">${j.my_vote === r.id ? 'Voted' : 'Vote'}</button>` : ''}</div>
        <div class="muted">${r.members.map((m) => `${who(m)} (${m.role})`).join(', ')}</div>
        ${r.entry ? html`<div><b>${r.entry.title}</b> ${r.entry.url ? html`<a href="${r.entry.url}" target="_blank" rel="noopener">open ↗</a>` : ''}<div class="muted">${r.entry.description}</div></div>` : html`<div class="muted">No entry ${j.phase === 'building' ? 'yet' : ''}</div>`}
        ${r.result?.payout_each ? html`<span class="pill ok">+${fmt(r.result.payout_each)} $${sym} each</span>` : ''}
      </div>`)}
    </div>` : ''}

    ${state.ov.me.is_admin && j.phase === 'lobby' ? html`<button style="width:100%" data-click="start">▶ Start jam (${j.participants} joined)</button>` : ''}`);

  if (deadline) {
    const tickClock = () => {
      const left = deadline - (Date.now() - skew);
      const el = $('#clock');
      if (el) el.textContent = left > 0 ? `⏱ ${ago(left)} left` : '⏱ time! refreshing…';
      if (left <= -2000) show();
    };
    tickClock();
    state.timers.push(setInterval(tickClock, 1000));
  }

  if (myRoom && j.phase !== 'closed') {
    let last = 0;
    const meId = state.ov.me.id;
    const pull = async () => {
      const msgs = await api(`/jams/${id}/messages?after=${last}`).catch(() => []);
      const box = $('#chat');
      if (!box || !msgs.length) return;
      for (const m of msgs) {
        box.insertAdjacentHTML('beforeend', html`<div class="msg ${m.user_id === meId ? 'me' : ''}"><span class="muted">${who(m)}</span><br>${m.text}</div>`.s);
        last = m.id;
      }
      box.scrollTop = box.scrollHeight;
    };
    pull();
    state.timers.push(setInterval(pull, 3000));
  }

  bindForms({
    join: async (f) => { await api(`/jams/${id}/join`, f); toast('You\'re in!'); show(); },
    submit: async (f) => { await api(`/jams/${id}/submit`, f); toast('Entry saved'); show(); },
    say: async (f, form) => { await api(`/jams/${id}/messages`, f); form.reset(); },
  });
  bindClicks({
    leave: async () => { await api(`/jams/${id}/leave`, {}); show(); },
    start: async () => { await api(`/jams/${id}/start`, {}); toast('Rooms assigned, clock started'); show(); },
    vote: async (d) => { await api(`/jams/${id}/vote`, { room_id: Number(d.room) }); toast('Vote counted'); show(); },
  });
}

// ---------- admin ----------

function adminPage() {
  const { token, chat } = state.ov;
  if (!token) {
    render(html`
      <form class="card" data-action="launch">
        <h3>🚀 Launch your token</h3>
        <p class="muted">Your members use it to buy products, unlock the group chat, earn rewards and vote.</p>
        <label>Symbol</label><input name="symbol" required maxlength="10" pattern="[A-Za-z0-9]{2,10}" placeholder="PIX">
        <label>Token name</label><input name="name" required maxlength="64" placeholder="Pixel">
        <label>Total supply</label><input name="supply" type="number" min="1000" value="1000000" required>
        <label>Your share (%). The rest goes to the treasury.</label><input name="creator_pct" type="number" min="0" max="50" value="10">
        <label>Welcome airdrop per member</label><input name="airdrop_amount" type="number" min="0" value="1000">
        <label>Treasury fee on sales (basis points, 100 = 1%)</label><input name="fee_bps" type="number" min="0" max="5000" value="500">
        <label>Burn on sales (basis points)</label><input name="burn_bps" type="number" min="0" max="5000" value="100">
        <button type="submit">Launch</button>
      </form>`);
    return bindForms({ launch: async (f) => { await api(`/c/${state.slug}/launch`, f); toast('Token launched 🚀'); state.tab = 'token'; show(); } });
  }
  const botHint = html`Add the bot to your group as an admin, then send <code>/link ${state.slug} 500</code> there to require 500 $${token.symbol} to join. Send <code>/addroom ${state.slug}</code> in extra groups to use them as jam rooms.`;
  render(html`
    <details class="card" open><summary>🛍 List a digital product</summary>
      <form data-action="product">
        <label>Title</label><input name="title" required maxlength="80">
        <label>Description</label><textarea name="description" maxlength="1000"></textarea>
        <label>Price ($${token.symbol})</label><input name="price" type="number" min="1" required>
        <label>Delivered content (link, code, text). Only buyers see it.</label><textarea name="content" required maxlength="4000"></textarea>
        <label>Holders-only: minimum balance to buy (0 = anyone)</label><input name="min_balance" type="number" min="0" value="0">
        <label>Stock (blank = unlimited)</label><input name="stock" type="number" min="0">
        <button type="submit">List product</button>
      </form>
    </details>
    <details class="card"><summary>🛠 Create a build jam</summary>
      <form data-action="jam">
        <label>Title</label><input name="title" required maxlength="80" placeholder="Weekend Mini App sprint">
        <label>Theme / brief</label><textarea name="theme" maxlength="500"></textarea>
        <label>Roles (comma separated)</label><input name="roles" value="builder, designer, storyteller">
        <label>Room size</label><input name="room_size" type="number" min="1" max="20" value="3">
        <label>Build time (minutes)</label><input name="build_minutes" type="number" min="1" value="60">
        <label>Voting time (minutes)</label><input name="vote_minutes" type="number" min="1" value="30">
        <label>Prize from treasury ($${token.symbol}, split 50/30/20)</label><input name="prize" type="number" min="0" value="0">
        <button type="submit">Create jam</button>
      </form>
    </details>
    <details class="card"><summary>🗳 Open a vote</summary>
      <form data-action="proposal">
        <label>Question</label><input name="title" required maxlength="200">
        <label>Options (one per line)</label><textarea name="options" required>Yes\nNo</textarea>
        <label>Duration (minutes)</label><input name="minutes" type="number" min="1" value="1440">
        <button type="submit">Open vote</button>
      </form>
    </details>
    <details class="card"><summary>🏆 Reward a member</summary>
      <form data-action="reward">
        <label>@username or Telegram id</label><input name="to" required>
        <label>Amount</label><input name="amount" type="number" min="1" required>
        <label>For</label><input name="reason" maxlength="140">
        <button type="submit">Pay from treasury</button>
      </form>
    </details>
    <details class="card"><summary>🔒 Token-gated group</summary>
      ${chat ? html`<form data-action="gate">
        <p class="muted">Linked: ${chat.title}. New members must hold this much to get in.</p>
        <input name="min_balance" type="number" min="0" value="${chat.min_balance}">
        <button type="submit">Save</button></form>` : ''}
      <p class="muted">${botHint}</p>
    </details>
    <details class="card"><summary>👥 Add an admin</summary>
      <form data-action="admin"><input name="user" required placeholder="@username"><button type="submit">Add</button></form>
    </details>`);
  bindForms({
    product: async (f, form) => { await api(`/c/${state.slug}/products`, f); toast('Listed'); form.reset(); },
    jam: async (f) => {
      const j = await api(`/c/${state.slug}/jams`, { ...f, roles: f.roles.split(',').map((s) => s.trim()).filter(Boolean) });
      toast('Jam created');
      state.tab = 'jams';
      state.jamId = j.id;
      show();
    },
    proposal: async (f) => {
      await api(`/c/${state.slug}/proposals`, { ...f, options: f.options.split('\n').map((s) => s.trim()).filter(Boolean) });
      toast('Vote opened');
      state.tab = 'vote';
      show();
    },
    reward: async (f, form) => { await api(`/c/${state.slug}/reward`, f); toast('Rewarded'); form.reset(); },
    gate: async (f) => { await api(`/c/${state.slug}/gate`, f); toast('Saved'); },
    admin: async (f, form) => { await api(`/c/${state.slug}/admins`, f); toast('Admin added'); form.reset(); },
  });
}

// ---------- boot ----------

(async () => {
  try {
    state.me = (await api('/me')).user;
    $('#who').textContent = who(state.me);
  } catch (err) {
    return render(html`<div class="card"><h3>Open bubble from Telegram</h3><p class="muted">${err.message}</p></div>`);
  }
  const slug = initialSlug();
  if (slug) open(slug);
  else show();
})();
