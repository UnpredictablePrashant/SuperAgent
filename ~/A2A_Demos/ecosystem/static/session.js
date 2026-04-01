const graphStage = document.getElementById('graph-stage');
const eventStream = document.getElementById('event-stream');
const edgeList = document.getElementById('edge-list');
const inspector = document.getElementById('inspector');
const sessionMeta = document.getElementById('session-meta');

const runId = location.pathname.split('/').filter(Boolean).pop();

function toTitle(value) {
  if (!value) return '';
  return value.replace(/[_-]/g, ' ').replace(/\b\w/g, (m) => m.toUpperCase());
}

function formatTs(ts) {
  if (!ts) return '-';
  return new Date(ts * 1000).toLocaleString();
}

function setInspector(title, data) {
  const payload = typeof data === 'string' ? data : JSON.stringify(data, null, 2);
  inspector.textContent = `${title}\n\n${payload}`;
}

function renderEvents(events) {
  eventStream.innerHTML = '';
  events.forEach((event) => {
    const div = document.createElement('div');
    div.className = `event ${event.kind || 'log'}`;
    div.onclick = () => setInspector('Event Detail', event);

    const meta = document.createElement('div');
    meta.className = 'meta';
    meta.textContent = `${formatTs(event.ts)} | ${event.source} | ${event.kind}`;

    const pre = document.createElement('pre');
    pre.textContent = event.message || '';

    div.appendChild(meta);
    div.appendChild(pre);
    eventStream.appendChild(div);
  });
}

function renderEdgeList(edges) {
  edgeList.innerHTML = '';
  edges.forEach((edge) => {
    const li = document.createElement('li');
    li.className = 'path-item';
    li.textContent = `${toTitle(edge.from)} -> ${toTitle(edge.to)} (${edge.type}) x${edge.count}`;
    li.onclick = () => setInspector('Interaction Edge', edge);
    edgeList.appendChild(li);
  });
}

function layoutNodes(nodes, width, height) {
  const cx = width / 2;
  const cy = height / 2;
  const radius = Math.max(90, Math.min(width, height) * 0.34);
  const out = {};
  const sorted = [...nodes].sort((a, b) => a.id.localeCompare(b.id));
  sorted.forEach((node, idx) => {
    const angle = (Math.PI * 2 * idx) / Math.max(sorted.length, 1) - Math.PI / 2;
    out[node.id] = {
      x: cx + Math.cos(angle) * radius,
      y: cy + Math.sin(angle) * radius,
    };
  });
  return out;
}

function renderGraph(graph) {
  const nodes = graph.nodes || [];
  const edges = graph.edges || [];
  renderEdgeList(edges);

  const width = graphStage.clientWidth || 900;
  const height = graphStage.clientHeight || 380;
  const points = layoutNodes(nodes, width, height);

  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);

  edges.forEach((edge) => {
    const from = points[edge.from];
    const to = points[edge.to];
    if (!from || !to) return;

    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line.setAttribute('x1', from.x);
    line.setAttribute('y1', from.y);
    line.setAttribute('x2', to.x);
    line.setAttribute('y2', to.y);
    line.setAttribute('class', 'graph-edge');
    line.style.strokeWidth = String(1.4 + Math.min(4, edge.count * 0.45));
    line.style.cursor = 'pointer';
    line.addEventListener('click', () => setInspector('Interaction Edge', edge));
    svg.appendChild(line);

    const lx = (from.x + to.x) / 2;
    const ly = (from.y + to.y) / 2;
    const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    text.setAttribute('x', lx);
    text.setAttribute('y', ly - 6);
    text.setAttribute('class', 'graph-edge-label');
    text.textContent = `${edge.type} x${edge.count}`;
    text.style.cursor = 'pointer';
    text.addEventListener('click', () => setInspector('Interaction Edge', edge));
    svg.appendChild(text);
  });

  nodes.forEach((node) => {
    const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    g.setAttribute('class', `graph-node ${node.kind}`);
    g.style.cursor = 'pointer';

    const p = points[node.id];
    const c = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    c.setAttribute('cx', p.x);
    c.setAttribute('cy', p.y);
    c.setAttribute('r', 30);

    const t = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    t.setAttribute('x', p.x);
    t.setAttribute('y', p.y);
    t.textContent = node.id === 'db' ? 'DB' : toTitle(node.id);

    g.appendChild(c);
    g.appendChild(t);
    g.addEventListener('click', () => {
      const related = edges.filter((e) => e.from === node.id || e.to === node.id);
      setInspector(`Node: ${toTitle(node.id)}`, { node, related_edges: related });
    });
    svg.appendChild(g);
  });

  graphStage.innerHTML = '';
  graphStage.appendChild(svg);
}

async function refresh() {
  const res = await fetch(`/api/sessions/${runId}`);
  if (!res.ok) {
    sessionMeta.textContent = `Session not found: ${runId}`;
    return;
  }
  const data = await res.json();
  const run = data.run || {};
  sessionMeta.textContent = `run=${run.id} | status=${run.status} | created=${formatTs(run.created_at)} | updated=${formatTs(run.updated_at)}`;
  renderGraph(data.graph || { nodes: [], edges: [], events: [] });
  renderEvents((data.graph || {}).events || []);
}

refresh();
setInterval(refresh, 2000);
