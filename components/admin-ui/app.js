const notice = document.querySelector('#notice');
const warning = document.querySelector('#gateway-warning');
const modelsBody = document.querySelector('#models');
const addButton = document.querySelector('#show-add');
const dialog = document.querySelector('#add-dialog');
const addForm = document.querySelector('#add-form');
const dialogError = document.querySelector('#dialog-error');
const modelSource = document.querySelector('#model-source');
const runnerAddress = document.querySelector('#runner-address');
const servedModel = document.querySelector('#served-model');
const runnerContext = document.querySelector('#runner-context');
const cloudModel = document.querySelector('#cloud-model');
const sharedKey = document.querySelector('#shared-key');
const servedError = document.querySelector('#served-error');
const saveButton = addForm.querySelector('[type=submit]');
const addClassChoices = document.querySelector('#add-class-choices');
let classesReady = false;
let classSelectionRequired = false;
let addDialogRequest = 0;
let runnerRuntime = {};

function showRunnerContext() {
  const details = runnerRuntime[servedModel.value];
  const active = details?.active_context_tokens;
  runnerContext.hidden = !Number.isInteger(active) || active < 1;
  if (!runnerContext.hidden) {
    const training = details.training_context_tokens;
    runnerContext.textContent = `Active context: ${active.toLocaleString()} tokens.` +
      (Number.isInteger(training) && training > 0 ?
        ` Model training context: ${training.toLocaleString()} tokens.` : '');
  }
}

function updateAddSave() {
  const cloud = modelSource.value !== 'runner';
  const validModel = cloud ? cloudModel.value.trim() &&
    /^[A-Za-z0-9_.:-]+$/.test(cloudModel.value.trim()) : servedModel.value;
  const validKey = !cloud || addForm.elements.key_choice.value !== 'shared' ||
    sharedKey.value.length >= 12;
  saveButton.disabled = !classesReady || !validModel || !validKey ||
    (classSelectionRequired && !addClassChoices.querySelector('input:checked'));
}

function updateSource() {
  const cloud = modelSource.value !== 'runner';
  document.querySelector('#runner-fields').hidden = cloud;
  document.querySelector('#cloud-fields').hidden = !cloud;
  runnerAddress.required = !cloud;
  servedModel.required = !cloud;
  cloudModel.required = cloud;
  sharedKey.required = cloud && addForm.elements.key_choice.value === 'shared';
  document.querySelector('#shared-key-field').hidden = !sharedKey.required;
  servedError.hidden = true;
  updateAddSave();
}

