import { digest, kindOf, settings, verdict } from './shared.js';

const LENSES = [
  ['digest', 'digest — balanced'],
  ['wisdom', 'wisdom — insights'],
  ['critique', 'critique — weak points'],
  ['study', 'study — key concepts'],
  ['actions', 'actions — next steps'],
];

const $ = (id) => document.getElementById(id);
let tabUrl = '';
let noteId = null;

(async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  tabUrl = tab?.url || '';
  $('target').textContent = tab?.title || tabUrl || '(no page)';
  $('target').title = tabUrl;

  const { lens } = await settings();
  $('lens').innerHTML = LENSES.map(([v, label]) =>
    `<option value="${v}"${v === lens ? ' selected' : ''}>${label}</option>`).join('');

  if (!/^https?:/i.test(tabUrl)) {
    $('go').disabled = true;
    $('target').textContent = 'Only http(s) pages can be digested.';
  }
})();

$('go').addEventListener('click', async () => {
  $('err').style.display = 'none';
  $('go').disabled = true;
  $('go').textContent = 'Digesting…';
  try {
    const note = await digest({ value: tabUrl, kind: kindOf(tabUrl), lens: $('lens').value });
    noteId = note.id;
    $('badges').style.display = 'flex';
    $('badges').innerHTML =
      `<span class="badge">domain <b>${note.domain}</b></span>` +
      `<span class="badge">proposal <b>${note.action}</b></span>` +
      `<span class="badge">conf <b>${note.confidence}</b></span>` +
      (note.reingested ? '<span class="badge">re-read</span>' : '') +
      '<span class="badge warn">unverified</span>';
    $('reason').style.display = 'block';
    $('reason').textContent = note.reason;
    $('verdict').style.display = 'flex';
    $('go').textContent = 'Digest again';
  } catch (err) {
    $('err').style.display = 'block';
    $('err').textContent = `${err.message} — is \`smelt serve\` running?`;
    $('go').textContent = 'Digest';
  } finally {
    $('go').disabled = false;
  }
});

for (const [id, v] of [['keep', 'kept'], ['drop', 'dropped']]) {
  $(id).addEventListener('click', async () => {
    if (!noteId) return;
    try {
      const res = await verdict(noteId, v);
      $(id).classList.add('done');
      $(id).textContent = `${v} · ${res.judged}`;
    } catch (err) {
      $('err').style.display = 'block';
      $('err').textContent = err.message;
    }
  });
}

$('opts').addEventListener('click', (e) => {
  e.preventDefault();
  chrome.runtime.openOptionsPage();
});
