const $ = id => document.getElementById(id);
let snapshot;
function choices(el, values) {
  const old = el.value;
  el.replaceChildren(...values.map(v => new Option(v === '*' ? 'همه' : v, v)));
  if (values.includes(old)) el.value = old;
  else if (values.includes('*')) el.value = '*';
  el.disabled = !values.length;
}
function render() {
  $('coverage').replaceChildren(...snapshot.exchanges.map(exchange => {
    const state = snapshot.sources?.[exchange.id];
    const node = document.createElement('div');
    node.className = 'source-card';
    const stale = !state?.last_success || Date.now() - Date.parse(state.last_success) > snapshot.stale_after_seconds * 1000;
    const label = !state ? 'هنوز بررسی نشده' : state.status === 'error' ? 'دریافت ناموفق' : state.status === 'stale' || stale ? 'اطلاعات قدیمی' : 'دریافت موفق';
    node.textContent = `${exchange.name} · ${label}`;
    return node;
  }));
  const selected = snapshot.rows.filter(r => ($('asset').value === '*' || r.asset === $('asset').value) && ($('network').value === '*' || r.network === $('network').value));
  selected.sort((a,b) => a.asset.localeCompare(b.asset) || a.network.localeCompare(b.network) || a.exchange.localeCompare(b.exchange));
  $('rows').replaceChildren(...selected.map(row => {
    const exchange = snapshot.exchanges.find(e => e.id === row.exchange);
    const tr = document.createElement('tr');
    const source = snapshot.sources?.[exchange.id];
    const stale = row && Date.now() - Date.parse(row.updated_at) > snapshot.stale_after_seconds * 1000;
    const values = [exchange.name, row.asset, row.network_label || row.network, row?.fee_kind === 'percent' ? `${Number(row.fee_rate) * 100}٪ از مبلغ برداشت` : row?.fee == null ? 'نامشخص' : `${row.fee} ${row.fee_currency}`, row?.minimum == null ? 'نامشخص' : `${row.minimum} ${row.asset}`, row?.withdrawal_enabled == null ? 'نامشخص' : row.withdrawal_enabled ? 'فعال' : 'متوقف', row ? `${new Date(row.updated_at).toLocaleString('fa-IR')}${stale ? ' — قدیمی' : ''}${source?.status === 'error' ? ' — دریافت ناموفق' : ''}` : source?.status === 'error' ? 'دریافت ناموفق؛ داده نداریم' : 'در دادهٔ این صرافی موجود نیست'];
    values.forEach(v => { const td = document.createElement('td'); td.textContent = v; tr.append(td); });
    if (row) {
      const link = document.createElement('a'); link.href = row.source; link.textContent = 'منبع'; link.target = '_blank'; link.rel = 'noopener noreferrer';
      tr.lastChild.append(document.createElement('br'), link);
    }
    return tr;
  }));
}
function networks() {
  choices($('network'), ['*', ...new Set(snapshot.rows.filter(r => $('asset').value === '*' || r.asset === $('asset').value).map(r => r.network))].sort());
  render();
}
async function refresh() {
  if ($('refresh').disabled) return;
  $('refresh').disabled = true;
  try {
    const response = await fetch('./fees.json', {cache: 'no-store'});
    if (!response.ok) throw new Error('unavailable');
    snapshot = await response.json();
    choices($('asset'), ['*', ...new Set(snapshot.rows.map(r => r.asset))].sort());
    networks();
    $('status').textContent = snapshot.rows.length ? 'دریافت زمان‌بندی‌شده تقریباً هر ۱۵ دقیقه؛ احتمال تأخیر وجود دارد. زمان داده و وضعیت هر منبع را بررسی کنید.' : 'هنوز دادهٔ تأییدشده‌ای ثبت نشده است. اتصال زنده به صرافی‌ها در حال آماده‌سازی است.';
  } catch {
    $('rows').replaceChildren();
    $('asset').disabled = $('network').disabled = true;
    $('status').textContent = 'دریافت اطلاعات ممکن نشد. دوباره تلاش کنید.';
  } finally { $('refresh').disabled = false; }
}
$('asset').addEventListener('change', networks);
$('network').addEventListener('change', render);
$('refresh').addEventListener('click', refresh);
refresh();
setInterval(refresh, 60000);
