const rows = document.querySelector('#rows');
const notice = document.querySelector('#notice');
const previous = document.querySelector('#previous');
const next = document.querySelector('#next');
const pageLabel = document.querySelector('#page-label');
const searchInput = document.querySelector('#search-users');
const state = {page: 1, hasMore: false, search: '', sequence: 0};

async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers: {'Accept': 'application/json', ...options.headers}});
  if (response.status === 401) {
    window.location.assign('/');
    throw new Error('Sign in again');
  }
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
  return result;
}

function changeNotice(message, isError = false) {
  notice.textContent = message;
  notice.classList.toggle('error', isError);
  notice.hidden = !message;
}

function emptyRow(message) {
  rows.replaceChildren();
  const row = rows.insertRow();
  const cell = row.insertCell();
  cell.colSpan = 2;
  cell.textContent = message;
}

function setPager(count) {
  const start = count ? (state.page - 1) * 20 + 1 : 0;
  pageLabel.textContent = count ? `Showing ${start}–${start + count - 1}` : 'No results';
  previous.disabled = state.page === 1;
  next.disabled = !state.hasMore;
}

async function loadUsers() {
  const sequence = ++state.sequence;
  emptyRow('Loading…');
  try {
    const params = new URLSearchParams({page: state.page, page_size: 20, search: state.search});
    const result = await api(`/api/users?${params}`);
    if (sequence !== state.sequence) return;
    state.hasMore = result.has_more;
    rows.replaceChildren();
    if (!result.users.length) emptyRow('No users found');
    for (const user of result.users) {
      const row = rows.insertRow();
      row.insertCell().textContent = user.username;
      row.insertCell().textContent = user.role === 'admin' ? 'Admin' : 'Developer';
    }
    setPager(result.users.length);
  } catch (error) {
    if (sequence === state.sequence) {
      emptyRow('Could not load users');
      changeNotice(error.message, true);
    }
  }
}

previous.addEventListener('click', () => { if (state.page > 1) { state.page--; loadUsers(); } });
next.addEventListener('click', () => { if (state.hasMore) { state.page++; loadUsers(); } });
let searchTimer;
searchInput.addEventListener('input', () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { state.search = searchInput.value.trim(); state.page = 1; loadUsers(); }, 250);
});

const dialog = document.querySelector('#create-dialog');
const form = document.querySelector('#create-form');
const dialogError = document.querySelector('#dialog-error');
document.querySelector('#show-create').addEventListener('click', () => {
  dialogError.hidden = true;
  dialog.showModal();
});
document.querySelector('#cancel-create').addEventListener('click', () => dialog.close());
form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const save = form.querySelector('[type=submit]');
  save.disabled = true;
  dialogError.hidden = true;
  try {
    const created = await api('/api/users', {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-Keeplane-Action': '1'},
      body: JSON.stringify(Object.fromEntries(new FormData(form))),
    });
    dialog.close();
    form.reset();
    state.page = 1;
    state.search = '';
    searchInput.value = '';
    changeNotice(`Created ${created.username}.`);
    await loadUsers();
  } catch (error) {
    dialogError.textContent = error.message;
    dialogError.hidden = false;
  } finally { save.disabled = false; }
});

api('/api/identity').then((identity) => {
  document.querySelector('#signed-in-user').textContent = identity.username;
}).catch(() => {});
api('/api/edition-note/consume', {
  method: 'POST', headers: {'Content-Type': 'application/json', 'X-Keeplane-Action': '1'}, body: '{}',
}).then(({show}) => { document.querySelector('#edition-note').hidden = !show; }).catch(() => {});
loadUsers();
document.documentElement.dataset.appReady = 'true';
