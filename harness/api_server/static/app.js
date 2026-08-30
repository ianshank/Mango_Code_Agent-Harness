const API_PATH = '/api/orchestrate';
const VERDICTS = new Set(['VERIFIED', 'FAILED', 'BLOCKED']);
const form = document.getElementById('taskForm');
const taskInput = document.getElementById('taskInput');
const apiKeyInput = document.getElementById('apiKeyInput');
const submitBtn = document.getElementById('submitBtn');
const btnText = document.getElementById('btnText');
const btnLoader = document.getElementById('btnLoader');
const runOutput = document.getElementById('runOutput');
const runState = document.getElementById('runState');
const runBadge = document.getElementById('runBadge');

function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
}

function setRunning(isRunning) {
    submitBtn.disabled = isRunning;
    btnText.textContent = isRunning ? 'Run in progress' : 'Start governed run';
    btnLoader.classList.toggle('hidden', !isRunning);
    runState.textContent = isRunning
        ? 'Run in progress. The console will update when the server responds.'
        : 'Ready for a task.';
    runBadge.textContent = isRunning ? 'In progress' : 'No run yet';
    runBadge.className = 'run-badge' + (isRunning ? ' is-running' : '');
}

function addLabelledValue(container, label, value) {
    if (value === undefined || value === null || value === '') return;
    const row = element('div', 'assessment-detail');
    row.append(element('dt', '', label), element('dd', '', value));
    container.appendChild(row);
}

function renderVerdict(data) {
    const verdict = String(data.verdict || '').toUpperCase();
    const knownVerdict = VERDICTS.has(verdict);
    const card = element('section', 'assessment-card harness' + (knownVerdict ? ' verdict-' + verdict.toLowerCase() : ''));
    card.append(
        element('p', 'assessment-label', 'Harness verdict'),
        element('h3', 'assessment-status', knownVerdict ? verdict : 'Not provided')
    );
    const details = element('dl', 'assessment-details');
    const hasStructuredEvidence = data.verdict_command != null || data.verdict_exit_code != null;
    if (hasStructuredEvidence) {
        addLabelledValue(details, 'Command', data.verdict_command);
        addLabelledValue(details, 'Exit code', data.verdict_exit_code);
    } else {
        addLabelledValue(details, 'Evidence', data.verdict_detail);
    }
    addLabelledValue(details, 'Termination', data.termination_reason);
    if (details.childElementCount) card.appendChild(details);
    return card;
}

function traceEvents(data) {
    if (Array.isArray(data.trace)) return data.trace;
    return [data.trace_events, data.events].find(Array.isArray) || [];
}

function orderedPhases(data) {
    return traceEvents(data)
        .map((event, index) => ({ event, index }))
        .filter(({ event }) => event && typeof event === 'object' && event.phase)
        .sort((left, right) => {
            const leftSequence = Number(left.event.sequence);
            const rightSequence = Number(right.event.sequence);
            const leftValid = Number.isFinite(leftSequence);
            const rightValid = Number.isFinite(rightSequence);
            if (leftValid && rightValid && leftSequence !== rightSequence) return leftSequence - rightSequence;
            if (leftValid !== rightValid) return leftValid ? -1 : 1;
            return left.index - right.index;
        })
        .reduce((phases, { event }) => {
            const existing = phases.get(event.phase);
            if (existing) {
                existing.state = event.state;
                existing.elapsedMs = event.elapsed_ms;
            } else {
                phases.set(event.phase, { state: event.state, elapsedMs: event.elapsed_ms });
            }
            return phases;
        }, new Map());
}

function renderTrace(data) {
    const phases = orderedPhases(data);
    if (!phases.size) return null;
    const section = element('section', 'trace-section');
    section.appendChild(element('h3', 'subheading', 'Phase pipeline'));
    const list = element('ol', 'phase-pipeline');
    phases.forEach((phase, name) => {
        const item = element('li', 'phase');
        const metadata = element('div', 'phase-metadata');
        metadata.appendChild(element('strong', '', name));
        metadata.appendChild(element('span', 'phase-status', phase.state || 'state not provided'));
        if (phase.elapsedMs !== undefined && phase.elapsedMs !== null && phase.elapsedMs !== '') {
            metadata.appendChild(element('span', 'phase-elapsed', String(phase.elapsedMs) + ' ms'));
        }
        item.appendChild(metadata);
        list.appendChild(item);
    });
    section.appendChild(list);
    return section;
}

function renderLegacyHistory(data) {
    if (!Array.isArray(data.history) || !data.history.length) return null;
    const details = element('details', 'legacy-history');
    details.appendChild(element('summary', '', 'Legacy run history'));
    const list = element('div', 'history-list');
    data.history.forEach((entry) => {
        if (!entry || typeof entry !== 'object') return;
        const item = element('article', 'history-item');
        item.append(
            element('p', 'history-role', entry.role || 'message'),
            element('p', 'history-content', entry.content || '')
        );
        list.appendChild(item);
    });
    if (!list.childElementCount) return null;
    details.appendChild(list);
    return details;
}

function renderResult(data) {
    const fragment = document.createDocumentFragment();
    const grid = element('div', 'assessment-grid');
    grid.appendChild(renderVerdict(data));
    const verifier = element('section', 'assessment-card verifier');
    verifier.append(
        element('p', 'assessment-label', 'Verifier assessment'),
        element('p', 'verifier-result', data.result || 'No verifier assessment returned.')
    );
    grid.appendChild(verifier);
    fragment.appendChild(grid);
    const trace = renderTrace(data);
    if (trace) fragment.appendChild(trace);
    const history = renderLegacyHistory(data);
    if (history) fragment.appendChild(history);
    runOutput.replaceChildren(fragment);
    const verdict = String(data.verdict || '').toUpperCase();
    runBadge.textContent = VERDICTS.has(verdict) ? verdict : 'Completed';
    runBadge.className = 'run-badge' + (VERDICTS.has(verdict) ? ' verdict-' + verdict.toLowerCase() : '');
    runState.textContent = 'Run completed' + (VERDICTS.has(verdict) ? ' with harness verdict ' + verdict : '') + '.';
}

function renderError(message, data = {}) {
    const fragment = document.createDocumentFragment();
    const card = element('section', 'request-error');
    card.append(element('h3', '', 'Request error'), element('p', '', message));
    fragment.appendChild(card);
    const trace = renderTrace(data);
    if (trace) fragment.appendChild(trace);
    runOutput.replaceChildren(fragment);
    runBadge.textContent = 'Request error';
    runBadge.className = 'run-badge verdict-failed';
    runState.textContent = 'Request failed: ' + message;
}

async function responseBody(response) {
    try {
        return await response.json();
    } catch (_) {
        return {};
    }
}

form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const task = taskInput.value.trim();
    const apiKey = apiKeyInput.value.trim();
    if (!task || !apiKey) return;
    setRunning(true);
    runOutput.replaceChildren(element('p', 'placeholder', 'The server is processing this run.'));
    try {
        const response = await fetch(API_PATH, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-API-Key': apiKey },
            body: JSON.stringify({ task })
        });
        const data = await responseBody(response);
        if (!response.ok) {
            const message =
                data.detail ||
                data.message ||
                'Request failed (' + response.status + ' ' + (response.statusText || 'Unknown error') + ').';
            renderError(message, data);
            return;
        }
        renderResult(data);
    } catch (error) {
        renderError(error.message || 'The request could not be completed.');
    } finally {
        if (submitBtn.disabled) {
            submitBtn.disabled = false;
            btnText.textContent = 'Start governed run';
            btnLoader.classList.add('hidden');
        }
    }
});