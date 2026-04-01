const createForm = document.getElementById('polling-create-form');
const callerSelect = document.getElementById('caller-agent');
const targetSelect = document.getElementById('target-agent');
const intervalInput = document.getElementById('poll-interval');
const attemptsInput = document.getElementById('poll-attempts');
const pollingTable = document.getElementById('polling-table');
const inspector = document.getElementById('inspector');

let snapshot = { agents: [], rows: [] };

function setInspector(title, data) {
  inspector.textContent = `${title}\n\n${JSON.stringify(data, null, 2)}`;
}

function uniqueAgents(rows, listed) {
  const set = new Set((listed || []).map((x) => String(x).toLowerCase()).filter(Boolean));
  (rows || []).forEach((row) => {
    set.add(String(row.caller_agent || '').toLowerCase());
    set.add(String(row.target_agent || '').toLowerCase());
  });
  return [...set].filter(Boolean).sort((a, b) => a.localeCompare(b));
}

function renderAgentOptions(agents) {
  const options = agents.map((id) => `<option value="${id}">${id}</option>`).join('');
  callerSelect.innerHTML = options;
  targetSelect.innerHTML = options;
  if (agents.length > 1) {
    callerSelect.value = agents[0];
    targetSelect.value = agents[1];
  }
}

function renderRows(rows) {
  pollingTable.innerHTML = '';
  if (!rows.length) {
    const tr = document.createElement('tr');
    tr.innerHTML = '<td colspan="6">No agent pairs available yet.</td>';
    pollingTable.appendChild(tr);
    return;
  }

  rows.forEach((row) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${row.caller_agent}</td>
      <td>${row.target_agent}</td>
      <td><input type="number" min="0.1" step="0.1" value="${Number(row.poll_interval_seconds ?? 20)}" /></td>
      <td><input type="number" min="1" step="1" value="${Number(row.max_poll_attempts ?? 5)}" /></td>
      <td>${row.is_custom ? 'db(custom)' : 'default'}</td>
      <td><button type="button">Save</button></td>
    `;
    const [intervalField, attemptsField] = tr.querySelectorAll('input');
    const button = tr.querySelector('button');

    button.addEventListener('click', async () => {
      await saveRow({
        caller_agent: row.caller_agent,
        target_agent: row.target_agent,
        poll_interval_seconds: Number(intervalField.value),
        max_poll_attempts: Number(attemptsField.value),
      });
    });

    tr.onclick = (ev) => {
      if (ev.target.tagName.toLowerCase() === 'input' || ev.target.tagName.toLowerCase() === 'button') return;
      setInspector('Polling Pair', row);
    };
    pollingTable.appendChild(tr);
  });
}

async function fetchSnapshot() {
  const res = await fetch('/api/polling-config');
  if (!res.ok) throw new Error('Failed to fetch polling config');
  snapshot = await res.json();
  const agents = uniqueAgents(snapshot.rows || [], snapshot.agents || []);
  renderAgentOptions(agents);
  renderRows(snapshot.rows || []);
}

async function saveRow(payload) {
  if (!payload.caller_agent || !payload.target_agent) return;
  if (payload.caller_agent === payload.target_agent) {
    setInspector('Validation', { error: 'caller and target must differ' });
    return;
  }
  const res = await fetch('/api/polling-config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    setInspector('Save Failed', body);
    return;
  }
  snapshot = body;
  const agents = uniqueAgents(snapshot.rows || [], snapshot.agents || []);
  renderAgentOptions(agents);
  renderRows(snapshot.rows || []);
  setInspector('Saved', payload);
}

createForm.addEventListener('submit', async (ev) => {
  ev.preventDefault();
  await saveRow({
    caller_agent: String(callerSelect.value || '').toLowerCase(),
    target_agent: String(targetSelect.value || '').toLowerCase(),
    poll_interval_seconds: Number(intervalInput.value),
    max_poll_attempts: Number(attemptsInput.value),
  });
});

fetchSnapshot().catch((err) => setInspector('Load Failed', String(err)));
setInterval(() => fetchSnapshot().catch(() => {}), 5000);
