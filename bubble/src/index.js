import { openDb } from './db.js';
import { createCore } from './core.js';
import { createApi } from './api.js';
import { createBot } from './bot.js';

const {
  BOT_TOKEN = '',
  WEBAPP_URL = '',
  PORT = '3000',
  DB_PATH = 'bubble.db',
  BUBBLE_DEV = '',
} = process.env;
const dev = BUBBLE_DEV === '1';

if (!BOT_TOKEN && !dev) {
  console.error('Set BOT_TOKEN (from @BotFather), or BUBBLE_DEV=1 to try the Mini App in a browser.');
  process.exit(1);
}

const core = createCore(openDb(DB_PATH));
const api = createApi(core, { botToken: BOT_TOKEN, dev });
api.server().listen(Number(PORT), () => console.log(`bubble api + mini app on :${PORT}${dev ? ' (dev mode)' : ''}`));
setInterval(() => core.tick(), 10_000);

if (BOT_TOKEN) {
  if (!WEBAPP_URL.startsWith('https://')) {
    console.error('WEBAPP_URL must be the public https URL of this server (Telegram requires https for Mini Apps).');
    process.exit(1);
  }
  const bot = createBot(core, { token: BOT_TOKEN, webAppUrl: WEBAPP_URL });
  await bot.api.setMyCommands([
    { command: 'start', description: 'Open bubble' },
    { command: 'link', description: 'Link this group to a community: /link <slug> [min tokens]' },
    { command: 'addroom', description: 'Use this group as a jam room: /addroom <slug>' },
    { command: 'balance', description: 'Your token balance' },
    { command: 'tip', description: 'Reply with /tip <amount>' },
    { command: 'reward', description: 'Admins: reply with /reward <amount> [reason]' },
    { command: 'app', description: 'Open this community in bubble' },
  ]);
  bot.start({ allowed_updates: ['message', 'chat_join_request'], onStart: (me) => console.log(`bot @${me.username} running`) });
}
