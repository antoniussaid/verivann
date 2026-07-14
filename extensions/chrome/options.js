import { DEFAULTS, settings } from './shared.js';

const $ = (id) => document.getElementById(id);

(async () => {
  const current = await settings();
  for (const key of Object.keys(DEFAULTS)) $(key).value = current[key];
})();

$('save').addEventListener('click', async () => {
  const endpoint = $('endpoint').value.trim() || DEFAULTS.endpoint;
  await chrome.storage.sync.set({
    endpoint,
    token: $('token').value.trim(),
    lens: $('lens').value,
  });

  // A custom endpoint (e.g. the LAN address) is outside the manifest's host
  // permissions - ask for it explicitly, or the fetch would silently fail.
  try {
    const origin = new URL(endpoint).origin + '/*';
    const granted = await chrome.permissions.contains({ origins: [origin] });
    if (!granted) await chrome.permissions.request({ origins: [origin] });
  } catch { /* invalid URL: the popup will surface the error on first use */ }

  $('saved').classList.add('on');
  setTimeout(() => $('saved').classList.remove('on'), 1400);
});
