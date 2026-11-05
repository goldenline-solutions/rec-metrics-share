'use strict';

/**
 * RecMetrics Discord bot.
 *
 * Two jobs:
 *   1. Rec box-score ingestion — screenshots dropped in registered channels
 *      (src/ingest.js, unchanged behaviour).
 *   2. The MyNBA league: rosters, trades and approvals (src/commands.js,
 *      src/buttons.js), all backed by the league API.
 *
 * This file is wiring only. Command logic lives in src/.
 */

require('dotenv').config();

const {
  Client,
  GatewayIntentBits,
  SlashCommandBuilder,
  REST,
  Routes,
  PermissionFlagsBits,
  ChannelType,
  MessageFlags,
} = require('discord.js');

const api = require('./src/api');
const ingest = require('./src/ingest');
const { commands, handleProposeModal, handleProposeModal3 } = require('./src/commands');
const { handleButton } = require('./src/buttons');
const { startWeeklySync } = require('./src/ratings');

const DISCORD_TOKEN = process.env.DISCORD_TOKEN;
const API_BASE_URL = api.API_BASE_URL;
const API_AUTH_HEADER = api.AUTH_HEADER;
const CHANNELS_REFRESH_INTERVAL_MS = 5 * 60 * 1000;
const SWEEP_INTERVAL_MS = 10 * 60 * 1000;

// Start with env-based channels; API-fetched channels merge in on ready
const rawSingle = (process.env.TARGET_CHANNEL_ID || '').trim();
const rawList = (process.env.TARGET_CHANNEL_IDS || '').trim();
const targetChannelIds = new Set(
  rawList
    ? rawList.split(',').map((id) => id.trim()).filter(Boolean)
    : rawSingle ? [rawSingle] : []
);

if (!DISCORD_TOKEN) {
  console.error('Missing required env: DISCORD_TOKEN must be set.');
  process.exit(1);
}
const useChannelsApi = Boolean(API_BASE_URL && API_AUTH_HEADER);
if (targetChannelIds.size === 0 && !useChannelsApi) {
  console.error('Set TARGET_CHANNEL_ID, TARGET_CHANNEL_IDS, or API_BASE_URL+API_AUTH_HEADER to fetch channels from API.');
  process.exit(1);
}

const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.MessageContent,
  ],
});

// ---------------------------------------------------------------------------
// Upload channels (box-score ingestion)
// ---------------------------------------------------------------------------

async function fetchChannelsFromApi() {
  if (!API_BASE_URL || !API_AUTH_HEADER) return;
  try {
    const data = await api.call('/api/discord/upload-channels');
    if (Array.isArray(data.channel_ids)) {
      for (const id of data.channel_ids) {
        if (id) targetChannelIds.add(String(id));
      }
    }
  } catch (err) {
    console.error('[RecMetrics] Failed to fetch channels from API:', err.message);
  }
}

async function registerUploadChannel(guildId, channelId, registeredByDiscordId) {
  return api.call('/api/discord/upload-channels', {
    method: 'POST',
    body: {
      guild_id: guildId,
      channel_id: channelId,
      registered_by_discord_id: registeredByDiscordId || undefined,
    },
  });
}

const setChannelCommand = new SlashCommandBuilder()
  .setName('recmetrics-set-channel')
  .setDescription('Set this channel (or the chosen channel) as the Rec box score upload channel.')
  .setDefaultMemberPermissions(PermissionFlagsBits.ManageChannels)
  .addChannelOption((opt) =>
    opt
      .setName('channel')
      .setDescription('Channel for uploads (default: this channel)')
      .addChannelTypes(ChannelType.GuildText));

function commandBody() {
  return [
    setChannelCommand.toJSON(),
    ...Object.values(commands).map((c) => c.data.toJSON()),
  ];
}

/**
 * Register commands globally AND per guild.
 *
 * Global registration alone can take up to an hour to show up in a client,
 * which reads as "the bot is broken". Guild commands appear immediately and
 * override the global one of the same name, so nobody sees duplicates.
 */
async function registerSlashCommands() {
  const rest = new REST().setToken(DISCORD_TOKEN);
  const body = commandBody();

  await rest.put(Routes.applicationCommands(client.user.id), { body });

  const guilds = [...client.guilds.cache.values()];
  const results = await Promise.allSettled(
    guilds.map((g) => rest.put(Routes.applicationGuildCommands(client.user.id, g.id), { body }))
  );
  results.forEach((r, i) => {
    if (r.status === 'rejected') {
      console.error(`[RecMetrics] Could not register commands in ${guilds[i].name}: ${r.reason.message}` +
        ' — the bot likely needs the applications.commands scope there.');
    }
  });

  const ok = results.filter((r) => r.status === 'fulfilled').length;
  return { count: body.length, guilds: ok, totalGuilds: guilds.length };
}

// A server added after startup gets the commands right away too.
client.on('guildCreate', async (guild) => {
  try {
    const rest = new REST().setToken(DISCORD_TOKEN);
    await rest.put(Routes.applicationGuildCommands(client.user.id, guild.id), { body: commandBody() });
    console.log(`[RecMetrics] Registered commands in new guild ${guild.name}.`);
  } catch (err) {
    console.error(`[RecMetrics] Failed to register commands in ${guild.name}: ${err.message}`);
  }
});

// ---------------------------------------------------------------------------
// Trade sweep — expire stale proposals, execute matured protest windows
// ---------------------------------------------------------------------------

