# 🫧 bubble

A Telegram bot and Mini App where communities launch their own token and run on it:

- **Launch**: an admin mints a token (supply, creator share, welcome airdrop, sale fee and burn). The remainder sits in a community treasury.
- **Sell**: list digital products (links, codes, files, text) priced in the token. A purchase splits into seller / treasury fee / burn, and the content is unlocked in the app and sent by DM. Products can be holders-only or limited stock.
- **Access**: link a Telegram group with `/link <slug> <min>`. The bot approves join requests only for members holding enough tokens.
- **Rewards**: welcome airdrop, `/tip` and admin `/reward` in chat, and treasury-funded jam prizes.
- **Voting**: token-weighted proposals. Balances are snapshotted when a vote opens, so tokens can't be passed around to vote twice.
- **Build jams**: enter a jam, get a role, get assigned to a mixed-role team room, build before the clock runs out, then everyone votes. The prize is escrowed up front and the top 3 rooms split it 50/30/20. Rooms can be real Telegram groups (`/addroom <slug>`, entry limited to the team) or the built-in room chat in the app.

## Run it

Requires Node ≥ 22.5 (uses the built-in `node:sqlite`, no native deps).

```bash
npm install
npm test                 # core rules + initData verification
npm run dev              # http://localhost:3000, browser dev mode (no Telegram needed)
```

In dev mode the app asks for a `<id>:<name>` test identity, so you can open several browser profiles and play several users.

### With Telegram

1. Create a bot with @BotFather and copy the token.
2. Host this server at a public **https** URL (Railway, Fly, a tunnel such as `cloudflared` for testing).
3. Start it:
   ```bash
   BOT_TOKEN=123:abc WEBAPP_URL=https://your-host.example npm start
   ```
4. DM the bot `/start`, open the app, create a community and launch its token.
5. Add the bot to your community group **as an admin with "invite users"**, then run `/link <slug> 500` there. Share the invite link it prints; it creates join requests that the bot approves by balance.
6. Optional: add the bot to extra groups and run `/addroom <slug>` in each to use them as jam rooms.

Share `https://t.me/<your_bot>?start=<slug>` to send people straight into a community.

| Env | Default | |
|---|---|---|
| `BOT_TOKEN` | required unless dev | BotFather token. Also the key for verifying Mini App `initData`. |
| `WEBAPP_URL` | required with bot | Public https URL of this server. |
| `PORT` | `3000` | |
| `DB_PATH` | `bubble.db` | SQLite file. |
| `BUBBLE_DEV` | | `1` enables the `x-dev-user` header login. Never set this in production. |

## Layout

```
src/core.js   all rules: tokens, ledger, shop, gates, governance, jams (+ events)
src/db.js     schema, transaction helper
src/api.js    JSON API for the Mini App, Telegram initData auth, static files
src/bot.js    grammY bot: commands, join-request gating, event → message relay
public/       the Mini App (vanilla JS, follows the Telegram theme)
test/         node:test suite
```

## Important: tokens are off-chain in this version

Balances live in an append-only ledger in SQLite, and the server is the custodian. That makes launches instant and free, and every rule above is enforced and tested. These are **not yet transferable on-chain assets**. To go on-chain, swap the `credit`/`debit`/`mint`/`burn` primitives in `core.js` for a chain adapter, for example TON jettons (native to Telegram wallets) or an SPL/ERC-20 factory. Then add wallet connect (TON Connect) in the Mini App. Until then, don't present the tokens as having monetary value.
