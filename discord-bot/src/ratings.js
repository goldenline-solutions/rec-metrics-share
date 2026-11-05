'use strict';

/**
 * 2K ratings: the weekly staff sync and the commands around it.
 *
 * The sync only ever refreshes the ratings reference. It never moves a player
 * between teams — league rosters are changed by trades and nothing else.
 */

const { SlashCommandBuilder, EmbedBuilder, MessageFlags } = require('discord.js');
const api = require('./api');
const { PURPLE, AMBER, GREEN, GREY } = require('./embeds');

// 2kratings publishes weekly; once a week a few hours after that is plenty.
const WEEKLY_MS = 7 * 24 * 60 * 60 * 1000;
const CHECK_INTERVAL_MS = 60 * 60 * 1000;
const STATE_KEY = 'lastRatingsSync';

const state = new Map();

function movementLines(changes, limit = 12) {
  return changes.slice(0, limit).map((c) => {
    const arrow = c.delta > 0 ? '▲' : '▼';
    const sign = c.delta > 0 ? `+${c.delta}` : `${c.delta}`;
    return `${arrow} **${c.name}** ${c.from} → ${c.to} (${sign})`;
  });
}

function syncEmbed(result, { title = 'Weekly 2K ratings sync' } = {}) {
  const risers = result.changes.filter((c) => c.delta > 0).length;
  const fallers = result.changes.filter((c) => c.delta < 0).length;

  const embed = new EmbedBuilder()
    .setColor(result.changes.length ? PURPLE : GREY)
    .setTitle(title)
    .setDescription(
      result.changes.length
        ? `${result.updated} rating${result.updated === 1 ? '' : 's'} moved — ${risers} up, ${fallers} down.`
        : 'No rating changes since the last sync.'
    )
    .addFields(
      { name: 'Players', value: String(result.total), inline: true },
      { name: 'New', value: String(result.created), inline: true },
      { name: 'Unchanged', value: String(result.unchanged), inline: true },
    );

  if (result.changes.length) {
    embed.addFields({
      name: 'Biggest moves',
      value: movementLines(result.changes).join('\n').slice(0, 1000),
    });
  }
  if (!result.badges_available) {
    embed.setFooter({ text: 'Badges need NBA2K_API_KEY in backend/.env — attributes synced fine without it.' });
  }
  return embed;
}

/**
 * Run the sync for every guild and post the result to the approvals channel.
 * Called hourly; only acts once a week.
 */
async function weeklySync(client, { force = false } = {}) {
  for (const guild of client.guilds.cache.values()) {
    const key = `${STATE_KEY}:${guild.id}`;
    const last = state.get(key) || 0;
    if (!force && Date.now() - last < WEEKLY_MS) continue;

    let league;
    try {
      league = await api.call(`/api/mynba/league?guild_id=${guild.id}`);
    } catch (err) {
      continue; // no league in this guild
    }

    try {
      const result = await api.syncRatings(guild.id, 'curr', 'schedule');
      state.set(key, Date.now());

      const channelId = (league.league && league.league.approvals_channel_id)
        || (league.league && league.league.trade_channel_id);
      if (!channelId) continue;
      const channel = await client.channels.fetch(channelId).catch(() => null);
      if (!channel) continue;

      await channel.send({ embeds: [syncEmbed(result)] }).catch(() => {});
    } catch (err) {
      console.error(`[MyNBA] Ratings sync failed for ${guild.id}:`, err.message);
    }
  }
}

function startWeeklySync(client) {
  setInterval(() => weeklySync(client).catch(() => {}), CHECK_INTERVAL_MS);
  // Don't fire on boot — a restart shouldn't spam the staff channel.
  state.clear();
  for (const guild of client.guilds.cache.values()) {
    state.set(`${STATE_KEY}:${guild.id}`, Date.now());
  }
}

const commands = {};

commands['ratings-sync'] = {
  data: new SlashCommandBuilder()
    .setName('ratings-sync')
    .setDescription('Pull the latest 2K ratings now. Does not change any roster.'),
  async run(interaction) {
    await interaction.deferReply();
    const result = await api.syncRatings(interaction.guildId, 'curr', interaction.user.id);
    await interaction.editReply({ embeds: [syncEmbed(result, { title: 'Ratings synced' })] });
  },
};

commands['ratings-status'] = {
  data: new SlashCommandBuilder()
    .setName('ratings-status')
    .setDescription('When the 2K ratings were last pulled.'),
  async run(interaction) {
    await interaction.deferReply({ flags: MessageFlags.Ephemeral });
    const status = await api.ratingsStatus(interaction.guildId);
    const last = status.runs[0];

    const embed = new EmbedBuilder()
      .setColor(status.players ? PURPLE : AMBER)
      .setTitle('2K ratings')
      .addFields(
        { name: 'Players stored', value: String(status.players), inline: true },
        { name: 'With badges', value: `${status.with_badges}`, inline: true },
        { name: 'API key', value: status.has_api_key ? 'set' : 'not set', inline: true },
      );

    if (last) {
      const when = last.finished_at ? `<t:${Math.floor(new Date(`${last.finished_at}Z`).getTime() / 1000)}:R>` : 'never';
      embed.addFields({
        name: 'Last sync',
        value: `${when} — ${last.updated} changed, ${last.created} new` + (last.error ? `\n⚠️ ${last.error}` : ''),
      });
    }
    if (!status.has_api_key) {
      embed.setFooter({ text: 'Set NBA2K_API_KEY in backend/.env to pull badges.' });
    }
    await interaction.editReply({ embeds: [embed] });
  },
};

