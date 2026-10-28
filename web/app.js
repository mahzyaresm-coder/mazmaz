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
  if ($('asset').value !== '*' && !snapshot.rows.some(r => r.asset === $('asset').value)) {
    $('status').textContent = $('asset').value === 'IRR' ? 'ریال شبکهٔ رمزارزی ندارد؛ کارمزد برداشت بانکی هنوز به این سامانه متصل نیست.' : 'برای این ارز هنوز دادهٔ تأییدشده‌ای از صرافی‌های انتخابی دریافت نشده است.';
  } else {
    $('status').textContent = 'نمایش فقط ارزهای انتخابی؛ زمان داده و وضعیت هر منبع را بررسی کنید.';
  }
  const selected = snapshot.rows.filter(r => ($('asset').value === '*' || r.asset === $('asset').value) && ($('network').value === '*' || r.network === $('network').value));
  selected.sort((a,b) => a.asset.localeCompare(b.asset) || a.network.localeCompare(b.network) || a.exchange.localeCompare(b.exchange));
  renderBlockchain();
  const exact = $('asset').value !== '*' && $('network').value !== '*';
  const displayRows = exact ? snapshot.exchanges.map(exchange => selected.find(r => r.exchange === exchange.id) || {exchange: exchange.id, asset: $('asset').value, network: $('network').value}) : selected;
  $('rows').replaceChildren(...displayRows.map(row => {
    const exchange = snapshot.exchanges.find(e => e.id === row.exchange);
    const tr = document.createElement('tr');
    const source = snapshot.sources?.[exchange.id];
    const stale = row?.updated_at && Date.now() - Date.parse(row.updated_at) > snapshot.stale_after_seconds * 1000;
    const values = [exchange.name, row.asset, row.network_label || row.network, row?.fee_kind === 'percent' ? `${Number(row.fee_rate) * 100}٪ از مبلغ برداشت` : row?.fee == null ? 'نامشخص' : `${row.fee} ${row.fee_currency}`, row?.minimum == null ? 'نامشخص' : `${row.minimum} ${row.asset}`, row?.withdrawal_enabled == null ? 'نامشخص' : row.withdrawal_enabled ? 'فعال' : 'متوقف', row?.updated_at ? `${new Date(row.updated_at).toLocaleString('fa-IR')}${stale ? ' — قدیمی' : ''}${source?.status === 'error' ? ' — دریافت ناموفق' : ''}` : source?.status === 'error' ? 'دریافت ناموفق؛ داده نداریم' : 'در دادهٔ این صرافی موجود نیست'];
    values.forEach(v => { const td = document.createElement('td'); td.textContent = v; tr.append(td); });
    if (row.source) {
      const link = document.createElement('a'); link.href = row.source; link.textContent = 'منبع'; link.target = '_blank'; link.rel = 'noopener noreferrer';
      tr.lastChild.append(document.createElement('br'), link);
    }
    return tr;
  }));
}

