'use strict';

/**
 * Slash commands for the MyNBA league.
 *
 * Each entry exports the command definition plus `run`, and optionally
 * `autocomplete`. Nothing here enforces permissions on its own — the API does
 * that — but commands do surface the API's error text as-is, because those
 * messages are already written for a person to read.
 */

const {
  SlashCommandBuilder,
  PermissionFlagsBits,
  MessageFlags,
  ModalBuilder,
  TextInputBuilder,
  TextInputStyle,
  ActionRowBuilder,
  EmbedBuilder,
} = require('discord.js');

const api = require('./api');
const { tradeEmbed, tradeButtons, rosterEmbed, playerEmbed, PURPLE, AMBER } = require('./embeds');

const ephemeral = (content) => ({ content, flags: MessageFlags.Ephemeral });

const NEWLINE = String.fromCharCode(10);

/** Split "Jordan, Pippen , Rodman" or newline-separated text into names. */
const parseNames = (raw) =>
  String(raw || '')
    .split(/[\n,]/)
    .map((s) => s.trim())
    .filter(Boolean);

async function teamChoices(interaction) {
  const focused = (interaction.options.getFocused() || '').toLowerCase();
  try {
    const { teams } = await api.getTeams(interaction.guildId);
    return teams
      .filter((t) =>
        !focused ||
        t.name.toLowerCase().includes(focused) ||
        t.abbrev.toLowerCase().includes(focused) ||
        (t.full_name || '').toLowerCase().includes(focused))
      .slice(0, 25)
      .map((t) => ({ name: `${t.name}${t.is_cpu ? ' (CPU)' : ''}`, value: t.name }));
  } catch (_) {
    return [];
  }
}

async function playerChoices(interaction) {
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
}

const commands = {};

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

commands['league-setup'] = {
  data: new SlashCommandBuilder()
    .setName('league-setup')
    .setDescription('Create the league for this server and seed all 30 NBA teams.')
    .setDefaultMemberPermissions(PermissionFlagsBits.ManageGuild)
    .addStringOption((o) => o.setName('name').setDescription('League name'))
    .addChannelOption((o) => o.setName('trades').setDescription('Channel for trade proposals'))
    .addChannelOption((o) => o.setName('approvals').setDescription('Channel for commissioner approvals'))
    .addIntegerOption((o) => o.setName('roster_size').setDescription('Players per team (default 11)')),
  async run(interaction) {
    await interaction.deferReply();
    const result = await api.createLeague(interaction, {
      name: interaction.options.getString('name') || undefined,
      trade_channel_id: interaction.options.getChannel('trades')?.id,
      approvals_channel_id: interaction.options.getChannel('approvals')?.id,
      roster_size: interaction.options.getInteger('roster_size') ?? undefined,
    });
    await interaction.editReply(
      `✅ Created **${result.league.name}** with all 30 teams. Roster target is ${result.league.roster_size}.\n` +
      'You are the first commissioner. Next: `/league-import` with the roster CSV, then `/team-set-gm` for each GM.'
    );
  },
};

commands['league-import'] = {
  data: new SlashCommandBuilder()
    .setName('league-import')
    .setDescription('Import rosters from a CSV. Shows a preview before it writes anything.')
    .addAttachmentOption((o) => o.setName('csv').setDescription('Roster CSV').setRequired(true))
    .addBooleanOption((o) => o.setName('apply').setDescription('Actually write it (default: preview only)')),
  async run(interaction) {
    await interaction.deferReply();
    const file = interaction.options.getAttachment('csv');
    const apply = interaction.options.getBoolean('apply') ?? false;

    const res = await fetch(file.url, { signal: AbortSignal.timeout(20000) });
    if (!res.ok) throw new Error(`Could not download the CSV (${res.status})`);
    const csv = await res.text();

    const summary = await api.importRosters(interaction, csv, { dryRun: !apply });
    const embed = new EmbedBuilder()
      .setColor(summary.problems.length ? AMBER : PURPLE)
      .setTitle(apply ? 'Rosters imported' : 'Preview — nothing written yet')
      .addFields(
        { name: 'Added', value: String(summary.created), inline: true },
        { name: 'Updated', value: String(summary.updated), inline: true },
        { name: 'Released', value: String(summary.released), inline: true },
        { name: 'Columns used', value: Object.keys(summary.columns_used).join(', ') || '—' },
      );
    if (summary.columns_ignored.length) {
      embed.addFields({ name: 'Columns kept but unmapped', value: summary.columns_ignored.join(', ').slice(0, 1000) });
    }
    if (summary.problems.length) {
      embed.addFields({
        name: `Problems (${summary.problems.length})`,
        value: summary.problems.slice(0, 8).join('\n').slice(0, 1000),
      });
    }
    await interaction.editReply({
      content: apply ? null : 'Run it again with `apply: True` to write these changes.',
      embeds: [embed],
    });
  },
};

