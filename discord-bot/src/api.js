'use strict';

/**
 * Thin client for the league API.
 *
 * The bot never decides who may do what — it passes the acting Discord user to
 * the backend, which checks the database. Discord role checks in this bot are
 * for fast feedback only.
 */

const API_BASE_URL = (process.env.API_BASE_URL || 'http://127.0.0.1:5000').replace(/\/$/, '');
const RAW_AUTH = (process.env.API_AUTH_HEADER || '').trim();
const AUTH_HEADER = RAW_AUTH.startsWith('Bearer ') ? RAW_AUTH : RAW_AUTH ? `Bearer ${RAW_AUTH}` : '';

const DEFAULT_TIMEOUT_MS = 15000;

class ApiError extends Error {
  constructor(message, { status, code, candidates } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.candidates = candidates;
  }
}

async function call(path, { method = 'GET', body, timeout = DEFAULT_TIMEOUT_MS } = {}) {
  const headers = {};
  if (AUTH_HEADER) headers['Authorization'] = AUTH_HEADER;
  if (body) headers['Content-Type'] = 'application/json';

  const res = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(timeout),
  });

  const text = await res.text().catch(() => '');
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch (_) {
    // Non-JSON body — surface the status instead of a parse error.
  }

  if (!res.ok) {
    const message = (data && data.error) || `API ${res.status}`;
    throw new ApiError(message, {
      status: res.status,
      code: data && data.code,
      candidates: data && data.candidates,
    });
  }
  return data || {};
}

const withActor = (interaction, body = {}) => ({
  ...body,
  guild_id: interaction.guildId,
  actor_discord_id: interaction.user.id,
  actor_display_name: interaction.user.displayName || interaction.user.username,
});

const qs = (params) => {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value));
  }
  const s = search.toString();
  return s ? `?${s}` : '';
};

module.exports = {
  ApiError,
  API_BASE_URL,
  AUTH_HEADER,
  call,
  withActor,

  createLeague: (interaction, body) =>
    call('/api/mynba/leagues', { method: 'POST', body: withActor(interaction, body) }),

  getMembership: (interaction) =>
    call(`/api/mynba/me${qs({ guild_id: interaction.guildId, actor_discord_id: interaction.user.id })}`),

  getTeams: (guildId) => call(`/api/mynba/teams${qs({ guild_id: guildId })}`),

  getRoster: (guildId, teamRef) =>
    call(`/api/mynba/teams/${encodeURIComponent(teamRef)}/roster${qs({ guild_id: guildId })}`),

  searchPlayers: (guildId, q, teamId) =>
    call(`/api/mynba/players/search${qs({ guild_id: guildId, q, team_id: teamId, limit: 25 })}`),

  getFreeAgents: (guildId, position) =>
    call(`/api/mynba/free-agents${qs({ guild_id: guildId, position })}`),

  getTrades: (guildId, status = 'open') =>
    call(`/api/mynba/trades${qs({ guild_id: guildId, status })}`),

  importRosters: (interaction, csv, { dryRun } = {}) =>
    call(`/api/mynba/import${qs({ guild_id: interaction.guildId, dry_run: dryRun ? 1 : '' })}`, {
      method: 'POST',
      body: withActor(interaction, { csv }),
      timeout: 60000,
    }),

  setTeamGm: (interaction, teamId, body) =>
    call(`/api/mynba/teams/${teamId}/gm`, { method: 'POST', body: withActor(interaction, body) }),

  addCommissioner: (interaction, body) =>
    call('/api/mynba/commissioners', { method: 'POST', body: withActor(interaction, body) }),

  patchLeague: (interaction, body) =>
    call('/api/mynba/league', { method: 'PATCH', body: withActor(interaction, body) }),

  proposeTrade: (interaction, body) =>
    call('/api/mynba/trades', { method: 'POST', body: withActor(interaction, body) }),

  tradeAction: (interaction, ref, action, body = {}) =>
    call(`/api/mynba/trades/${encodeURIComponent(ref)}/${action}`, {
      method: 'POST',
      body: withActor(interaction, body),
    }),

  signPlayer: (interaction, playerRef, body) =>
    call(`/api/mynba/players/${encodeURIComponent(playerRef)}/sign`, {
      method: 'POST',
      body: withActor(interaction, body),
    }),

  releasePlayer: (interaction, playerRef, body) =>
    call(`/api/mynba/players/${encodeURIComponent(playerRef)}/release`, {
      method: 'POST',
      body: withActor(interaction, body),
    }),

  sweep: (guildId) => call('/api/mynba/sweep', { method: 'POST', body: { guild_id: guildId } }),

  syncRatings: (guildId, era = 'curr', triggeredBy = 'schedule') =>
    call('/api/mynba/ratings/sync', {
      method: 'POST',
      body: { guild_id: guildId, era, triggered_by: triggeredBy },
      timeout: 180000,
    }),

  syncBadges: (interaction, limit = null) =>
    call('/api/mynba/ratings/badges', {
      method: 'POST',
      body: withActor(interaction, limit ? { limit } : {}),
      timeout: 300000,
    }),

  ratingsStatus: (guildId) =>
    call(`/api/mynba/ratings/status${qs({ guild_id: guildId })}`),

  seedRosters: (interaction, body) =>
    call('/api/mynba/ratings/seed-rosters', {
      method: 'POST',
      body: withActor(interaction, body),
      timeout: 120000,
    }),

  playerCard: (guildId, name) =>
    call(`/api/mynba/players/${encodeURIComponent(name)}/card${qs({ guild_id: guildId })}`),

  health: () => call(process.env.API_HEALTH_PATH || '/api/health'),
};
