'use strict';
const $ = id => document.getElementById(id);
const normalize = value => String(value).normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{N}]/gu, '');
let data, rows = [], byId, byCode, activeFilter = 'new', current = [], shown = 30, selected;
function element(tag, text, className) { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node; }
function setFilter(value) { activeFilter = value; document.querySelectorAll('[data-filter]').forEach(b => { const on = b.dataset.filter === value; b.classList.toggle('active', on); b.setAttribute('aria-pressed', String(on)); }); }
function search() {
  if (!data) return;
  shown = 30;
  const input = $('query').value.trim(), query = normalize(input), exact = byCode.get(query);
  if (query && activeFilter === 'new') setFilter('all');
  const indexed = new Set(data.search[query] || []);
  const unitQuery = data.unitQueries.includes(query);
  current = exact ? [exact] : rows.filter(r => !r.ended && (!query || (!unitQuery && (normalize(r.title).includes(query) || normalize(r.titleJp).includes(query))) || indexed.has(r.id)));
  if (!exact) {
    if (activeFilter === 'new') current = current.filter(r => r.isNew && r.releaseDate === data.latestRelease);
    else if (activeFilter === 'sortie') current = current.filter(r => r.category === 'sortie');
    else if (activeFilter !== 'all') current = current.filter(r => r.frequency === activeFilter);
  }
  $('results-title').textContent = input ? `'${input}' 검색 결과` : activeFilter === 'new' ? '최근 추가된 임무' : '임무 목록';
  $('status').textContent = activeFilter === 'new' && !query ? `${data.latestRelease || '날짜 미등록'} 점검 기준 · 자료에 등록된 최신 임무입니다.` : current.length ? '임무를 선택하면 상세 정보를 확인할 수 있어요.' : '검색 결과가 없어요. 다른 이름이나 정확한 임무 번호를 입력해보세요.';
  renderList();
  if (current.length === 1) openQuest(current[0], false);
  else if (!current.some(r => r.id === selected)) {
    selected = undefined;
    const heading = element('h2', current.length ? '임무를 선택해주세요.' : '다른 검색어로 찾아볼까요?'); heading.id = 'detail-title';
    $('detail').replaceChildren(element('p', 'MISSION BRIEFING', 'eyebrow'), heading, element('p', '목록에서 임무를 선택하면 조건·보상과 원문 공략 링크를 확인할 수 있어요.', 'empty-description'));
    history.replaceState(null, '', location.pathname + location.search);
  }
}
function renderList() {
  $('results').replaceChildren();
  $('result-count').textContent = `${current.length}개`;
  current.slice(0, shown).forEach(row => {
    const button = element('button', undefined, 'quest-row'); button.type = 'button'; button.classList.toggle('selected', selected === row.id); button.setAttribute('aria-pressed', String(selected === row.id));
    const meta = element('span', undefined, 'row-meta'); meta.append(element('span', row.code), element('span', row.frequencyLabel, 'badge')); if (row.limited) meta.append(element('span', row.ended ? '종료' : '기간한정', 'badge'));
    button.append(meta, element('strong', row.title)); button.addEventListener('click', () => openQuest(row, true)); $('results').append(button);
  });
  $('more').hidden = shown >= current.length;
}
function externalLink(text, url) {
  const parsed = new URL(url); if (parsed.protocol !== 'https:') throw new Error('Invalid public URL');
  const link = element('a', text); link.href = parsed.href; link.target = '_blank'; link.rel = 'noopener noreferrer'; return link;
}
function openQuest(row, scroll) {
  selected = row.id; renderList();
  const panel = $('detail'); panel.replaceChildren(element('p', `${row.code} · ${row.frequencyLabel}${row.ended ? ' · 종료' : ''}`, 'eyebrow'), element('h2', row.title)); panel.querySelector('h2').id = 'detail-title';
  panel.append(element('pre', row.detail.split('\n').slice(1).join('\n').trim(), 'detail-text'));
  for (const [label, ids] of [['선행임무 바로 보기', row.before], ['후속임무 바로 보기', row.after]]) {
    if (!ids.length) continue; const related = element('div', undefined, 'related'); related.append(element('span', label));
    ids.forEach(id => { const other = byId.get(id); if (!other) return; const b = element('button', other.code); b.type = 'button'; b.title = other.title; b.addEventListener('click', () => openQuest(other, true)); related.append(b); }); panel.append(related);
  }
  if (row.category === 'sortie') {
    const links = element('div', undefined, 'source-links');
    if (row.guideUrl) links.append(externalLink('제카마시 원문 공략 ↗', row.guideUrl));
    else panel.append(element('p', '연결된 전용 공략이 없습니다. 일반해역 원문에서 임무 조건에 맞는 편성을 확인하세요.', 'small-note'));
    [...new Set(row.maps.map(area => area.split('-').slice(0, 2).join('-')))].forEach(area => links.append(externalLink(`${area} 일반해역 원문 ↗`, `https://zekamashi.net/kancolle-kouryaku/${area}/`)));
    panel.append(links, element('p', '외부 사이트로 이동합니다. 원문의 최신 갱신 여부와 임무 조건을 함께 확인하세요.', 'small-note'));
  }
  history.replaceState(null, '', '#quest=' + encodeURIComponent(row.code));
  if (scroll && window.matchMedia('(max-width:760px)').matches) panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
}
$('search-form').addEventListener('submit', e => { e.preventDefault(); search(); });
document.querySelectorAll('[data-query]').forEach(b => b.addEventListener('click', () => { $('query').value = b.dataset.query; setFilter('all'); search(); }));
document.querySelectorAll('[data-filter]').forEach(b => b.addEventListener('click', () => { setFilter(b.dataset.filter); search(); }));
$('more').addEventListener('click', () => { shown += 30; renderList(); });
window.addEventListener('hashchange', () => {
  if (!byCode) return;
  const code = new URLSearchParams(location.hash.slice(1)).get('quest');
  if (code && byCode.has(normalize(code))) openQuest(byCode.get(normalize(code)), true);
});
fetch('data/quests.json').then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); }).then(result => {
  if (result.schema !== 1 || !Array.isArray(result.quests)) throw new Error('Invalid data schema');
  data = result; rows = data.quests; byId = new Map(rows.map(r => [r.id, r])); byCode = new Map();
  rows.forEach(r => [r.code, ...r.aliases].forEach(code => byCode.set(normalize(code), r)));
  data.latestRelease = rows.filter(r => r.isNew && !r.ended).map(r => r.releaseDate).sort().at(-1);
  $('catalog-count').textContent = `임무 ${rows.filter(r => !r.ended).length}개 수록`;
  const code = new URLSearchParams(location.hash.slice(1)).get('quest');
  $('search-button').disabled = false; search();
  if (code && byCode.has(normalize(code))) openQuest(byCode.get(normalize(code)), false);
}).catch(() => { $('status').textContent = '자료를 불러오지 못했어요. 새로고침해 주세요. 로컬 확인 시에는 HTTP 서버로 열어주세요.'; $('catalog-count').textContent = '불러오기 실패'; });