commands['team-set-gm'] = {
  data: new SlashCommandBuilder()
    .setName('team-set-gm')
    .setDescription('Put someone in charge of a team (or clear it back to CPU).')
    .addStringOption((o) => o.setName('team').setDescription('Team').setRequired(true).setAutocomplete(true))
    .addUserOption((o) => o.setName('gm').setDescription('The GM — leave empty to make it a CPU team')),
  autocomplete: teamChoices,
  async run(interaction) {
    await interaction.deferReply();
    const teamName = interaction.options.getString('team');
    const gm = interaction.options.getUser('gm');

    const { teams } = await api.getTeams(interaction.guildId);
    const team = teams.find((t) => t.name.toLowerCase() === teamName.toLowerCase());
    if (!team) return interaction.editReply(`No team called "${teamName}".`);

    await api.setTeamGm(interaction, team.id, {
      discord_id: gm ? gm.id : null,
      display_name: gm ? (gm.displayName || gm.username) : null,
    });
    await interaction.editReply(
      gm ? `✅ <@${gm.id}> now runs the **${team.name}**.` : `✅ The **${team.name}** are a CPU team again.`
    );
  },
};

commands['league-commissioner'] = {
  data: new SlashCommandBuilder()
    .setName('league-commissioner')
    .setDescription('Add another commissioner.')
    .addUserOption((o) => o.setName('user').setDescription('Who').setRequired(true)),
  async run(interaction) {
    await interaction.deferReply();
    const user = interaction.options.getUser('user');
    await api.addCommissioner(interaction, {
      discord_id: user.id,
      display_name: user.displayName || user.username,
    });
    await interaction.editReply(`✅ <@${user.id}> is a commissioner.`);
  },
};

commands['trades-lock'] = {
  data: new SlashCommandBuilder()
    .setName('trades-lock')
    .setDescription('Stop or restart trading (the deadline switch).')
    .addBooleanOption((o) => o.setName('locked').setDescription('True to stop trading').setRequired(true))
    .addStringOption((o) => o.setName('reason').setDescription('Shown to anyone who tries to trade')),
  async run(interaction) {
    await interaction.deferReply();
    const locked = interaction.options.getBoolean('locked');
    await api.patchLeague(interaction, {
      trades_locked: locked,
      trades_locked_reason: interaction.options.getString('reason') || null,
    });
    await interaction.editReply(locked ? '🔒 Trading is now locked.' : '🔓 Trading is open.');
  },
};

// ---------------------------------------------------------------------------
// Looking things up
// ---------------------------------------------------------------------------

commands['roster'] = {
  data: new SlashCommandBuilder()
    .setName('roster')
    .setDescription("Show a team's roster.")
    .addStringOption((o) => o.setName('team').setDescription('Team (default: yours)').setAutocomplete(true)),
  autocomplete: teamChoices,
  async run(interaction) {
    await interaction.deferReply();
    let teamRef = interaction.options.getString('team');
    if (!teamRef) {
      const me = await api.getMembership(interaction);
      if (!me.team) return interaction.editReply(ephemeral("You don't run a team — name one: `/roster team:Knicks`"));
      teamRef = me.team.name;
    }
    const data = await api.getRoster(interaction.guildId, teamRef);
    await interaction.editReply({ embeds: [rosterEmbed(data.team, data.players, data.team.roster_target)] });
  },
};

