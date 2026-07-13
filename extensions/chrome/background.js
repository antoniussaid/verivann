// Right-click anything → it lands in Verivann. The badge is the whole feedback loop:
// a domain when it worked, "!" when the inbox is not running.

import { digest, kindOf } from './shared.js';

const MENUS = [
  { id: 'verivann-page', title: 'Verivann this page', contexts: ['page'] },
  { id: 'verivann-link', title: 'Verivann this link', contexts: ['link'] },
  { id: 'verivann-selection', title: 'Verivann selection', contexts: ['selection'] },
];

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => MENUS.forEach((m) => chrome.contextMenus.create(m)));
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  const selection = (info.selectionText || '').trim();
  const url = info.linkUrl || info.pageUrl || tab?.url || '';

  const payload = info.menuItemId === 'verivann-selection' && selection
    ? { value: selection, kind: 'text' }
    : { value: url, kind: kindOf(url) };

  await flash('…', '#33333a');
  try {
    const note = await digest(payload);
    await flash(note.domain.slice(0, 4), '#3a3a44');
  } catch (err) {
    await flash('!', '#7a3b3b');
    console.error('[verivann]', err.message);  // read via the service-worker console
  }
});

async function flash(text, color) {
  await chrome.action.setBadgeBackgroundColor({ color });
  await chrome.action.setBadgeText({ text });
  if (text !== '…') setTimeout(() => chrome.action.setBadgeText({ text: '' }), 4000);
}