commands['ratings-badges'] = {
  data: new SlashCommandBuilder()
    .setName('ratings-badges')
    .setDescription('Pull every player’s badges (needs the API key).')
    .addIntegerOption((o) =>
      o.setName('limit').setDescription('Only the first N badges (debug; default all 40)')),
  async run(interaction) {
    await interaction.deferReply();
    const limit = interaction.options.getInteger('limit') ?? null;
    const result = await api.syncBadges(interaction, limit);

    const lines = [
      `**${result.players_with_badges}** players now have badges — ` +
        `${result.total_assignments} assignments across ${result.badges_checked} badges ` +
        `(${result.api_calls} API calls).`,
    ];
    if (result.stale_flags_cleared) {
      lines.push(`Cleared ${result.stale_flags_cleared} player(s) wrongly marked as synced.`);
    }
    if (result.truncated && result.truncated.length) {
      lines.push(
        `⚠️ ${result.truncated.length} badge/tier lists hit the API's 100-row cap, so a few ` +
        'assignments are missing. That is an nba2kapi limit — re-running will not fix it.'
      );
    }
    await interaction.editReply(lines.join('\n'));
  },
};

commands['league-seed-rosters'] = {
  data: new SlashCommandBuilder()
    .setName('league-seed-rosters')
    .setDescription('Fill the league from current 2K rosters, free agents included.')
    .addBooleanOption((o) => o.setName('apply').setDescription('Actually write it (default: preview only)')),
  async run(interaction) {
    await interaction.deferReply();
    const apply = interaction.options.getBoolean('apply') ?? false;
    const summary = await api.seedRosters(interaction, { era: 'curr', dry_run: !apply });

    const embed = new EmbedBuilder()
      .setColor(summary.unmatched_teams.length ? AMBER : GREEN)
      .setTitle(apply ? 'Rosters seeded from 2K' : 'Preview — nothing written yet')
      .addFields(
        { name: '2K players', value: String(summary.reference_players), inline: true },
        { name: 'Added', value: String(summary.created), inline: true },
        { name: 'Already here', value: String(summary.already_in_league), inline: true },
        { name: 'Free agents', value: String(summary.free_agents), inline: true },
      );
    if (summary.unmatched_teams.length) {
      embed.addFields({
        name: 'Teams that did not map',
        value: summary.unmatched_teams.map(([t, n]) => `${t} (${n})`).join('\n').slice(0, 1000),
      });
    }
    await interaction.editReply({
      content: apply ? null : 'Run it again with `apply: True` to write these rosters.',
      embeds: [embed],
    });
  },
};

commands['card'] = {
  data: new SlashCommandBuilder()
    .setName('card')
    .setDescription("A player's 2K ratings and badges.")
    .addStringOption((o) =>
      o.setName('player').setDescription('Player').setRequired(true).setAutocomplete(true)),
  async autocomplete(interaction) {
    const focused = interaction.options.getFocused() || '';
    try {
      const { players } = await api.searchPlayers(interaction.guildId, focused);
      return players.slice(0, 25).map((p) => ({
        name: `${p.name}${p.team ? ` — ${p.team}` : ' — free agent'}`.slice(0, 100),
        value: p.name,
      }));
    } catch (_) {
      return [];
    }
  },
  async run(interaction) {
    await interaction.deferReply();
    const name = interaction.options.getString('player');
    const { player, ratings } = await api.playerCard(interaction.guildId, name);

    const embed = new EmbedBuilder()
      .setColor(PURPLE)
      .setTitle(player.name)
      .setDescription(
        [player.is_free_agent ? 'Free agent' : player.team, player.position, ratings && ratings.archetype]
          .filter(Boolean).join(' · ')
      );

    if (ratings) {
      if (ratings.player_image) embed.setThumbnail(ratings.player_image);
      embed.addFields(
        { name: 'Overall', value: `${ratings.overall ?? '—'}`, inline: true },
        { name: 'Height', value: ratings.height || '—', inline: true },
        { name: 'Wingspan', value: ratings.wingspan || '—', inline: true },
      );

      const attrs = ratings.attributes || {};
      const best = Object.entries(attrs).sort((a, b) => b[1] - a[1]).slice(0, 8);
      if (best.length) {
        embed.addFields({
          name: 'Top attributes',
          value: best.map(([k, v]) => `\`${String(v).padStart(2)}\` ${k.replace(/([A-Z])/g, ' $1').replace(/^./, (c) => c.toUpperCase())}`).join('\n'),
        });
      }

      const badgeCount = ratings.badges && Object.keys(ratings.badges).length;
      embed.addFields({
        name: 'Badges',
        value: ratings.has_badges && badgeCount
          ? `${badgeCount} badge group(s) — see the portal for the full list`
          : 'Not pulled yet — a commissioner can run `/ratings-badges`',
      });
    } else {
      embed.addFields({ name: '2K ratings', value: 'No ratings for this player yet. Run `/ratings-sync`.' });
    }

    await interaction.editReply({ embeds: [embed] });
  },
};

module.exports = { commands, weeklySync, startWeeklySync, syncEmbed };