async function request(path, options) {
  const response = await fetch(path, {...options, headers: {'Accept': 'application/json', ...options?.headers}});
  if (response.status === 401) {
    window.location.assign('/');
    throw new Error('Sign in again');
  }
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.error?.message || data.error || `HTTP ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return data;
}

function showNotice(message) {
  notice.textContent = message;
  notice.hidden = !message;
}

function tableMessage(message) {
  modelsBody.replaceChildren();
  const row = modelsBody.insertRow();
  const cell = row.insertCell();
  cell.colSpan = 6;
  cell.textContent = message;
}

async function refresh(preferredModel) {
  tableMessage('Loading models…');
  try {
    const catalog = await request('/api/models');
    warning.hidden = true;
    addButton.disabled = false;
    modelsBody.replaceChildren();
    const models = catalog.models.filter((model) => model.kind !== 'endpoint-trial' || model.approved !== undefined);
    if (!models.length) tableMessage('No models added yet');
    for (const model of models) {
      const row = modelsBody.insertRow();
      const nameCell = row.insertCell();
      const name = document.createElement('span');
      name.className = 'model-id';
      name.textContent = model.id;
      const detail = document.createElement('span');
      detail.className = 'model-kind';
      detail.textContent = model.approved === false ? 'Added outside Keeplane' :
        model.kind === 'real-local' ? 'Local model' :
        model.kind === 'cloud' ? 'Cloud model' :
        model.kind === 'fixture' ? 'Fixed answer test fixture' : 'Source not identified';
      nameCell.append(name, detail);
      row.insertCell().textContent = model.provider;
      row.insertCell().textContent = model.kind === 'cloud' ? 'Cloud' :
        model.kind === 'unknown' ? 'Unknown' : 'Local';
      row.insertCell().textContent = model.approved === false ? 'Not set' :
        model.approved ? ({shared: 'Shared', personal: "Each developer's own", none: 'No key needed'}[model.key_choice] || 'Unknown') :
        model.kind === 'unknown' ? 'Unknown' : 'None';
      const approval = row.insertCell();
      approval.textContent = model.approved === false ? 'Not set · gets no work' :
        model.approved ? model.approved_classes.join(', ') : 'Not configured';
      if (!model.approved) approval.className = 'unconfigured';
      const actions = row.insertCell();
      if (model.approved !== undefined) {
        const edit = document.createElement('button');
        edit.type = 'button';
        edit.textContent = model.approved ? 'Edit' : 'Set up';
        edit.addEventListener('click', () => openSetup(model));
        actions.append(edit);
      }
    }
    return models.some((model) => model.id === preferredModel);
  } catch (_) {
    tableMessage('Models unavailable');
    warning.hidden = false;
    addButton.disabled = true;
    return false;
  }
}

addButton.addEventListener('click', async () => {
  const requestId = ++addDialogRequest;
  dialogError.hidden = true;
  servedError.hidden = true;
  classesReady = false;
  classSelectionRequired = false;
  addClassChoices.hidden = true;
  addClassChoices.querySelectorAll('label').forEach((label) => label.remove());
  updateAddSave();
  dialog.showModal();
  try {
    const result = await request('/api/data-classes');
    if (requestId !== addDialogRequest || !dialog.open) return;
    classSelectionRequired = true;
    addClassChoices.hidden = false;
    for (const dataClass of result.classes) {
      const label = document.createElement('label');
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.name = 'approved_classes';
      input.value = dataClass.name;
      label.append(input, document.createTextNode(' ' + dataClass.name));
      addClassChoices.insertBefore(label, addClassChoices.querySelector('p'));
    }
    classesReady = true;
  } catch (error) {
    if (requestId !== addDialogRequest || !dialog.open) return;
    if (error.status === 404) classesReady = true;
    else {
      dialogError.textContent = error.message;
      dialogError.hidden = false;
    }
  }
  updateAddSave();
});
dialog.addEventListener('close', () => { addDialogRequest += 1; });
addClassChoices.addEventListener('change', updateAddSave);
servedModel.addEventListener('change', () => { showRunnerContext(); updateAddSave(); });
modelSource.addEventListener('change', updateSource);
cloudModel.addEventListener('input', updateAddSave);
sharedKey.addEventListener('input', updateAddSave);
addForm.querySelectorAll('[name=key_choice]').forEach((choice) =>
  choice.addEventListener('change', updateSource));

const setupDialog = document.querySelector('#setup-dialog');
const setupForm = document.querySelector('#setup-form');
const setupError = document.querySelector('#setup-error');
let setupModel;
async function openSetup(model) {
  setupModel = model;
  document.querySelector('#setup-title').textContent = model.approved ? `Edit ${model.id}` : 'Set up model';
  document.querySelector('#setup-description').textContent = model.approved ?
    `${model.provider} · ${model.kind === 'cloud' ? 'Cloud' : 'Local'}. Change ${model.key_choice === 'shared' ? 'the shared key or ' : ''}the approved data classes. Keeplane checks that it still answers before saving.` :
    'A model added outside Keeplane gets no work until you set its key and the classes it is approved for.';
  const setupName = document.querySelector('#setup-model-name');
  setupName.hidden = model.approved;
  setupName.textContent = model.approved ? '' : model.id;
  const removeButton = document.querySelector('#remove-setup');
  removeButton.hidden = !model.approved;
  removeButton.textContent = model.owned_by_keeplane ? 'Remove model' : 'Remove Keeplane setup';
  setupError.hidden = true;
  setupForm.reset();
  document.querySelector('#setup-key-choice').textContent = model.key_choice === 'shared' ?
    'Shared key' : 'No key needed';
  document.querySelector('#replace-key-field').hidden = !(
    model.key_choice === 'shared' && model.owned_by_keeplane && model.kind === 'cloud');
  setupDialog.showModal();
  const choices = document.querySelector('#setup-class-choices');
  const save = setupForm.querySelector('[type=submit]');
  save.disabled = true;
  choices.querySelectorAll('label').forEach((label) => label.remove());
  try {
    const result = await request('/api/data-classes');
    for (const dataClass of result.classes) {
      const label = document.createElement('label');
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.name = 'approved_classes';
      input.value = dataClass.name;
      input.checked = model.approved_classes.includes(dataClass.name);
      label.append(input, document.createTextNode(' ' + dataClass.name));
      choices.insertBefore(label, choices.querySelector('p'));
    }
    save.disabled = false;
  } catch (error) {
    setupError.textContent = error.message;
    setupError.hidden = false;
  }
}
document.querySelector('#cancel-setup').addEventListener('click', () => setupDialog.close());
setupForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const save = setupForm.querySelector('[type=submit]');
  const approvedClasses = [...new FormData(setupForm).getAll('approved_classes')];
  const replaceKey = document.querySelector('#replace-shared-key');
  const replacement = replaceKey.value;
  save.disabled = true;
  setupError.hidden = true;
  try {
    await request(`/api/models/${encodeURIComponent(setupModel.id)}/setup`, {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-Keeplane-Action': '1'},
      body: JSON.stringify({key_choice: setupModel.key_choice === 'shared' ? 'shared' : 'none',
        approved_classes: approvedClasses,
        ...(replacement ? {replace_shared_key: replacement} : {})}),
    });
    setupDialog.close();
    showNotice(`${setupModel.approved ? 'Saved' : 'Set up'} ${setupModel.id}.`);
    await refresh(setupModel.id);
  } catch (error) {
    setupError.textContent = error.message;
    setupError.hidden = false;
  } finally { replaceKey.value = ''; save.disabled = false; }
});
const removeSetupDialog = document.querySelector('#remove-setup-dialog');
document.querySelector('#remove-setup').addEventListener('click', () => {
  document.querySelector('#remove-setup-title').textContent = setupModel.owned_by_keeplane ?
    `Remove ${setupModel.id}?` : 'Remove Keeplane setup?';
  const description = document.querySelector('#remove-setup-description');
  const name = document.querySelector('#remove-setup-name');
  name.textContent = setupModel.id;
  description.replaceChildren('Keeplane stops sending work to ', name, setupModel.owned_by_keeplane ?
    ' and removes it from the gateway.' : '. The model stays in the gateway.');
  document.querySelector('#confirm-remove-setup').textContent =
    setupModel.owned_by_keeplane ? 'Remove model' : 'Remove setup';
  document.querySelector('#remove-setup-error').hidden = true;
  removeSetupDialog.showModal();
});
document.querySelector('#cancel-remove-setup').addEventListener('click', () => removeSetupDialog.close());
document.querySelector('#confirm-remove-setup').addEventListener('click', async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  document.querySelector('#remove-setup-error').hidden = true;
  try {
    const result = await request(`/api/models/${encodeURIComponent(setupModel.id)}/setup`, {
      method: 'DELETE', headers: {'Content-Type': 'application/json', 'X-Keeplane-Action': '1'},
    });
    removeSetupDialog.close();
    setupDialog.close();
    showNotice(result.gateway_model_preserved ?
      `Removed Keeplane setup for ${setupModel.id}. The gateway model remains.` :
      `Removed ${setupModel.id} from Keeplane and the gateway.`);
    if (result.gateway_model_preserved) await refresh(setupModel.id);
    else {
      for (const delay of [0, 100, 200, 400, 800, 1600, 3200]) {
        if (delay) await new Promise((resolve) => setTimeout(resolve, delay));
        if (!await refresh(setupModel.id)) break;
      }
    }
  } catch (error) {
    document.querySelector('#remove-setup-error').textContent = error.message;
    document.querySelector('#remove-setup-error').hidden = false;
  } finally { button.disabled = false; }
});
document.querySelector('#try-again').addEventListener('click', () => refresh());
document.querySelector('#cancel-add').addEventListener('click', () => dialog.close());
runnerAddress.addEventListener('input', () => {
  servedError.hidden = true;
  runnerRuntime = {};
  showRunnerContext();
  servedModel.replaceChildren(new Option('Find models first', ''));
  servedModel.disabled = true;
  updateAddSave();
});

document.querySelector('#find-models').addEventListener('click', async (event) => {
  if (!runnerAddress.reportValidity()) return;
  const queriedAddress = runnerAddress.value.trim();
  const button = event.currentTarget;
  button.disabled = true;
  dialogError.hidden = true;
  servedError.hidden = true;
  servedModel.replaceChildren(new Option('Finding models…', ''));
  servedModel.disabled = true;
  runnerRuntime = {};
  showRunnerContext();
  try {
    const result = await request('/api/runners/models', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({address: queriedAddress}),
    });
    if (!dialog.open || runnerAddress.value.trim() !== queriedAddress) return;
    servedModel.replaceChildren();
    for (const name of result.models) servedModel.add(new Option(name, name));
    runnerRuntime = result.runtime || {};
    showRunnerContext();
    if (result.models.length) {
      servedModel.disabled = false;
      updateAddSave();
    } else servedModel.add(new Option('No models found', ''));
  } catch (error) {
    if (!dialog.open || runnerAddress.value.trim() !== queriedAddress) return;
    servedModel.replaceChildren(new Option('Find models first', ''));
    runnerRuntime = {};
    showRunnerContext();
    updateAddSave();
    dialogError.textContent = error.message;
    dialogError.hidden = false;
  } finally {
    button.disabled = false;
  }
});

addForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = addForm.querySelector('[type=submit]');
  const source = modelSource.value;
  const model = source === 'runner' ? servedModel.value : cloudModel.value.trim();
  const address = runnerAddress.value.trim();
  const approvedClasses = [...new FormData(addForm).getAll('approved_classes')];
  button.disabled = true;
  dialogError.hidden = true;
  servedError.hidden = true;
  try {
    const result = await request('/api/models', {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-Keeplane-Action': '1'},
      body: JSON.stringify({name: model, model, source, ...(source === 'runner' ? {address} :
        {key_choice: addForm.elements.key_choice.value,
          ...(addForm.elements.key_choice.value === 'shared' ? {shared_key: sharedKey.value} : {})}),
        ...(classSelectionRequired ? {approved_classes: approvedClasses} : {})}),
    });
    if (result.existing) {
      servedError.textContent = `${model} from ${modelSource.selectedOptions[0].textContent} is already added.`;
      servedError.hidden = false;
      return;
    }
    dialog.close();
    addForm.reset();
    updateSource();
    servedModel.replaceChildren(new Option('Find models first', ''));
    servedModel.disabled = true;
    runnerRuntime = {};
    showRunnerContext();
    updateAddSave();
    let visible = false;
    for (const delay of [0, 100, 200, 400, 800, 1600, 3200]) {
      if (delay) await new Promise((resolve) => setTimeout(resolve, delay));
      visible = await refresh(model);
      if (visible) break;
    }
    showNotice(visible ? `Added ${model}${result.approved_classes ? ' with approved data classes' : ''}.` :
      `${model} was added, but is not in the list yet. Try again in a moment.`);
  } catch (error) {
    if (error.status === 409) {
      servedError.textContent = `${model} from ${modelSource.selectedOptions[0].textContent} is already added.`;
      servedError.hidden = false;
    } else {
      dialogError.textContent = `${model || 'Model'} wasn't added. ${error.message} Check the details and try again.`;
      dialogError.hidden = false;
    }
  } finally {
    updateAddSave();
  }
});

refresh();
updateSource();
request('/api/identity').then((identity) => {
  document.querySelectorAll('[data-identity-only]').forEach((item) => { item.hidden = false; });
  document.querySelector('#signed-in-user').textContent = identity.username;
  document.querySelector('.preview').hidden = true;
}).catch(() => {});
document.documentElement.dataset.appReady = 'true';
