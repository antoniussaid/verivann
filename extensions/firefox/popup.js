import { digest, kindOf, settings, verdict } from './shared.js';

const LENSES = [
  ['digest', 'digest - balanced'],
  ['wisdom', 'wisdom - insights'],
  ['critique', 'critique - weak points'],
  ['study', 'study - key concepts'],
  ['actions', 'actions - next steps'],
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
  const lensSel = $('lens');
  lensSel.textContent = '';
  for (const [v, label] of LENSES) lensSel.add(new Option(label, v, v === lens, v === lens));

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
    const badges = $('badges');
    badges.style.display = 'flex';
    badges.textContent = '';
    const badge = (label, value, cls) => {
      const span = document.createElement('span');
      span.className = cls ? `badge ${cls}` : 'badge';
      if (value === undefined) {
        span.textContent = label;
      } else {
        span.append(`${label} `);
        const b = document.createElement('b');
        b.textContent = value;
        span.append(b);
      }
      badges.append(span);
    };
    // note.* comes from the local inbox response; build with textContent so the
    // values can never be interpreted as markup
    badge('domain', note.domain);
    badge('proposal', note.action);
    badge('conf', note.confidence);
    if (note.reingested) badge('re-read');
    badge('unverified', undefined, 'warn');
    $('reason').style.display = 'block';
    $('reason').textContent = note.reason;
    $('verdict').style.display = 'flex';
    $('go').textContent = 'Digest again';
  } catch (err) {
    $('err').style.display = 'block';
    $('err').textContent = `${err.message} - is \`verivann serve\` running?`;
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
