'use strict';

/**
 * Rec box-score ingestion — screenshots dropped in a registered channel get
 * queued and posted to /api/ingest one at a time.
 *
 * Moved out of index.js unchanged when the league commands arrived; the
 * behaviour is the same as before.
 */

const API_BASE_URL = (process.env.API_BASE_URL || 'http://127.0.0.1:5000').replace(/\/$/, '');
const RAW_AUTH = (process.env.API_AUTH_HEADER || '').trim();
const API_AUTH_HEADER = RAW_AUTH.startsWith('Bearer ') ? RAW_AUTH : RAW_AUTH ? `Bearer ${RAW_AUTH}` : '';
const INGEST_TIMEOUT_MS = 120000;

const queue = [];
let processing = false;

function isImageAttachment(attachment) {
  const ct = (attachment.contentType || '').toLowerCase();
  if (ct.startsWith('image/')) return true;
  const name = (attachment.name || '').toLowerCase();
  return /\.(png|jpe?g|webp|gif)$/.test(name);
}

async function runIngest(job) {
  const { attachment, authorId } = job;
  const res = await fetch(attachment.url, { signal: AbortSignal.timeout(15000) });
  if (!res.ok) throw new Error(`Could not download image (${res.status})`);
  const buf = await res.arrayBuffer();
  const contentType = attachment.contentType || 'image/png';
  const blob = new Blob([buf], { type: contentType });
  const form = new FormData();
  form.append('screenshot', blob, attachment.name || 'screenshot.png');
  form.append('uploader_discord_id', authorId);

  const headers = {};
  if (API_AUTH_HEADER) headers['Authorization'] = API_AUTH_HEADER;

  const ingestRes = await fetch(`${API_BASE_URL}/api/ingest`, {
    method: 'POST',
    headers,
    body: form,
    signal: AbortSignal.timeout(INGEST_TIMEOUT_MS),
  });

  // Read the body once, then parse — so the error path can still report it.
  const rawBody = await ingestRes.text().catch(() => '');
  let data = null;
  const ct = ingestRes.headers.get('content-type');
  if (ct && ct.includes('application/json')) {
    try {
      data = JSON.parse(rawBody);
    } catch (_) {}
  }

  if (!ingestRes.ok) {
    const detail = (data && (data.error || data.message)) || rawBody;
    throw new Error(`API ${ingestRes.status}${detail ? `: ${String(detail).slice(0, 300)}` : ''}`);
  }

  if (data && data.stored) return '✅ Game ingested successfully.';
  if (data && data.game_id) return '✅ Game already in database.';
  return '✅ Game ingested successfully.';
}

async function processQueue() {
  if (processing || queue.length === 0) return;
  processing = true;
  const job = queue.shift();
  try {
    const reply = await runIngest(job);
    await job.message.reply(reply);
  } catch (err) {
    console.error('[RecMetrics] Ingest job error:', err);
    try {
      const detail = err && err.message ? `: ${String(err.message).slice(0, 300)}` : '';
      await job.message.reply(`❌ Ingest failed${detail}`);
    } catch (_) {}
  } finally {
    processing = false;
    setImmediate(processQueue);
  }
}

function enqueue(message, attachment, authorId) {
  queue.push({ message, attachment, authorId });
}

module.exports = { isImageAttachment, enqueue, processQueue, runIngest };
