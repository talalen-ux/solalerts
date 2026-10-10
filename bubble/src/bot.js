import { Bot, InlineKeyboard } from 'grammy';
import { BubbleError } from './core.js';

const name = (u) => (u?.username ? '@' + u.username : u?.first_name || 'someone');

/**
 * Telegram side of bubble: opens the Mini App, links groups as gated
 * community chats or jam rooms, approves join requests by token balance,
 * supports /tip in chat, and relays core events as messages.
 */
export function createBot(core, { token, webAppUrl }) {
  const bot = new Bot(token);
  const appUrl = (slug) => (slug ? `${webAppUrl}?c=${encodeURIComponent(slug)}` : webAppUrl);
  const openAppKeyboard = (slug, label = 'Open bubble') => new InlineKeyboard().webApp(label, appUrl(slug));
  // Web App buttons only work in private chats, so groups get a deep link into the DM.
  const groupKeyboard = (slug, label = 'Open bubble') => new InlineKeyboard().url(label, `https://t.me/${bot.botInfo.username}?start=${slug}`);
  const dm = (userId, text, extra) => bot.api.sendMessage(userId, text, extra).catch(() => {});
  const toMainChat = (cid, text, slug) => {
    const chat = core.mainChat(cid);
    if (chat) bot.api.sendMessage(chat.chat_id, text, slug ? { reply_markup: groupKeyboard(slug) } : {}).catch(() => {});
  };

  bot.use((ctx, next) => {
    if (ctx.from && !ctx.from.is_bot) core.upsertUser(ctx.from);
    return next();
  });

  bot.command('start', async (ctx) => {
    const slug = ctx.match?.trim();
    if (ctx.chat.type !== 'private') {
      return ctx.reply('bubble works best in DM.', { reply_markup: groupKeyboard(slug || '') });
    }
    let intro = '🫧 bubble: launch a community token, sell digital products with it, and use it for access, rewards and voting. Run timed build jams where teams compete for the prize pool.';
    if (slug) {
      try {
        const c = core.community(slug);
        core.join(c.id, ctx.from.id);
        intro = `🫧 Welcome to ${c.name}! Open the app to claim your airdrop, browse the shop and join jams.`;
      } catch { /* unknown slug: fall back to the generic intro */ }
    }
    await ctx.reply(intro, { reply_markup: openAppKeyboard(slug) });
  });

  async function requireGroupAdmin(ctx) {
    if (ctx.chat.type === 'private') {
      await ctx.reply('Run this inside the Telegram group you want to link.');
      return false;
    }
    const member = await ctx.getChatMember(ctx.from.id);
    if (!['creator', 'administrator'].includes(member.status)) {
      await ctx.reply('Only group admins can do that.');
      return false;
    }
    return true;
  }

  // /link <slug> [min_balance] makes this group the community's token-gated chat.
  bot.command('link', async (ctx) => {
    if (!(await requireGroupAdmin(ctx))) return;
    const [slug, min = '0'] = ctx.match.trim().split(/\s+/);
    const c = core.community(slug);
    core.linkChat(c.id, ctx.from.id, { chat_id: ctx.chat.id, kind: 'main', title: ctx.chat.title, min_balance: min });
    const link = await ctx.createChatInviteLink({ name: 'bubble gate', creates_join_request: true }).catch(() => null);
    await ctx.reply(
      `🔗 Linked to ${c.name}. ${Number(min) ? `Joining requires ${min} tokens.` : 'Set a holding requirement in the app under Admin.'}\n` +
      (link ? `Share this gated invite: ${link.invite_link}` : 'Make me an admin with "invite users" so I can check join requests.'),
      { reply_markup: groupKeyboard(c.slug) },
    );
  });

  // /addroom <slug> adds this group to the pool of jam rooms.
  bot.command('addroom', async (ctx) => {
    if (!(await requireGroupAdmin(ctx))) return;
    const c = core.community(ctx.match.trim());
    core.linkChat(c.id, ctx.from.id, { chat_id: ctx.chat.id, kind: 'room', title: ctx.chat.title });
    await ctx.reply(`🏠 "${ctx.chat.title}" is now a jam room for ${c.name}. Teams get assigned here when a jam starts.`);
  });

  function chatCommunity(ctx) {
    const chat = core.chat(ctx.chat.id);
    if (!chat) throw new BubbleError(404, 'This group is not linked. An admin can run /link <community>.');
    return core.community(chat.community_id);
  }

  bot.command('balance', async (ctx) => {
    const c = chatCommunity(ctx);
    const o = core.overview(c.id, ctx.from.id);
    await ctx.reply(`${name(ctx.from)}: ${o.me.balance} ${o.token?.symbol ?? ''}`);
  });

  // Reply to someone's message with /tip <amount>.
  bot.command('tip', async (ctx) => {
    const c = chatCommunity(ctx);
    const target = ctx.message.reply_to_message?.from;
    if (!target || target.is_bot) return ctx.reply('Reply to someone\'s message with /tip <amount>.');
    core.upsertUser(target);
    core.transfer(c.id, ctx.from.id, target.id, ctx.match.trim(), 'tip');
    await ctx.reply(`💸 ${name(ctx.from)} tipped ${name(target)} ${ctx.match.trim()} ${core.overview(c.id, ctx.from.id).token.symbol}`);
  });

  // Admins: reply with /reward <amount> [reason] to pay from the treasury.
  bot.command('reward', async (ctx) => {
    const c = chatCommunity(ctx);
    const target = ctx.message.reply_to_message?.from;
    if (!target || target.is_bot) return ctx.reply('Reply to someone\'s message with /reward <amount> [reason].');
    const [amount, ...reason] = ctx.match.trim().split(/\s+/);
    core.upsertUser(target);
    core.reward(c.id, ctx.from.id, target.id, amount, reason.join(' '));
    await ctx.reply(`🏆 ${name(target)} earned ${amount} from the treasury${reason.length ? ': ' + reason.join(' ') : ''}`);
  });

  bot.command('app', async (ctx) => {
    const c = chatCommunity(ctx);
    await ctx.reply(`Open ${c.name} in bubble`, { reply_markup: groupKeyboard(c.slug) });
  });

  bot.on('chat_join_request', async (ctx) => {
    const req = ctx.chatJoinRequest;
    core.upsertUser(req.from);
    const verdict = core.canEnterChat(req.chat.id, req.from.id);
    if (verdict.ok) {
      await ctx.approveChatJoinRequest(req.from.id);
    } else {
      await ctx.declineChatJoinRequest(req.from.id);
      const chat = core.chat(req.chat.id);
      const slug = chat ? core.community(chat.community_id).slug : undefined;
      await dm(req.from.id, `🚫 Couldn't let you into ${req.chat.title}: ${verdict.reason}.`, { reply_markup: openAppKeyboard(slug, 'Get tokens') });
    }
  });

  bot.catch(({ ctx, error }) => {
    if (error instanceof BubbleError) return ctx.reply(`⚠️ ${error.message}`).catch(() => {});
    console.error('bot error', error);
  });

  // ---------- core events → Telegram ----------

  const ev = core.events;
  ev.on('token_launched', ({ community: c, token: t }) =>
    toMainChat(c.id, `🚀 $${t.symbol} is live! Supply ${t.supply.toLocaleString()}${t.airdrop_amount ? `, ${t.airdrop_amount} airdrop per member` : ''}.`, c.slug));
  ev.on('purchase', ({ buyerId, product, token }) =>
    dm(buyerId, `🛍 You bought "${product.title}" for ${product.price} ${token.symbol}.\n\n${product.content}`));
  ev.on('reward', ({ cid, userId, amount, reason }) =>
    dm(userId, `🏆 You earned ${amount} ${core.overview(cid, userId).token.symbol}${reason ? ` for ${reason}` : ''}.`));
  ev.on('proposal_created', ({ cid, proposal }) =>
    toMainChat(cid, `🗳 New proposal: ${proposal.title}\nOptions: ${proposal.options.join(' / ')}`, core.community(cid).slug));
  ev.on('proposal_closed', ({ proposal }) => {
    const best = proposal.tally.indexOf(Math.max(...proposal.tally));
    toMainChat(proposal.community_id, `🗳 "${proposal.title}" closed. Winner: ${proposal.options[best]}.`);
  });
  ev.on('jam_created', ({ cid, jam }) =>
    toMainChat(cid, `🛠 New build jam: ${jam.title}\n${jam.theme}\nRoles: ${jam.roles.join(', ')}. Prize: ${jam.prize}. Join in the app!`, core.community(cid).slug));

  async function sendRoomAssignment(jam, userId, room) {
    const me = room.members.find((m) => m.user_id === userId);
    const mates = room.members.filter((m) => m.user_id !== userId).map((m) => `${name(m)} (${m.role})`).join(', ') || 'just you so far';
    let invite = '';
    if (room.chat_id) {
      const link = await bot.api.createChatInviteLink(room.chat_id, { creates_join_request: true, name: `jam ${jam.id}` }).catch(() => null);
      if (link) invite = `\nRoom chat: ${link.invite_link}`;
    }
    const slug = core.community(jam.community_id).slug;
    await dm(userId, `🛠 ${jam.title} has started!\nYour role: ${me.role}\nYour room: ${room.name} with ${mates}${invite}\nYou have ${jam.build_minutes} minutes. Submit from the app.`,
      { reply_markup: openAppKeyboard(slug, 'Open my room') });
  }

  ev.on('jam_started', ({ jam }) => {
    for (const room of jam.rooms) for (const m of room.members) sendRoomAssignment(jam, m.user_id, room);
    toMainChat(jam.community_id, `🛠 ${jam.title} is live: ${jam.participants} builders in ${jam.rooms.length} rooms. ${jam.build_minutes} minutes on the clock.`);
  });
  ev.on('room_assigned', ({ jam, userId, roomId }) => sendRoomAssignment(jam, userId, jam.rooms.find((r) => r.id === roomId)));
  ev.on('jam_voting', ({ jam }) =>
    toMainChat(jam.community_id, `⏱ Time's up on ${jam.title}! Voting is open for ${jam.vote_minutes} minutes.`, core.community(jam.community_id).slug));
  ev.on('jam_closed', ({ jam }) => {
    const podium = jam.rooms.filter((r) => r.result).sort((a, b) => a.result.rank - b.result.rank).slice(0, 3)
      .map((r) => `${['🥇', '🥈', '🥉'][r.result.rank - 1]} ${r.name}: "${r.entry.title}" (${r.votes} votes, ${r.result.payout_each} each)`);
    toMainChat(jam.community_id, `🏁 ${jam.title} is over.\n${podium.join('\n') || 'No entries were submitted; the prize returned to the treasury.'}`);
    for (const room of jam.rooms) {
      for (const m of room.members) {
        if (room.result?.payout_each) dm(m.user_id, `🏁 Your room placed #${room.result.rank} in ${jam.title}. You won ${room.result.payout_each}!`);
      }
    }
  });

  return bot;
}