async function sweepTrades() {
  for (const guild of client.guilds.cache.values()) {
    try {
      const result = await api.sweep(guild.id);
      const executed = result.executed || [];
      if (!executed.length) continue;

      const channelId = executed[0] && executed[0].channel_id;
      const channel = channelId ? await client.channels.fetch(channelId).catch(() => null) : null;
      if (!channel) continue;
      for (const trade of executed) {
        await channel.send(
          `✅ **${trade.ref}** went through — the protest window closed with no objections. Rosters are updated.`
        ).catch(() => {});
      }
    } catch (err) {
      if (err.code !== 'no_league' && err.status !== 404) {
        console.error('[MyNBA] Sweep failed:', err.message);
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

client.once('ready', async () => {
  await fetchChannelsFromApi();
  try {
    const reg = await registerSlashCommands();
    console.log(`[RecMetrics] Registered ${reg.count} slash commands globally and in ` +
      `${reg.guilds}/${reg.totalGuilds} guild(s).`);
  } catch (err) {
    console.error('[RecMetrics] Failed to register slash commands:', err.message);
  }

  if (targetChannelIds.size > 0) {
    console.log(`[RecMetrics] Bot ready as ${client.user.tag}. Listening in ${targetChannelIds.size} channel(s).`);
  } else {
    console.log(`[RecMetrics] Bot ready as ${client.user.tag}. No upload channels yet; use /recmetrics-set-channel.`);
  }

  setInterval(fetchChannelsFromApi, CHANNELS_REFRESH_INTERVAL_MS);
  setInterval(sweepTrades, SWEEP_INTERVAL_MS);
  startWeeklySync(client);
});

client.on('interactionCreate', async (interaction) => {
  try {
    if (interaction.isAutocomplete()) {
      const command = commands[interaction.commandName];
      if (!command || !command.autocomplete) return interaction.respond([]);
      const choices = await command.autocomplete(interaction);
      return interaction.respond(choices.slice(0, 25));
    }

    if (interaction.isButton() && interaction.customId.startsWith('mynba:')) {
      return handleButton(interaction);
    }

    if (interaction.isModalSubmit() && interaction.customId.startsWith('mynba:proposemodal3:')) {
      return handleProposeModal3(interaction, interaction.customId.split(':').slice(2).join(':'));
    }

    if (interaction.isModalSubmit() && interaction.customId.startsWith('mynba:proposemodal:')) {
      const teamName = interaction.customId.split(':').slice(2).join(':');
      return handleProposeModal(interaction, teamName);
    }

    if (!interaction.isChatInputCommand()) return;

    if (interaction.commandName === 'recmetrics-set-channel') {
      return handleSetChannel(interaction);
    }

    const command = commands[interaction.commandName];
    if (!command) return;
    await command.run(interaction);
  } catch (err) {
    console.error(`[Bot] ${interaction.commandName || interaction.customId} failed:`, err);
    const message = `❌ ${err.message || 'Something went wrong.'}`.slice(0, 1900);
    try {
      if (interaction.deferred || interaction.replied) {
        await interaction.editReply({ content: message, embeds: [], components: [] });
      } else if (!interaction.isAutocomplete()) {
        await interaction.reply({ content: message, flags: MessageFlags.Ephemeral });
      }
    } catch (_) {}
  }
});

async function handleSetChannel(interaction) {
  const channel = interaction.options.getChannel('channel') ?? interaction.channel;
  if (!channel || channel.type !== ChannelType.GuildText) {
    return interaction.reply({ content: 'Please choose a text channel.', flags: MessageFlags.Ephemeral });
  }
  if (!interaction.member.permissions.has(PermissionFlagsBits.ManageChannels)) {
    return interaction.reply({
      content: 'You need the "Manage Channels" permission to set the upload channel.',
      flags: MessageFlags.Ephemeral,
    });
  }
  await registerUploadChannel(interaction.guildId, channel.id, interaction.user.id);
  targetChannelIds.add(channel.id);
  await interaction.reply({
    content: `✅ <#${channel.id}> is now the Rec box score upload channel for this server. Users can drop screenshots here to ingest games.`,
  });
}

client.on('messageCreate', async (message) => {
  try {
    if (!targetChannelIds.has(message.channelId)) return;
    if (message.author.bot) return;

    const text = (message.content || '').trim();

    if (text === '!api-health') {
      let reply;
      try {
        const data = await api.health();
        const statusText = data && typeof data.status === 'string' ? data.status : 'ok';
        reply = `✅ API healthy (status: ${statusText})`;
      } catch (err) {
        reply = `❌ API health check failed${err.status ? ` (${err.status})` : ''}`;
        console.error('[RecMetrics] Health check error:', err.message || err);
      }
      await message.reply(reply);
      return;
    }

    const attachments = message.attachments && message.attachments.size > 0
      ? Array.from(message.attachments.values())
      : [];
    const imageAttachments = attachments.filter(ingest.isImageAttachment);
    if (imageAttachments.length === 0) return;

    for (const attachment of imageAttachments) {
      ingest.enqueue(message, attachment, message.author.id);
    }
    await message.reply(`📥 Queued ${imageAttachments.length} screenshot(s). You'll get a reply for each when done.`);
    ingest.processQueue();
  } catch (err) {
    console.error('[RecMetrics] Message handler error:', err);
  }
});

client.login(DISCORD_TOKEN).catch((err) => {
  console.error('[RecMetrics] Login failed:', err);
  process.exit(1);
});
