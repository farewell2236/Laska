'use strict';

const OPTIONS = ['未設定','正規','MIRROR','RANDOM','R-RANDOM','S-RANDOM','H-RANDOM'];
const ORDER = [
  '未定','地力S+','個人差S+','地力S','個人差S','地力A+','個人差A+',
  '地力A','個人差A','地力B+','個人差B+','地力B','個人差B',
  '地力C','個人差C','地力D','個人差D','地力E','個人差E',
  '地力F','個人差F','未分類'
];
const OPT_KEY = 'iidx_sp12_options_actions_v1';
const MODE_KEY = 'iidx_sp12_mode_actions_v1';

const $ = (selector) => document.querySelector(selector);
const clean = (value) => String(value ?? '').replace(/\s+/g, ' ').trim();
const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (char) => ({
  '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
}[char]));

const data = window.IIDX_SP12_DATA || { normal: [], hard: [], generatedAt: null };
let mode = localStorage.getItem(MODE_KEY) || 'normal';
let options = safeParse(localStorage.getItem(OPT_KEY), {});

function safeParse(text, fallback) {
  try { return text ? JSON.parse(text) : fallback; }
  catch { return fallback; }
}
function save() {
  localStorage.setItem(OPT_KEY, JSON.stringify(options));
  localStorage.setItem(MODE_KEY, mode);
}
function optionKey(song) {
  return `${mode}::${song.title}::${song.chart || ''}`;
}
function getOption(song) {
  return options[optionKey(song)] || '未設定';
}
function currentList() {
  return Array.isArray(data[mode]) ? data[mode] : [];
}
function switchMode(nextMode) {
  mode = nextMode;
  save();
  render();
}
function render() {
  $('#normalBtn').classList.toggle('active', mode === 'normal');
  $('#hardBtn').classList.toggle('active', mode === 'hard');

  const list = currentList();
  const query = clean($('#search').value).toLowerCase();
  const filter = $('#optionFilter').value;

  if (!list.length) {
    $('#summary').innerHTML = '';
    $('#status').className = 'error';
    $('#status').textContent =
      '曲データがまだ生成されていません。GitHubのActionsで「Update difficulty data」を実行してください。';
    $('#app').innerHTML = `
      <section class="notice">
        <strong>データ未生成</strong><br>
        GitHubで <code>Actions → Update difficulty data → Run workflow</code> を実行してください。
        成功すると <code>data/songs.js</code> と <code>data/songs.json</code> が自動更新されます。
      </section>`;
    return;
  }

  const shown = list.filter((song) =>
    (!query || song.title.toLowerCase().includes(query)) &&
    (!filter || getOption(song) === filter)
  );

  const groups = new Map(ORDER.map((rank) => [rank, []]));
  shown.forEach((song) => (groups.get(song.rank) || groups.get('未分類')).push(song));

  $('#app').innerHTML = [...groups]
    .filter(([, songs]) => songs.length)
    .map(([rank, songs]) => `
      <section class="group">
        <button class="group-title">
          <strong>${escapeHtml(rank)}</strong><span>${songs.length}譜面 ▾</span>
        </button>
        <div class="rows">
          ${songs.sort((a,b) => a.title.localeCompare(b.title, 'ja')).map((song) => `
            <div class="row">
              <span class="ver">${escapeHtml(song.ver || '-')}</span>
              <span class="title">${escapeHtml(song.title)}${song.chart ? ` <small>${escapeHtml(song.chart)}</small>` : ''}</span>
              <select class="option-select" data-key="${escapeHtml(optionKey(song))}">
                ${OPTIONS.map((option) =>
                  `<option${getOption(song) === option ? ' selected' : ''}>${option}</option>`
                ).join('')}
              </select>
            </div>`).join('')}
        </div>
      </section>`).join('') || '<div class="empty">該当曲なし</div>';

  document.querySelectorAll('.group-title').forEach((button) => {
    button.addEventListener('click', () => button.parentElement.classList.toggle('closed'));
  });
  document.querySelectorAll('.option-select').forEach((select) => {
    select.addEventListener('change', () => {
      options[select.dataset.key] = select.value;
      save();
      render();
    });
  });

  $('#summary').innerHTML =
    `<span class="badge">全 ${list.length}譜面</span>` +
    OPTIONS.map((option) =>
      `<span class="badge">${option}: ${list.filter((song) => getOption(song) === option).length}</span>`
    ).join('');

  const generated = data.generatedAt ? new Date(data.generatedAt).toLocaleString('ja-JP') : '不明';
  $('#status').className = '';
  $('#status').textContent =
    `${mode === 'normal' ? 'ノマゲ' : 'ハード'} ${list.length}譜面を表示中。データ生成: ${generated}`;
}

function exportData() {
  const blob = new Blob(
    [JSON.stringify({ options, exportedAt: new Date().toISOString() }, null, 2)],
    { type: 'application/json' }
  );
  const anchor = document.createElement('a');
  anchor.href = URL.createObjectURL(blob);
  anchor.download = 'IIDX_SP12_options_backup.json';
  anchor.click();
  URL.revokeObjectURL(anchor.href);
}
async function importData(file) {
  try {
    const parsed = JSON.parse(await file.text());
    if (!parsed.options || typeof parsed.options !== 'object') throw new Error('optionsがありません');
    options = parsed.options;
    save();
    render();
  } catch (error) {
    $('#status').className = 'error';
    $('#status').textContent = `バックアップを読み込めませんでした: ${error.message}`;
  }
}

$('#normalBtn').addEventListener('click', () => switchMode('normal'));
$('#hardBtn').addEventListener('click', () => switchMode('hard'));
$('#search').addEventListener('input', render);
$('#optionFilter').addEventListener('change', render);
$('#exportBtn').addEventListener('click', exportData);
$('#importBtn').addEventListener('click', () => $('#importFile').click());
$('#importFile').addEventListener('change', (event) => {
  if (event.target.files[0]) importData(event.target.files[0]);
});
$('#resetBtn').addEventListener('click', () => {
  if (confirm('すべてのオプションを未設定に戻しますか？')) {
    options = {};
    save();
    render();
  }
});
$('#optionFilter').innerHTML =
  '<option value="">全オプション</option>' +
  OPTIONS.map((option) => `<option>${option}</option>`).join('');

render();
