'use strict';

/**
 * How a trade looks in Discord.
 *
 * Button custom ids are `mynba:<action>:<trade ref>`. The ref is the whole
 * state — nothing lives in bot memory, so a restart never orphans a card.
 */

const { EmbedBuilder, ActionRowBuilder, ButtonBuilder, ButtonStyle } = require('discord.js');

const PURPLE = 0x8b5cf6;
const GREEN = 0x34d399;
const RED = 0xfb7185;
const AMBER = 0xfbbf24;
const GREY = 0x4b5563;

const STATUS_COLOR = {
  PENDING_GM: PURPLE,
  PENDING_COMMISSIONER: PURPLE,
  APPROVED_WINDOW: GREEN,
  PROTESTED: AMBER,
  EXECUTED: GREEN,
  VOIDED: AMBER,
  DECLINED: GREY,
  VETOED: RED,
  CANCELLED: GREY,
  EXPIRED: GREY,
  OVERTURNED: RED,
};

const list = (names) => (names && names.length ? names.map((n) => `• ${n}`).join('\n') : '_nobody_');

function tradeEmbed(trade, { warnings = [] } = {}) {
  const teams = trade.teams || [];
  const threeWay = (trade.team_count || teams.length) > 2;

  const title = threeWay
    ? `${trade.ref} — ${teams.map((t) => t.abbrev || t.name).join(' / ')} (${trade.team_count}-team)`
    : `${trade.ref} — ${trade.proposer_team.name} ⇄ ${trade.counterparty_team.name}`;

  const embed = new EmbedBuilder()
    .setColor(STATUS_COLOR[trade.status] || PURPLE)
    .setTitle(title)
    .setDescription(trade.status_label);

  if (threeWay && trade.movement) {
    // Two columns per team don't fit; one field per team, each saying where
    // its players go and where its incoming players came from.
    for (const side of trade.movement) {
      const out = side.sends.length
        ? side.sends.map((m) => `↗ ${m.player} → ${m.team}`).join('\n')
        : '↗ _nobody_';
      const inn = side.gets.length
        ? side.gets.map((m) => `↘ ${m.player} ← ${m.team}`).join('\n')
        : '↘ _nobody_';
      embed.addFields({ name: side.team, value: `${out}\n${inn}`.slice(0, 1000) });
    }
  } else {
    embed.addFields(
      { name: `${trade.proposer_team.name} send`, value: list(trade.sending), inline: true },
      { name: `${trade.counterparty_team.name} send`, value: list(trade.receiving), inline: true },
    );
  }

  if (teams.length) {
    const state = teams.map((t) => {
      if (t.declined) return `✖ ${t.name}`;
      if (t.is_proposer) return `● ${t.name} (proposed)`;
      if (t.is_cpu) return `○ ${t.name} (CPU)`;
      return t.accepted ? `✔ ${t.name}` : `… ${t.name}`;
    });
    embed.addFields({ name: 'Sign-off', value: state.join('\n').slice(0, 1000) });
  }

  if (trade.note) embed.addFields({ name: 'Note', value: trade.note.slice(0, 1000) });
  if (warnings.length) embed.addFields({ name: 'Heads up', value: warnings.join('\n').slice(0, 1000) });
  if (trade.resolution_reason) {
    embed.addFields({ name: 'Why', value: String(trade.resolution_reason).slice(0, 1000) });
  }
  if (trade.votes) {
    embed.addFields({
      name: 'League vote',
      value: `${trade.votes.uphold} to keep it · ${trade.votes.overturn} to kill it` +
        (trade.votes.eligible ? ` · ${trade.votes.eligible} GMs can vote` : ''),
    });
  }
  if (trade.execute_after) {
    const unix = Math.floor(new Date(`${trade.execute_after}Z`).getTime() / 1000);
    embed.addFields({ name: 'Goes through', value: `<t:${unix}:R> unless someone protests` });
  }
  return embed;
}


const button = (action, ref, label, style) =>
  new ButtonBuilder().setCustomId(`mynba:${action}:${ref}`).setLabel(label).setStyle(style);

/** Buttons for whichever stage the trade is at. Empty array means no action left. */
function tradeButtons(trade) {
  switch (trade.status) {
    case 'PENDING_GM':
      return [new ActionRowBuilder().addComponents(
        button('accept', trade.ref, 'Accept', ButtonStyle.Success),
        button('decline', trade.ref, 'Decline', ButtonStyle.Danger),
        button('cancel', trade.ref, 'Withdraw', ButtonStyle.Secondary),
      )];
    case 'PENDING_COMMISSIONER':
      return [new ActionRowBuilder().addComponents(
        button('approve', trade.ref, 'Approve', ButtonStyle.Success),
        button('veto', trade.ref, 'Veto', ButtonStyle.Danger),
      )];
    case 'APPROVED_WINDOW':
      return [new ActionRowBuilder().addComponents(
        button('protest', trade.ref, 'Protest', ButtonStyle.Danger),
        button('execute', trade.ref, 'Execute now', ButtonStyle.Secondary),
      )];
    case 'PROTESTED':
      return [new ActionRowBuilder().addComponents(
        button('uphold', trade.ref, 'Let it stand', ButtonStyle.Success),
        button('overturn', trade.ref, 'Overturn', ButtonStyle.Danger),
        button('closevote', trade.ref, 'Close the vote', ButtonStyle.Secondary),
      )];
    default:
      return [];
  }
}

function rosterEmbed(team, players, rosterTarget) {
  const lines = players.length
    ? players.map((p) => {
        const pos = (p.position || '--').padEnd(2);
        const ovr = p.ovr ? String(p.ovr).padStart(2) : '--';
        return `\`${pos} ${ovr}\`  ${p.name}`;
      })
    : ['_No players imported for this team yet._'];

  const off = rosterTarget && players.length !== rosterTarget;
  return new EmbedBuilder()
    .setColor(off ? AMBER : PURPLE)
    .setTitle(team.full_name || team.name)
    .setDescription(lines.join('\n').slice(0, 4000))
    .setFooter({
      text: `${players.length} players${rosterTarget ? ` · target ${rosterTarget}` : ''}` +
        (team.is_cpu ? ' · CPU team' : team.gm_display_name ? ` · GM ${team.gm_display_name}` : ''),
    });
}

function playerEmbed(player) {
  const where = player.is_free_agent ? 'Free agent' : player.team;
  return new EmbedBuilder()
    .setColor(player.is_free_agent ? GREY : PURPLE)
    .setTitle(player.name)
    .addFields(
      { name: 'Team', value: where || '—', inline: true },
      { name: 'Position', value: player.position || '—', inline: true },
      { name: 'OVR', value: player.ovr ? String(player.ovr) : '—', inline: true },
    );
}

module.exports = { tradeEmbed, tradeButtons, rosterEmbed, playerEmbed, PURPLE, GREEN, RED, AMBER, GREY };
