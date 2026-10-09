const notice = document.querySelector('#notice');
const rows = document.querySelector('#records');
const count = document.querySelector('#record-count');
const previous = document.querySelector('#previous');
const next = document.querySelector('#next');
const search = document.querySelector('#search-records');
const kind = document.querySelector('#record-kind');
let page = 1;
let requestNumber = 0;
let searchTimer;

async function api(path, options = {}) {
  const response = await fetch(path, {...options,
    headers: {'Accept': 'application/json', ...options.headers}});
  if (response.status === 401) {
    location.assign('/');
    throw new Error('Sign in again');
  }
  if (!response.headers.get('Content-Type')?.includes('application/json')) {
    if (response.redirected) location.assign('/');
    throw new Error('Audit is temporarily unavailable. Try again.');
  }
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
  return result;
}

function message(value, error = false) {
  notice.textContent = value;
  notice.classList.toggle('error', error);
  notice.hidden = !value;
}

async function refreshOptions() {
  const result = await api('/api/audit/options');
  for (const toggle of document.querySelectorAll('[data-kind]')) {
    toggle.checked = result.options[toggle.dataset.kind];
  }
}

for (const toggle of document.querySelectorAll('[data-kind]')) {
  toggle.addEventListener('change', async () => {
    const desired = toggle.checked;
    toggle.disabled = true;
    try {
      await api(`/api/audit/options/${toggle.dataset.kind}`, {
        method: 'PUT', headers: {'Content-Type': 'application/json', 'X-Keeplane-Action': '1'},
        body: JSON.stringify({enabled: desired}),
      });
      message(desired ? 'Recording turned on.' : 'Recording turned off.');
    } catch (error) {
      toggle.checked = !desired;
      message(error.message, true);
    } finally {
      toggle.disabled = false;
    }
  });
}

async function refreshRecords() {
  const currentRequest = ++requestNumber;
  rows.replaceChildren();
  const loading = rows.insertRow().insertCell();
  loading.colSpan = 3;
  loading.textContent = 'Loading records…';
  const params = new URLSearchParams({page, kind: kind.value, search: search.value.trim()});
  try {
    const result = await api(`/api/audit/records?${params}`);
    if (currentRequest !== requestNumber) return;
    rows.replaceChildren();
    for (const item of result.records) {
      const row = rows.insertRow();
      const when = new Date(item.when);
      row.insertCell().textContent = Number.isNaN(when.valueOf()) ? item.when : when.toLocaleString();
      row.insertCell().textContent = item.who;
      row.insertCell().textContent = item.what;
    }
    if (!result.records.length) {
      const cell = rows.insertRow().insertCell();
      cell.colSpan = 3;
      cell.textContent = 'No records found.';
    }
    const first = result.total ? (result.page - 1) * result.page_size + 1 : 0;
    const last = Math.min(result.page * result.page_size, result.total);
    count.textContent = `Showing ${first}–${last} of ${result.total} records`;
    previous.disabled = page <= 1;
    next.disabled = !result.has_more;
  } catch (error) {
    if (currentRequest !== requestNumber) return;
    rows.replaceChildren();
    const cell = rows.insertRow().insertCell();
    cell.colSpan = 3;
    cell.textContent = 'Could not load records.';
    message(error.message, true);
  }
}

search.addEventListener('input', () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { page = 1; refreshRecords(); }, 250);
});
kind.addEventListener('change', () => { page = 1; refreshRecords(); });
previous.addEventListener('click', () => { if (page > 1) { page -= 1; refreshRecords(); } });
next.addEventListener('click', () => { page += 1; refreshRecords(); });

api('/api/identity').then((identity) => {
  document.querySelector('#signed-in-user').textContent = identity.username;
}).catch((error) => message(error.message, true));
refreshOptions().catch((error) => message(error.message, true));
refreshRecords();
document.documentElement.dataset.appReady = 'true';
