// Where the inbox lives, and how we talk to it. Nothing here leaves your machine:
// the extension only ever calls YOUR Smelt server.

export const DEFAULTS = { endpoint: 'http://127.0.0.1:8130', token: '', lens: 'digest' };

export async function settings() {
  return { ...DEFAULTS, ...(await chrome.storage.sync.get(DEFAULTS)) };
}

export function kindOf(url) {
  return /youtube\.com|youtu\.be/i.test(url) ? 'youtube' : 'url';
}

export async function digest({ value, kind, lens }) {
  const { endpoint, token, lens: fallback } = await settings();
  const headers = { 'content-type': 'application/json' };
  if (token) headers['x-smelt-token'] = token;

  const res = await fetch(`${endpoint.replace(/\/$/, '')}/intake`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ kind: kind || kindOf(value), value, lens: lens || fallback }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.error) throw new Error(data.error || `Smelt returned ${res.status}`);
  return data;
}

export async function verdict(id, v) {
  const { endpoint, token } = await settings();
  const headers = { 'content-type': 'application/json' };
  if (token) headers['x-smelt-token'] = token;

  const res = await fetch(`${endpoint.replace(/\/$/, '')}/feedback`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ id, verdict: v }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.error) throw new Error(data.error || `Smelt returned ${res.status}`);
  return data;
}