commands['player'] = {
  data: new SlashCommandBuilder()
    .setName('player')
    .setDescription('Find out who has a player.')
    .addStringOption((o) => o.setName('name').setDescription('Player').setRequired(true).setAutocomplete(true)),
  autocomplete: playerChoices,
  async run(interaction) {
    await interaction.deferReply();
    const name = interaction.options.getString('name');
    const { players } = await api.searchPlayers(interaction.guildId, name);
    if (!players.length) return interaction.editReply(`No player called "${name}".`);
    const exact = players.find((p) => p.name.toLowerCase() === name.toLowerCase());
    await interaction.editReply({ embeds: [playerEmbed(exact || players[0])] });
  },
};

commands['freeagents'] = {
  data: new SlashCommandBuilder()
    .setName('freeagents')
    .setDescription('List the free agent pool.')
    .addStringOption((o) =>
      o.setName('position').setDescription('Filter by position')
        .addChoices(...['PG', 'SG', 'SF', 'PF', 'C'].map((p) => ({ name: p, value: p })))),
  async run(interaction) {
    await interaction.deferReply();
    const { players } = await api.getFreeAgents(interaction.guildId, interaction.options.getString('position'));
    if (!players.length) return interaction.editReply('The free agent pool is empty.');

    const lines = players.slice(0, 40).map((p) => {
      const pos = (p.position || '--').padEnd(2);
      const ovr = p.ovr ? String(p.ovr).padStart(2) : '--';
      return `\`${pos} ${ovr}\`  ${p.name}`;
    });
    const embed = new EmbedBuilder()
      .setColor(PURPLE)
      .setTitle('Free agents')
      .setDescription(lines.join('\n').slice(0, 4000))
      .setFooter({ text: players.length > 40 ? `Showing 40 of ${players.length}` : `${players.length} available` });
    await interaction.editReply({ embeds: [embed] });
  },
};

commands['mytrades'] = {
  data: new SlashCommandBuilder().setName('mytrades').setDescription('Your pending trades.'),
  async run(interaction) {
    await interaction.deferReply({ flags: MessageFlags.Ephemeral });
    const me = await api.getMembership(interaction);
    const { trades } = await api.getTrades(interaction.guildId, 'open');
    const mine = me.team
      ? trades.filter((t) => t.proposer_team.id === me.team.id || t.counterparty_team.id === me.team.id)
      : trades;
    if (!mine.length) return interaction.editReply('Nothing pending.');
    await interaction.editReply({ embeds: mine.slice(0, 8).map((t) => tradeEmbed(t)) });
  },
};

// ---------------------------------------------------------------------------
// Trading
// ---------------------------------------------------------------------------

commands['trade'] = {
  data: new SlashCommandBuilder()
    .setName('trade')
    .setDescription('Propose a trade. Add a third team for a three-way.')
    .addStringOption((o) =>
      o.setName('team').setDescription('Who you want to trade with').setRequired(true).setAutocomplete(true))
    .addStringOption((o) =>
      o.setName('team3').setDescription('Optional third team, for a three-way').setAutocomplete(true)),
  autocomplete: teamChoices,
  async run(interaction) {
    // A modal must be the first reply, so this cannot be deferred.
    const team = interaction.options.getString('team');
    const team3 = interaction.options.getString('team3');

    if (team3) {
      // With three teams "send" and "receive" are ambiguous, so ask for the
      // moves directly. Each player's current team is the origin, so the line
      // only has to say where he is going.
      const modal = new ModalBuilder()
        .setCustomId(`mynba:proposemodal3:${team}|${team3}`)
        .setTitle('Three-team trade'.slice(0, 45))
        .addComponents(
          new ActionRowBuilder().addComponents(
            new TextInputBuilder()
              .setCustomId('moves')
              .setLabel('Moves, one per line')
              .setPlaceholder('Michael Jordan > Knicks\nPatrick Ewing > Lakers')
              .setStyle(TextInputStyle.Paragraph)
              .setRequired(true)),
          new ActionRowBuilder().addComponents(
            new TextInputBuilder()
              .setCustomId('note')
              .setLabel('Note (optional)')
              .setStyle(TextInputStyle.Short)
              .setRequired(false)),
        );
      return interaction.showModal(modal);
    }

    const modal = new ModalBuilder()
      .setCustomId(`mynba:proposemodal:${team}`)
      .setTitle(`Trade with the ${team}`.slice(0, 45))
      .addComponents(
        new ActionRowBuilder().addComponents(
          new TextInputBuilder()
            .setCustomId('send')
            .setLabel('Players you send')
            .setPlaceholder('One per line, or comma separated')
            .setStyle(TextInputStyle.Paragraph)
            .setRequired(false)),
        new ActionRowBuilder().addComponents(
          new TextInputBuilder()
            .setCustomId('receive')
            .setLabel('Players you want back')
            .setPlaceholder('One per line, or comma separated')
            .setStyle(TextInputStyle.Paragraph)
            .setRequired(false)),
        new ActionRowBuilder().addComponents(
          new TextInputBuilder()
            .setCustomId('note')
            .setLabel('Note (optional)')
            .setStyle(TextInputStyle.Short)
            .setRequired(false)),
      );
    await interaction.showModal(modal);
  },
};

