'use strict';

/**
 * Button handling for trade cards.
 *
 * Custom ids are `mynba:<action>:<ref>`. The API decides whether the clicker is
 * allowed to do it; a refusal comes back as a readable sentence, which we show
 * only to the person who clicked.
 */

const { MessageFlags } = require('discord.js');
const api = require('./api');
const { tradeEmbed, tradeButtons } = require('./embeds');

// action -> [api endpoint, past-tense confirmation]
const ACTIONS = {
  accept: ['accept', 'Accepted'],
  decline: ['decline', 'Declined'],
  cancel: ['cancel', 'Withdrawn'],
  approve: ['approve', 'Approved'],
  veto: ['veto', 'Vetoed'],
  protest: ['protest', 'Protested'],
  execute: ['execute', 'Executed'],
  closevote: ['resolve-protest', 'Vote closed'],
};

async function handleButton(interaction) {
  const [, action, ref] = interaction.customId.split(':');

  let endpoint;
  let confirmation;
  let body = {};

  if (action === 'uphold' || action === 'overturn') {
    endpoint = 'vote';
    confirmation = action === 'uphold' ? 'Voted to let it stand' : 'Voted to overturn';
    body = { uphold: action === 'uphold' };
  } else if (ACTIONS[action]) {
    [endpoint, confirmation] = ACTIONS[action];
  } else {
    return interaction.reply({ content: 'Unknown button.', flags: MessageFlags.Ephemeral });
  }

  await interaction.deferUpdate();

  let result;
  try {
    result = await api.tradeAction(interaction, ref, endpoint, body);
  } catch (err) {
    return interaction.followUp({
      content: `❌ ${err.message}`,
      flags: MessageFlags.Ephemeral,
    });
  }

  const trade = result.trade;

  // Re-render the card in place so it always shows the current stage.
  await interaction.editReply({
    content: nextStepLine(trade),
    embeds: [tradeEmbed(trade)],
    components: tradeButtons(trade),
  });

  await interaction.followUp({
    content: `${confirmation} — ${trade.ref}.`,
    flags: MessageFlags.Ephemeral,
  });

  return trade;
}

/** The line above the card: who the trade is waiting on now. */
function nextStepLine(trade) {
  switch (trade.status) {
    case 'PENDING_GM': {
      const gm = trade.counterparty_team.gm_discord_id;
      return gm ? `<@${gm}> — your call.` : `Waiting on the ${trade.counterparty_team.name}.`;
    }
    case 'PENDING_COMMISSIONER':
      return 'Both GMs agreed. Waiting on a commissioner.';
    case 'APPROVED_WINDOW':
      return 'Approved. Any other GM can protest before it goes through.';
    case 'PROTESTED':
      return 'Protested — the league is voting.';
    case 'EXECUTED':
      return '✅ Done. Rosters updated. Run it in-game when you get a chance.';
    case 'VOIDED':
      return '⚠️ Voided — a player had already moved.';
    default:
      return `${trade.ref} is closed.`;
  }
}

module.exports = { handleButton, nextStepLine };