function renderBlockchain() {
  const panel = $('chain-fee');
  panel.replaceChildren();
  const heading = document.createElement('h2');
  heading.textContent = 'میانگین فی پرداخت‌شدهٔ تراکنش‌های نمونه';
  panel.append(heading);
  const paragraph = text => { const p = document.createElement('p'); p.textContent = text; panel.append(p); };
  const asset = $('asset').value, network = $('network').value;
  if (asset === '*' || network === '*') {
    paragraph('برای دیدن میانگین فی بلاک‌چین کنار کارمزد صرافی‌ها، یک ارز و یک شبکهٔ مشخص انتخاب کنید.');
    return;
  }
  const entry = (snapshot.blockchain_fees || []).find(r => r.asset === asset && r.network === network);
  if (!entry || entry.status === 'unsupported') {
    paragraph('برای این ترکیب ارز و شبکه هنوز نمونه‌گیری تأییدشدهٔ بلاک‌چین در دسترس نیست.');
    return;
  }
  if (!entry.sample_count || entry.average_fee == null) {
    paragraph(entry.status === 'error' ? 'دریافت اطلاعات بلاک‌چین ناموفق بود؛ کارمزد نامشخص است.' : 'هنوز انتقال ساده و موفق کافی در بازهٔ بررسی پیدا نشده است.');
    return;
  }
  const average = document.createElement('strong');
  average.className = 'chain-average';
  average.textContent = `${entry.average_fee} ${entry.fee_currency}`;
  panel.append(average);
  paragraph(`میانگین ${entry.sample_count} انتقال ساده و موفق از ${entry.target_count} نمونهٔ هدف — ${asset} روی ${network}`);
  if (entry.total_fee != null) paragraph(`نحوهٔ محاسبه: جمع فی ${entry.sample_count} تراکنش (${entry.total_fee} ${entry.fee_currency}) تقسیم بر ${entry.sample_count}`);
  if (entry.minimum_fee != null && entry.maximum_fee != null) paragraph(`کمترین فی: ${entry.minimum_fee} ${entry.fee_currency} — بیشترین فی: ${entry.maximum_fee} ${entry.fee_currency} — میانه: ${entry.median_fee} ${entry.fee_currency}`);
  const stale = entry.status === 'stale' || !entry.updated_at || Date.now() - Date.parse(entry.updated_at) > snapshot.stale_after_seconds * 1000;
  paragraph(`زمان بررسی: ${new Date(entry.updated_at).toLocaleString('fa-IR')}${stale ? ' — قدیمی' : ''}${entry.status === 'error' ? ' — دریافت جدید ناموفق؛ نمایش دادهٔ قبلی' : ''}${entry.sample_count < entry.target_count ? ' — نمونهٔ کمتر از هدف' : ''}`);
  if (entry.sampled_from && entry.sampled_to) paragraph(`بازهٔ تراکنش‌ها: ${new Date(entry.sampled_from).toLocaleString('fa-IR')} تا ${new Date(entry.sampled_to).toLocaleString('fa-IR')}`);
  const details = document.createElement('details');
  const summary = document.createElement('summary'); summary.textContent = 'مشاهدهٔ تراکنش‌های نمونه';
  details.open = true;
  const list = document.createElement('ul');
  const prefixes = ['https://tronscan.org/#/transaction/', 'https://etherscan.io/tx/', 'https://bscscan.com/tx/', 'https://mempool.space/tx/'];
  for (const sample of entry.samples || []) {
    const item = document.createElement('li');
    item.textContent = `${sample.fee} ${entry.fee_currency} — `;
    if (prefixes.some(prefix => sample.url?.startsWith(prefix))) {
      const link = document.createElement('a');
      link.href = sample.url; link.target = '_blank'; link.rel = 'noopener noreferrer';
      link.textContent = sample.txid.slice(0, 10) + '…'; item.append(link);
    }
    if (network === 'tron' && sample.energy_fee != null && sample.bandwidth_fee != null) {
      const breakdown = document.createElement('div');
      breakdown.textContent = `از فی کل: انرژی ${sample.energy_fee} TRX، پهنای باند ${sample.bandwidth_fee} TRX، سایر ${sample.other_fee || '0'} TRX — انرژی مصرفی: ${sample.energy_consumed ?? 'نامشخص'} واحد (TRX نیست)`;
      item.append(breakdown);
    }
    list.append(item);
  }
  details.append(summary, list); panel.append(details);
  paragraph('این عدد میانگین تاریخی است؛ کارمزد قطعی انتقال بعدی یا برداشت صرافی نیست. واحد فی شبکه ممکن است با واحد کارمزد صرافی فرق داشته باشد.');
  if (network === 'tron') paragraph('این میانگین می‌تواند انتقال‌هایی با منابع متفاوت را شامل شود. در ترون، انرژی و پهنای باند تأمین‌شده می‌توانند فی پرداختی را صفر کنند؛ صفر بودن نمونه به معنی رایگان بودن انتقال برای همه نیست.');
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
    choices($('asset'), ['*', ...(snapshot.requested_assets || [...new Set(snapshot.rows.map(r => r.asset))])].sort());
    networks();
    if (!snapshot.rows.length) $('status').textContent = 'هنوز دادهٔ تأییدشده‌ای برای ارزهای انتخابی دریافت نشده است.';
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