commands['sign'] = {
  data: new SlashCommandBuilder()
    .setName('sign')
    .setDescription('Sign a free agent to your team.')
    .addStringOption((o) => o.setName('player').setDescription('Player').setRequired(true).setAutocomplete(true)),
  autocomplete: playerChoices,
  async run(interaction) {
    await interaction.deferReply();
    const name = interaction.options.getString('player');
    const player = await api.signPlayer(interaction, name, {});
    await interaction.editReply(`✅ **${player.player.name}** signed with the ${player.player.team}.`);
  },
};

commands['release'] = {
  data: new SlashCommandBuilder()
    .setName('release')
    .setDescription('Release one of your players to free agency.')
    .addStringOption((o) => o.setName('player').setDescription('Player').setRequired(true).setAutocomplete(true)),
  autocomplete: playerChoices,
  async run(interaction) {
    await interaction.deferReply();
    const name = interaction.options.getString('player');
    const result = await api.releasePlayer(interaction, name, {});
    await interaction.editReply(`**${result.player.name}** is a free agent.`);
  },
};

/** Handle the modal that /trade opens. */
async function handleProposeModal(interaction, teamName) {
  await interaction.deferReply();
  const send = parseNames(interaction.fields.getTextInputValue('send'));
  const receive = parseNames(interaction.fields.getTextInputValue('receive'));
  const note = interaction.fields.getTextInputValue('note') || null;

  if (!send.length && !receive.length) {
    return interaction.editReply(ephemeral('A trade needs at least one player on one side.'));
  }

  const { trade, warnings } = await api.proposeTrade(interaction, {
    with_team: teamName,
    send,
    receive,
    note,
  });

  const pending = (trade.teams || []).filter((t) => !t.accepted && !t.declined);
  const mention = pending.map((t) => (t.gm_discord_id ? `<@${t.gm_discord_id}>` : t.name)).join(' ');
  await interaction.editReply({
    content: `${mention ? mention + ' — ' : ''}${trade.ref} is up for review.`,
    embeds: [tradeEmbed(trade, { warnings })],
    components: tradeButtons(trade),
  });
}

// Ratings commands live in their own module; merged in so registration and
// dispatch see one command map.
Object.assign(commands, require('./ratings').commands);

/** "Michael Jordan > Knicks" — origin comes from whoever holds him today. */
function parseMoves(raw) {
  return String(raw || '')
    .split(NEWLINE)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [player, to] = line.split(/[>→]/).map((part) => (part || '').trim());
      return player && to ? { player, to } : null;
    })
    .filter(Boolean);
}

/** Handle the three-team modal. */
async function handleProposeModal3(interaction, teamsRaw) {
  await interaction.deferReply();
  const moves = parseMoves(interaction.fields.getTextInputValue('moves'));
  const note = interaction.fields.getTextInputValue('note') || null;

  if (!moves.length) {
    return interaction.editReply(ephemeral(
      'I could not read any moves. Use one line per player, like `Michael Jordan > Knicks`.'
    ));
  }

  const { trade, warnings } = await api.proposeTrade(interaction, { moves, note });
  const pending = (trade.teams || []).filter((t) => !t.accepted && !t.declined);
  const mentions = pending
    .map((t) => (t.gm_discord_id ? `<@${t.gm_discord_id}>` : t.name))
    .join(' ');

  await interaction.editReply({
    content: `${mentions ? mentions + ' — ' : ''}${trade.ref} needs your sign-off.`,
    embeds: [tradeEmbed(trade, { warnings })],
    components: tradeButtons(trade),
  });
}

module.exports = { commands, handleProposeModal, handleProposeModal3, parseNames, parseMoves, ephemeral };
