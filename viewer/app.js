// ── State ──
let data = null;
let transform = { x: 0, y: 0, k: 1 };
let drag = null;
let selectedId = null;
let hoveredSubnet = null;
let layoutCache = null;

const $ = (id) => document.getElementById(id);
const esc = (v) => String(v ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');

// ── Category colors ──
const CAT_COLORS = {
  'Public Edge':  { bg: '#d1fae5', border: '#34d399', text: '#065f46', icon: '🌐' },
  'Security':     { bg: '#fee2e2', border: '#f87171', text: '#991b1b', icon: '🛡️' },
  'Cloud Native': { bg: '#dbeafe', border: '#60a5fa', text: '#1e40af', icon: '☁️' },
  'Platform':     { bg: '#ede9fe', border: '#a78bfa', text: '#5b21b6', icon: '⚙️' },
  'DMZ':          { bg: '#fef3c7', border: '#fbbf24', text: '#92400e', icon: '🔶' },
  'Private App':  { bg: '#cffafe', border: '#22d3ee', text: '#155e75', icon: '🔒' },
  'Application':  { bg: '#e0e7ff', border: '#818cf8', text: '#3730a3', icon: '📦' },
};
const defaultCat = { bg: '#f3f4f6', border: '#9ca3af', text: '#374151', icon: '▪️' };
const catColor = (c) => CAT_COLORS[c] || defaultCat;

// ── Node type styles ──
const NODE_STYLES = {
  'vpc':                          { header: '#1e40af', bg: '#eff6ff', border: '#93c5fd' },
  'transit-gateway':              { header: '#b45309', bg: '#fffbeb', border: '#fcd34d' },
  'external-transit-gateway-peer':{ header: '#0e7490', bg: '#ecfeff', border: '#67e8f9' },
  'external-vpc-peer':            { header: '#7e22ce', bg: '#faf5ff', border: '#c4b5fd' },
};
const nodeStyle = (type) => NODE_STYLES[type] || NODE_STYLES['vpc'];

// ── Init ──
async function init() {
  // Try loading from local server first (python -m http.server)
  try {
    const resp = await fetch('../aws-network-topology.json');
    if (resp.ok) {
      data = await resp.json();
      boot();
      return;
    }
  } catch (_) { /* not available, show upload UI */ }

  showUploadUI();
}

function boot() {
  renderMetadata();
  renderSummary();
  renderLegend();
  layoutCache = layoutDiagram();
  renderDiagram();
  setupEvents();
  // Hide upload overlay if visible
  const overlay = $('upload-overlay');
  if (overlay) overlay.style.display = 'none';
}

function showUploadUI() {
  $('metadata').textContent = 'No data loaded — drop or select a topology JSON file';

  const overlay = document.createElement('div');
  overlay.id = 'upload-overlay';
  overlay.className = 'upload-overlay';
  overlay.innerHTML = `
    <div class="upload-box" id="drop-zone">
      <div class="upload-icon">📂</div>
      <div class="upload-title">Load Topology Data</div>
      <div class="upload-hint">Drag & drop <code>aws-network-topology.json</code> here</div>
      <div class="upload-or">or</div>
      <label class="upload-btn">
        Choose File
        <input type="file" id="file-input" accept=".json" hidden/>
      </label>
      <details class="upload-help">
        <summary>How to generate this file?</summary>
        <div class="upload-help-body">
          <p>0. Required IAM Permissions (read-only):</p>
          <pre>{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "ec2:DescribeVpcs",
      "ec2:DescribeSubnets",
      "ec2:DescribeRouteTables",
      "ec2:DescribeInternetGateways",
      "ec2:DescribeNatGateways",
      "ec2:DescribeTransitGateways",
      "ec2:DescribeTransitGatewayAttachments",
      "ec2:DescribeTransitGatewayPeeringAttachments",
      "ec2:DescribeTransitGatewayRouteTables",
      "ec2:SearchTransitGatewayRoutes",
      "elasticloadbalancing:DescribeLoadBalancers"
    ],
    "Resource": "*"
  }]
}</pre>
          <p>1. Clone the repo:</p>
          <pre>git clone https://github.com/mandowa/aws-network-topology-viewer.git
cd aws-network-topology-viewer</pre>
          <p>2. Export AWS data (replace <code>PROFILE</code> and <code>REGION</code>):</p>
          <pre>P=PROFILE; R=REGION
aws ec2 describe-vpcs --profile $P --region $R --output json &gt; vpcs.json
aws ec2 describe-subnets --profile $P --region $R --output json &gt; subnets.json
aws ec2 describe-route-tables --profile $P --region $R --output json &gt; route-tables.json
aws ec2 describe-internet-gateways --profile $P --region $R --output json &gt; internet-gateways.json
aws ec2 describe-nat-gateways --profile $P --region $R --output json &gt; nat-gateways.json
aws ec2 describe-transit-gateways --profile $P --region $R --output json &gt; transit-gateways.json
aws ec2 describe-transit-gateway-attachments --profile $P --region $R --output json &gt; tgw-attachments.json
aws ec2 describe-transit-gateway-peering-attachments --profile $P --region $R --output json &gt; tgw-peering-attachments.json
aws ec2 describe-transit-gateway-route-tables --profile $P --region $R --output json &gt; tgw-route-tables.json
aws elbv2 describe-load-balancers --profile $P --region $R --output json &gt; loadbalancers.json</pre>
          <p>3. (Optional) Export TGW routes for each route table:</p>
          <pre>bash fetch-tgw-routes.sh --profile $P --region $R</pre>
          <p>4. Generate the topology file:</p>
          <pre>python3 generate_aws_diagram.py</pre>
          <p>Then upload the generated <code>aws-network-topology.json</code> above.</p>
        </div>
      </details>
    </div>
  `;
  document.body.appendChild(overlay);

  const dropZone = $('drop-zone');
  const fileInput = $('file-input');

  dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('drag-over'); });
  dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
  dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('drag-over');
    const file = e.dataTransfer?.files[0];
    if (file) loadFile(file);
  });
  fileInput.addEventListener('change', (e) => {
    const file = e.target.files?.[0];
    if (file) loadFile(file);
  });

  // Also allow drop on the whole page
  document.body.addEventListener('dragover', (e) => e.preventDefault());
  document.body.addEventListener('drop', (e) => {
    e.preventDefault();
    const file = e.dataTransfer?.files[0];
    if (file) loadFile(file);
  });
}

function loadFile(file) {
  const reader = new FileReader();
  reader.onload = (e) => {
    try {
      data = JSON.parse(e.target.result);
      if (!data?.topology?.vpcs) throw new Error('Invalid topology format');
      boot();
    } catch (err) {
      alert('Failed to parse JSON: ' + err.message);
    }
  };
  reader.readAsText(file);
}

function renderMetadata() {
  const d = data.metadata.generatedAt ? new Date(data.metadata.generatedAt) : null;
  const label = d && !isNaN(d) ? d.toLocaleString() : 'Unknown';
  $('metadata').textContent = `Generated: ${label} | v${data.metadata.schemaVersion || '?'}`;
}

function renderSummary() {
  const s = data.summary;
  const items = [
    ['VPCs', s.vpcCount], ['Subnets', s.subnetCount],
    ['TGWs', s.transitGatewayCount], ['Peers', s.transitGatewayPeeringCount],
    ['IGWs', s.internetGatewayCount], ['NAT', s.natGatewayCount],
    ['LBs', s.loadBalancerCount],
  ];
  $('summary-badges').innerHTML = items
    .map(([l,v]) => `<span class="summary-badge">${l}: ${v||0}</span>`).join('');
}

function renderLegend() {
  let html = '';
  // Node types
  const types = [
    ['VPC', '#1e40af'], ['Transit Gateway', '#b45309'],
    ['Ext TGW Peer', '#0e7490'], ['Ext VPC Peer', '#7e22ce'],
  ];
  types.forEach(([l,c]) => {
    html += `<div class="legend-row"><div class="legend-swatch" style="background:${c}"></div><span>${l}</span></div>`;
  });
  // Edge types
  html += '<div class="legend-divider"></div>';
  html += `<div class="legend-row"><svg width="20" height="10"><line x1="0" y1="5" x2="20" y2="5" stroke="#6366f1" stroke-width="2"/></svg><span>TGW Attachment</span></div>`;
  html += `<div class="legend-row"><svg width="20" height="10"><line x1="0" y1="5" x2="20" y2="5" stroke="#0891b2" stroke-width="1.5" stroke-dasharray="4 2"/></svg><span>TGW Peering</span></div>`;
  html += `<div class="legend-row"><svg width="20" height="10"><line x1="0" y1="5" x2="20" y2="5" stroke="#a855f7" stroke-width="1.5" stroke-dasharray="3 3"/></svg><span>VPC Peering</span></div>`;
  // Subnet categories
  html += '<div class="legend-divider"></div>';
  html += '<div class="legend-subtitle">Subnet Roles</div>';
  Object.entries(CAT_COLORS).forEach(([name, c]) => {
    html += `<div class="legend-row"><div class="legend-swatch" style="background:${c.bg};border-color:${c.border}"></div><span>${c.icon} ${name}</span></div>`;
  });
  $('legend-items').innerHTML = html;
}

// ── Layout Engine ──
// Top-down flow: Internet cloud → VPCs (with IGW/NAT inside) → TGWs → External Peers
// Subnets grouped by category within each AZ lane

function layoutDiagram() {
  const edges = data.topology.edges;
  const vpcs = data.topology.vpcs;
  const tgws = data.topology.transitGateways;
  const extTgws = data.topology.externalTransitGatewayPeers || [];
  const extVpcs = data.topology.externalVpcPeerings || [];

  // Layout constants
  const C = {
    pad: 30,
    subW: 140, subH: 52, subGap: 8,
    azPad: 14, azHeader: 24,
    vpcHeader: 44, vpcPad: 18, vpcGap: 50,
    gwH: 36, gwW: 120, gwGap: 10,
    tgwW: 200, tgwH: 76,
    extW: 180, extH: 64,
  };

  const laid = {};

  // ── VPC Layout ──
  let vpcX = C.pad;
  let maxVpcBottom = 0;

  vpcs.forEach((vpc) => {
    const azs = vpc.availabilityZones || [];
    const igws = vpc.internetGateways || [];
    const nats = vpc.natGateways || [];
    const hasGateways = igws.length > 0 || nats.length > 0;

    // Gateway row height
    const gwRowH = hasGateways ? C.gwH + 16 : 0;

    // Calculate AZ layouts with subnets grouped by category
    let azLayouts = [];
    let maxAzWidth = 0;

    azs.forEach((az) => {
      const subs = az.subnets || [];
      // Group by category, sorted by a priority order
      const catOrder = ['Public Edge', 'Security', 'DMZ', 'Cloud Native', 'Platform', 'Private App', 'Application'];
      const groups = {};
      subs.forEach(s => {
        const cat = s.category || 'Other';
        if (!groups[cat]) groups[cat] = [];
        groups[cat].push(s);
      });

      // Build ordered flat list with category separators
      const orderedSubs = [];
      const catLabels = []; // { cat, startIdx }
      const sortedCats = Object.keys(groups).sort((a, b) => {
        const ai = catOrder.indexOf(a);
        const bi = catOrder.indexOf(b);
        return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
      });

      sortedCats.forEach(cat => {
        catLabels.push({ cat, startIdx: orderedSubs.length });
        groups[cat].forEach(s => orderedSubs.push({ ...s, _cat: cat }));
      });

      const orderedCount = orderedSubs.length;
      // Dynamic columns: up to 4 for many subnets, minimum 1
      const cols = orderedCount <= 3 ? orderedCount : orderedCount <= 8 ? 3 : 4;
      const rows = Math.ceil(orderedCount / (cols || 1));
      const azW = Math.max(cols, 1) * (C.subW + C.subGap) - C.subGap + C.azPad * 2;
      const azH = C.azHeader + rows * (C.subH + C.subGap) - C.subGap + C.azPad + 4;

      maxAzWidth = Math.max(maxAzWidth, azW);
      azLayouts.push({ az: az.availabilityZone, subs: orderedSubs, catLabels, w: azW, h: azH, cols });
    });

    // Normalize all AZ widths to the widest, and recalculate cols to use the space
    const finalAzW = Math.max(maxAzWidth, 300);
    azLayouts.forEach(a => {
      a.w = finalAzW;
      // Recalculate how many cols fit in the normalized width
      const usable = finalAzW - C.azPad * 2 + C.subGap;
      const fitCols = Math.max(1, Math.floor(usable / (C.subW + C.subGap)));
      a.cols = Math.min(fitCols, a.subs.length);
      // Recalculate height with new cols
      const rows = Math.ceil(a.subs.length / (a.cols || 1));
      a.h = C.azHeader + rows * (C.subH + C.subGap) - C.subGap + C.azPad + 4;
    });
    maxAzWidth = finalAzW;

    // Gateway row width
    const gwCount = igws.length + nats.length;
    const gwRowW = gwCount * (C.gwW + C.gwGap) - C.gwGap;

    const vpcW = Math.max(maxAzWidth + C.vpcPad * 2, gwRowW + C.vpcPad * 2 + 20);

    // Total VPC height
    let vpcH = C.vpcHeader + gwRowH;
    azLayouts.forEach(a => { vpcH += a.h + 10; });
    vpcH += C.vpcPad;

    // Position elements inside VPC
    let curY = C.vpcHeader;

    // Gateway icons
    const gatewayPositions = [];
    if (hasGateways) {
      let gwX = (vpcW - gwRowW) / 2;
      igws.forEach(gw => {
        gatewayPositions.push({ ...gw, _type: 'igw', rx: gwX, ry: curY + 4, rw: C.gwW, rh: C.gwH });
        gwX += C.gwW + C.gwGap;
      });
      nats.forEach(gw => {
        gatewayPositions.push({ ...gw, _type: 'nat', rx: gwX, ry: curY + 4, rw: C.gwW, rh: C.gwH });
        gwX += C.gwW + C.gwGap;
      });
      curY += gwRowH;
    }

    // AZ lanes + subnets
    const subnetPositions = [];
    azLayouts.forEach((azLayout) => {
      const azX = C.vpcPad;
      azLayout.rx = azX;
      azLayout.ry = curY;

      azLayout.subs.forEach((sub, idx) => {
        const col = idx % azLayout.cols;
        const row = Math.floor(idx / azLayout.cols);
        subnetPositions.push({
          ...sub,
          rx: azX + C.azPad + col * (C.subW + C.subGap),
          ry: curY + C.azHeader + row * (C.subH + C.subGap),
          rw: C.subW, rh: C.subH,
          azName: azLayout.az,
        });
      });

      curY += azLayout.h + 10;
    });

    laid[vpc.graphNodeId] = {
      x: vpcX, y: C.pad, w: vpcW, h: vpcH,
      type: 'vpc', data: vpc,
      subnets: subnetPositions,
      gateways: gatewayPositions,
      azLayouts,
    };

    maxVpcBottom = Math.max(maxVpcBottom, C.pad + vpcH);
    vpcX += vpcW + C.vpcGap;
  });

  const totalVpcWidth = vpcX - C.vpcGap;

  // ── TGW row (centered below VPCs) ──
  const tgwY = maxVpcBottom + 50;
  const totalTgwW = tgws.length * (C.tgwW + 40) - 40;
  let tgwStartX = Math.max(C.pad, totalVpcWidth / 2 - totalTgwW / 2);

  tgws.forEach((tgw, i) => {
    const rts = tgw.routeTables || [];
    const rtBlockH = rts.length > 0 ? rts.length * 28 + 24 : 0;
    const tgwH = C.tgwH + rtBlockH;
    laid[tgw.graphNodeId] = {
      x: tgwStartX + i * (C.tgwW + 40),
      y: tgwY, w: C.tgwW, h: tgwH,
      type: 'transit-gateway', data: tgw,
    };
  });

  // ── External TGW peers (grouped under their parent TGW, no overlap) ──
  let maxTgwBottom = tgwY;
  Object.values(laid).forEach(n => {
    if (n.type === 'transit-gateway') maxTgwBottom = Math.max(maxTgwBottom, n.y + n.h);
  });
  const extTgwY = maxTgwBottom + 50;
  const peersByTgw = {};
  extTgws.forEach(ext => {
    const localId = ext.LocalTransitGatewayId;
    if (!peersByTgw[localId]) peersByTgw[localId] = [];
    peersByTgw[localId].push(ext);
  });

  // Build groups with ideal X centered under parent TGW
  const peerGap = 18;
  const peerGroups = Object.entries(peersByTgw).map(([localTgwId, peers]) => {
    const parentKey = `tgw:${localTgwId}`;
    const parent = laid[parentKey];
    const parentCx = parent ? parent.x + parent.w / 2 : totalVpcWidth / 2;
    const groupW = peers.length * (C.extW + peerGap) - peerGap;
    return { localTgwId, peers, idealX: parentCx - groupW / 2, w: groupW };
  });

  // Sort groups by idealX so we can resolve left-to-right
  peerGroups.sort((a, b) => a.idealX - b.idealX);

  // Push groups right if they overlap the previous group
  const groupSpacing = 24;
  for (let i = 1; i < peerGroups.length; i++) {
    const prev = peerGroups[i - 1];
    const prevRight = prev.idealX + prev.w + groupSpacing;
    if (peerGroups[i].idealX < prevRight) {
      peerGroups[i].idealX = prevRight;
    }
  }

  // Place each peer node
  peerGroups.forEach(group => {
    group.peers.forEach((ext, i) => {
      laid[ext.graphNodeId] = {
        x: group.idealX + i * (C.extW + peerGap),
        y: extTgwY, w: C.extW, h: C.extH,
        type: 'external-transit-gateway-peer', data: ext,
      };
    });
  });

  // ── External VPC peers (to the right of VPCs) ──
  extVpcs.forEach((ext, i) => {
    laid[ext.graphNodeId] = {
      x: totalVpcWidth + 30,
      y: C.pad + i * (C.extH + 20),
      w: C.extW, h: C.extH,
      type: 'external-vpc-peer', data: ext,
    };
  });

  return { laid, edges };
}

// ── SVG Rendering ──

function renderDiagram() {
  const { laid, edges } = layoutCache;
  const svg = $('diagram-svg');

  let maxX = 0, maxY = 0;
  Object.values(laid).forEach(n => {
    maxX = Math.max(maxX, n.x + n.w + 60);
    maxY = Math.max(maxY, n.y + n.h + 60);
  });

  svg.setAttribute('viewBox', `0 0 ${maxX} ${maxY}`);
  svg.setAttribute('width', maxX);
  svg.setAttribute('height', maxY);

  let s = '';

  // Defs: markers, filters
  s += `<defs>
    <marker id="arr-attach" viewBox="0 0 10 6" refX="9" refY="3" markerWidth="7" markerHeight="5" orient="auto"><path d="M0,0 L10,3 L0,6Z" fill="#6366f1"/></marker>
    <marker id="arr-peer" viewBox="0 0 10 6" refX="9" refY="3" markerWidth="7" markerHeight="5" orient="auto"><path d="M0,0 L10,3 L0,6Z" fill="#0891b2"/></marker>
    <marker id="arr-vpc" viewBox="0 0 10 6" refX="9" refY="3" markerWidth="7" markerHeight="5" orient="auto"><path d="M0,0 L10,3 L0,6Z" fill="#a855f7"/></marker>
    <filter id="shadow" x="-4%" y="-4%" width="108%" height="108%"><feDropShadow dx="0" dy="1" stdDeviation="2" flood-opacity="0.08"/></filter>
  </defs>`;

  // ── Edges ──
  s += '<g class="edges-layer">';
  // Deduplicate: avoid overlapping labels
  const edgeMidpoints = [];

  edges.forEach(edge => {
    const src = laid[edge.source];
    const tgt = laid[edge.target];
    if (!src || !tgt) return;

    const from = connPoint(src, tgt);
    const to = connPoint(tgt, src);

    let cls = 'edge-line';
    let marker = '';
    if (edge.type === 'tgw-attachment') { cls += ' attachment'; marker = 'url(#arr-attach)'; }
    else if (edge.type === 'tgw-peering') { cls += ' peering'; marker = 'url(#arr-peer)'; }
    else if (edge.type === 'vpc-peering') { cls += ' vpc-peering'; marker = 'url(#arr-vpc)'; }

    // Slight curve to avoid overlap
    const mx = (from.x + to.x) / 2;
    const my = (from.y + to.y) / 2;
    const dx = to.x - from.x;
    const dy = to.y - from.y;
    const dist = Math.sqrt(dx*dx + dy*dy) || 1;

    // Offset to avoid overlapping parallel edges
    let offsetIdx = 0;
    edgeMidpoints.forEach(mp => {
      if (Math.abs(mp.mx - mx) < 30 && Math.abs(mp.my - my) < 30) offsetIdx++;
    });
    edgeMidpoints.push({ mx, my });

    const baseOffset = 18;
    const offset = offsetIdx * baseOffset;
    const nx = (-dy / dist) * offset;
    const ny = (dx / dist) * offset;
    const cx = mx + nx;
    const cy = my + ny;

    s += `<path class="${cls}" d="M${from.x},${from.y} Q${cx},${cy} ${to.x},${to.y}" marker-end="${marker}" data-edge-id="${esc(edge.id)}"/>`;

    // Label
    const label = edgeLabel(edge);
    if (label) {
      const lx = cx;
      const ly = cy;
      const tw = label.length * 4.2 + 10;
      s += `<rect x="${lx - tw/2}" y="${ly - 8}" width="${tw}" height="14" rx="3" fill="white" stroke="#e5e7eb" stroke-width="0.5"/>`;
      s += `<text x="${lx}" y="${ly + 2}" text-anchor="middle" class="edge-label-text">${esc(label)}</text>`;
    }
  });
  s += '</g>';

  // ── Nodes ──
  s += '<g class="nodes-layer">';
  Object.entries(laid).forEach(([nodeId, n]) => {
    const sel = selectedId === nodeId ? ' selected' : '';
    s += `<g class="node-group${sel}" data-node-id="${esc(nodeId)}" transform="translate(${n.x},${n.y})">`;
    if (n.type === 'vpc') s += renderVpcNode(n);
    else if (n.type === 'transit-gateway') s += renderTgwNode(n);
    else s += renderExtNode(n);
    s += '</g>';
  });
  s += '</g>';

  // ── Tooltip layer ──
  s += '<g id="tooltip-layer"></g>';

  svg.innerHTML = s;
  applyTransform();

  if (transform.k === 1 && transform.x === 0 && transform.y === 0) fitToScreen();
}

// ── VPC Node ──
function renderVpcNode(n) {
  let s = '';
  const vpc = n.data;
  const style = nodeStyle('vpc');
  const hH = 42;

  // Shadow container
  s += `<rect class="node-box" x="0" y="0" width="${n.w}" height="${n.h}" rx="8" fill="${style.bg}" stroke="${style.border}" stroke-width="1.5" filter="url(#shadow)"/>`;

  // Header
  s += `<rect x="0" y="0" width="${n.w}" height="${hH}" rx="8" fill="${style.header}"/>`;
  s += `<rect x="0" y="${hH-8}" width="${n.w}" height="8" fill="${style.header}"/>`;
  s += `<text class="node-header-text" x="14" y="18" font-size="14">🔲 ${esc(vpc.name)}</text>`;
  const cidrStr = (vpc.cidrBlocks || []).join(' / ');
  s += `<text class="node-header-text" x="14" y="33" font-size="9" opacity="0.75">${esc(vpc.id)}  ·  ${esc(cidrStr)}</text>`;

  // Subnet count summary in header
  const sc = vpc.subnetCounts || {};
  s += `<text class="node-header-text" x="${n.w - 14}" y="18" font-size="9" text-anchor="end" opacity="0.8">${sc.total || 0} subnets (${sc.public || 0} pub / ${sc.private || 0} prv)</text>`;

  // ── Gateway icons inside VPC ──
  if (n.gateways?.length) {
    n.gateways.forEach(gw => {
      const isIgw = gw._type === 'igw';
      const gwColor = isIgw ? '#059669' : '#d97706';
      const gwBg = isIgw ? '#ecfdf5' : '#fffbeb';
      const gwIcon = isIgw ? '🌍' : '🔄';
      const gwLabel = isIgw ? 'IGW' : 'NAT';

      s += `<rect x="${gw.rx}" y="${gw.ry}" width="${gw.rw}" height="${gw.rh}" rx="6" fill="${gwBg}" stroke="${gwColor}" stroke-width="1.5"/>`;
      s += `<text x="${gw.rx + 8}" y="${gw.ry + 15}" font-size="10" font-weight="700" fill="${gwColor}">${gwIcon} ${gwLabel}</text>`;
      s += `<text x="${gw.rx + 8}" y="${gw.ry + 28}" font-size="7.5" font-family="var(--font-mono)" fill="${gwColor}" opacity="0.7">${esc(gw.name || gw.id)}</text>`;
    });
  }

  // ── AZ lanes ──
  if (n.azLayouts) {
    n.azLayouts.forEach(az => {
      // AZ container
      s += `<rect x="${az.rx}" y="${az.ry}" width="${az.w}" height="${az.h}" rx="5" fill="white" fill-opacity="0.5" stroke="#d1d5db" stroke-width="0.75" stroke-dasharray="4 2"/>`;
      // AZ label with icon
      s += `<text class="az-label" x="${az.rx + 10}" y="${az.ry + 16}">⬡ ${esc(az.az)}</text>`;
    });
  }

  // ── Subnets (grouped by category) ──
  if (n.subnets) {
    n.subnets.forEach(sub => {
      const cc = catColor(sub._cat || sub.category);
      s += `<g class="subnet-group" data-subnet-id="${esc(sub.id)}">`;
      // Invisible hit area (ensures clicks register on the whole subnet)
      s += `<rect x="${sub.rx}" y="${sub.ry}" width="${sub.rw}" height="${sub.rh}" fill="transparent" class="subnet-hit"/>`;
      // Subnet card
      s += `<rect class="subnet-rect" x="${sub.rx}" y="${sub.ry}" width="${sub.rw}" height="${sub.rh}" fill="${cc.bg}" stroke="${cc.border}" stroke-width="1" rx="4"/>`;
      // Left category bar
      s += `<rect x="${sub.rx}" y="${sub.ry}" width="4" height="${sub.rh}" rx="2" fill="${cc.text}" pointer-events="none"/>`;

      // Name (truncated)
      const name = sub.displayName || sub.name || sub.id;
      const shortName = name.length > 20 ? name.slice(0, 19) + '…' : name;
      s += `<text x="${sub.rx + 9}" y="${sub.ry + 14}" font-size="9" font-weight="600" fill="${cc.text}" class="subnet-label" pointer-events="none">${esc(shortName)}</text>`;

      // CIDR
      s += `<text x="${sub.rx + 9}" y="${sub.ry + 26}" font-size="8" font-family="var(--font-mono)" fill="#6b7280" pointer-events="none">${esc(sub.cidr)}</text>`;

      // Public/Private
      const pubLabel = sub.isPublic ? 'PUBLIC' : 'PRIVATE';
      const pubColor = sub.isPublic ? '#059669' : '#9ca3af';
      s += `<text x="${sub.rx + sub.rw - 6}" y="${sub.ry + 14}" text-anchor="end" font-size="6.5" font-weight="700" fill="${pubColor}" font-family="var(--font-mono)" pointer-events="none">${pubLabel}</text>`;

      // Category icon + short name
      s += `<text x="${sub.rx + 9}" y="${sub.ry + sub.rh - 7}" font-size="7" fill="${cc.text}" opacity="0.65" pointer-events="none">${cc.icon} ${esc(sub._cat || sub.category || '')}</text>`;

      // Route count
      const routeCount = (sub.routeSummary || []).length;
      if (routeCount > 0) {
        s += `<text x="${sub.rx + sub.rw - 6}" y="${sub.ry + sub.rh - 7}" text-anchor="end" font-size="6.5" fill="#9ca3af" font-family="var(--font-mono)" pointer-events="none">${routeCount} routes</text>`;
      }
      s += '</g>';
    });
  }

  return s;
}

// ── TGW Node ──
function renderTgwNode(n) {
  let s = '';
  const tgw = n.data;
  const style = nodeStyle('transit-gateway');
  const hH = 32;
  const rts = tgw.routeTables || [];
  const rtBlockH = rts.length > 0 ? rts.length * 28 + 20 : 0;

  s += `<rect class="node-box" x="0" y="0" width="${n.w}" height="${n.h}" rx="8" fill="${style.bg}" stroke="${style.border}" stroke-width="2" filter="url(#shadow)"/>`;
  s += `<rect x="0" y="0" width="${n.w}" height="${hH}" rx="8" fill="${style.header}"/>`;
  s += `<rect x="0" y="${hH-8}" width="${n.w}" height="8" fill="${style.header}"/>`;

  s += `<text class="node-header-text" x="12" y="21" font-size="12">🔀 ${esc(tgw.name || tgw.id)}</text>`;

  // Details
  s += `<text x="12" y="${hH + 16}" font-size="8.5" font-family="var(--font-mono)" fill="#92400e">${esc(tgw.id)}</text>`;
  s += `<text x="12" y="${hH + 30}" font-size="9" fill="#78350f">Attachments: ${tgw.attachmentCount || 0}  ·  Peerings: ${tgw.peeringCount || 0}</text>`;

  // State badge
  const stateColor = tgw.state === 'available' ? '#059669' : '#dc2626';
  s += `<rect x="${n.w - 60}" y="${hH + 8}" width="48" height="16" rx="8" fill="${stateColor}" fill-opacity="0.1" stroke="${stateColor}" stroke-width="0.5"/>`;
  s += `<text x="${n.w - 36}" y="${hH + 19}" text-anchor="middle" font-size="7.5" font-weight="600" fill="${stateColor}">${esc(tgw.state)}</text>`;

  // Route Tables
  if (rts.length > 0) {
    const rtY = hH + 42;
    s += `<line x1="8" y1="${rtY}" x2="${n.w - 8}" y2="${rtY}" stroke="#fcd34d" stroke-width="0.5"/>`;
    s += `<text x="12" y="${rtY + 13}" font-size="8" font-weight="700" fill="#92400e" text-transform="uppercase">Route Tables</text>`;

    rts.forEach((rt, i) => {
      const ry = rtY + 18 + i * 28;
      const isDefault = rt.defaultAssociation || rt.defaultPropagation;
      const rtBg = isDefault ? '#fef3c7' : '#fffbeb';
      const rtBorder = isDefault ? '#f59e0b' : '#fde68a';

      s += `<rect x="8" y="${ry}" width="${n.w - 16}" height="24" rx="4" fill="${rtBg}" stroke="${rtBorder}" stroke-width="0.75"/>`;
      s += `<text x="14" y="${ry + 10}" font-size="8" font-weight="600" fill="#78350f">📋 ${esc(rt.name)}</text>`;
      s += `<text x="14" y="${ry + 20}" font-size="7" font-family="var(--font-mono)" fill="#92400e" opacity="0.7">${esc(rt.id)}</text>`;

      // Default badges
      if (rt.defaultAssociation) {
        s += `<rect x="${n.w - 80}" y="${ry + 2}" width="36" height="10" rx="5" fill="#f59e0b" fill-opacity="0.2"/>`;
        s += `<text x="${n.w - 62}" y="${ry + 9.5}" text-anchor="middle" font-size="5.5" font-weight="600" fill="#92400e">assoc</text>`;
      }
      if (rt.defaultPropagation) {
        s += `<rect x="${n.w - 42}" y="${ry + 2}" width="32" height="10" rx="5" fill="#f59e0b" fill-opacity="0.2"/>`;
        s += `<text x="${n.w - 26}" y="${ry + 9.5}" text-anchor="middle" font-size="5.5" font-weight="600" fill="#92400e">prop</text>`;
      }
    });
  }

  return s;
}

// ── External Node (TGW peer / VPC peer) ──
function renderExtNode(n) {
  let s = '';
  const d = n.data;
  const style = nodeStyle(n.type);
  const hH = 28;

  s += `<rect class="node-box" x="0" y="0" width="${n.w}" height="${n.h}" rx="8" fill="${style.bg}" stroke="${style.border}" stroke-width="1.5" stroke-dasharray="6 3" filter="url(#shadow)"/>`;
  s += `<rect x="0" y="0" width="${n.w}" height="${hH}" rx="8" fill="${style.header}"/>`;
  s += `<rect x="0" y="${hH-8}" width="${n.w}" height="8" fill="${style.header}"/>`;

  const icon = n.type === 'external-transit-gateway-peer' ? '🌐' : '🔗';
  const label = d.Name || d.name || d.label || d.id || '';
  s += `<text class="node-header-text" x="10" y="18" font-size="10">${icon} ${esc(label)}</text>`;

  // Body
  if (n.type === 'external-transit-gateway-peer') {
    s += `<text x="10" y="${hH + 14}" font-size="8" font-family="var(--font-mono)" fill="#155e75">${esc(d.RemoteRegion || '')} · ${esc(d.RemoteTransitGatewayId || '')}</text>`;
    s += `<text x="10" y="${hH + 27}" font-size="7.5" fill="#6b7280">Account: ${esc(d.RemoteAccountId || '?')}</text>`;
  } else {
    s += `<text x="10" y="${hH + 14}" font-size="8" font-family="var(--font-mono)" fill="#5b21b6">${esc(d.VpcPeeringConnectionId || '')}</text>`;
    const dests = (d.Destinations || []).join(', ');
    if (dests) s += `<text x="10" y="${hH + 27}" font-size="7.5" fill="#6b7280">→ ${esc(dests)}</text>`;
  }

  return s;
}

// ── Edge helpers ──

function connPoint(from, to) {
  const fcx = from.x + from.w / 2;
  const fcy = from.y + from.h / 2;
  const tcx = to.x + to.w / 2;
  const tcy = to.y + to.h / 2;
  const dx = tcx - fcx;
  const dy = tcy - fcy;
  const absDx = Math.abs(dx) || 0.01;
  const absDy = Math.abs(dy) || 0.01;
  const hw = from.w / 2;
  const hh = from.h / 2;

  if (absDx / hw > absDy / hh) {
    const side = dx > 0 ? from.x + from.w : from.x;
    const t = hw / absDx;
    return { x: side, y: Math.max(from.y, Math.min(from.y + from.h, fcy + dy * t)) };
  } else {
    const side = dy > 0 ? from.y + from.h : from.y;
    const t = hh / absDy;
    return { x: Math.max(from.x, Math.min(from.x + from.w, fcx + dx * t)), y: side };
  }
}

function edgeLabel(edge) {
  if (edge.type === 'tgw-attachment') {
    const parts = (edge.displayLabel || '').split('\n');
    return parts[0] || '';
  }
  if (edge.type === 'vpc-peering') return 'VPC Peering';
  return '';
}

// ── Pan / Zoom ──

function applyTransform() {
  const svg = $('diagram-svg');
  const t = `translate(${transform.x},${transform.y}) scale(${transform.k})`;
  svg.querySelectorAll('.edges-layer, .nodes-layer, #tooltip-layer').forEach(el => {
    el.setAttribute('transform', t);
  });
}

function fitToScreen() {
  const svg = $('diagram-svg');
  const wrap = document.querySelector('.canvas-wrap');
  const vb = svg.getAttribute('viewBox');
  if (!vb) return;
  const [, , vw, vh] = vb.split(' ').map(Number);
  const cw = wrap.clientWidth;
  const ch = wrap.clientHeight;
  const scale = Math.min(cw / vw, ch / vh) * 0.9;
  transform.k = scale;
  transform.x = (cw - vw * scale) / 2;
  transform.y = (ch - vh * scale) / 2;
  applyTransform();
}

function zoom(delta) {
  const wrap = document.querySelector('.canvas-wrap');
  const cx = wrap.clientWidth / 2;
  const cy = wrap.clientHeight / 2;
  const newK = Math.max(0.05, Math.min(6, transform.k + delta));
  const ratio = newK / transform.k;
  transform.x = cx - (cx - transform.x) * ratio;
  transform.y = cy - (cy - transform.y) * ratio;
  transform.k = newK;
  applyTransform();
}

// ── Tooltip (hover on subnet) ──

function showTooltip(sub, screenX, screenY) {
  const tip = $('tooltip-el');
  if (tip) tip.remove();

  const div = document.createElement('div');
  div.id = 'tooltip-el';
  div.className = 'tooltip';
  const cc = catColor(sub._cat || sub.category);
  const routes = (sub.routeSummary || []).map(r => `<div class="tip-route">${esc(r)}</div>`).join('') || '<div class="tip-muted">No routes</div>';

  div.innerHTML = `
    <div class="tip-header" style="border-left:3px solid ${cc.text}">
      <div class="tip-name">${esc(sub.displayName || sub.name)}</div>
      <div class="tip-meta">${esc(sub.cidr)} · ${sub.isPublic ? 'Public' : 'Private'} · ${esc(sub._cat || sub.category || '')}</div>
    </div>
    <div class="tip-section">
      <div class="tip-label">Routes</div>
      ${routes}
    </div>
  `;

  div.style.left = screenX + 12 + 'px';
  div.style.top = screenY - 10 + 'px';
  document.body.appendChild(div);

  // Keep in viewport
  const rect = div.getBoundingClientRect();
  if (rect.right > window.innerWidth) div.style.left = (screenX - rect.width - 12) + 'px';
  if (rect.bottom > window.innerHeight) div.style.top = (screenY - rect.height) + 'px';
}

function hideTooltip() {
  const tip = $('tooltip-el');
  if (tip) tip.remove();
}

// ── Detail Panel ──

function showPanel(nodeId) {
  selectedId = nodeId;
  const node = data.topology.nodes.find(n => n.id === nodeId);
  if (!node) return;

  $('panel-title').textContent = node.label || node.id;
  let html = '';

  if (node.type === 'vpc') {
    const vpc = data.topology.vpcs.find(v => v.graphNodeId === nodeId);
    if (vpc) html = vpcPanelHtml(vpc);
  } else if (node.type === 'transit-gateway') {
    const tgw = data.topology.transitGateways.find(t => t.graphNodeId === nodeId);
    if (tgw) html = tgwPanelHtml(tgw);
  } else if (node.type === 'external-transit-gateway-peer') {
    const ext = (data.topology.externalTransitGatewayPeers || []).find(t => t.graphNodeId === nodeId);
    if (ext) html = extTgwPanelHtml(ext);
  } else if (node.type === 'external-vpc-peer') {
    const ext = (data.topology.externalVpcPeerings || []).find(v => v.graphNodeId === nodeId);
    if (ext) html = extVpcPanelHtml(ext);
  }

  // Relationships
  const rels = data.topology.edges.filter(e => e.source === nodeId || e.target === nodeId);
  if (rels.length) {
    html += sec('Relationships');
    rels.forEach(e => {
      const isOut = e.source === nodeId;
      const other = data.topology.indexes.nodeById[isOut ? e.target : e.source];
      html += `<div class="subnet-mini">
        <div class="subnet-mini-header"><span class="subnet-mini-name">${esc(e.type)}</span>
        <span class="subnet-mini-badge ${isOut ? 'public' : 'private'}">${isOut ? '→ out' : '← in'}</span></div>
        <div style="font-size:0.75rem;color:#6b7280">${esc(other?.label || '?')}</div>
        ${e.state ? row('State', e.state) : ''}
      </div>`;
    });
    html += '</div>';
  }

  $('panel-body').innerHTML = html;
  $('detail-panel').classList.remove('hidden');

  document.querySelectorAll('.node-group').forEach(g => g.classList.remove('selected'));
  const el = document.querySelector(`[data-node-id="${CSS.escape(nodeId)}"]`);
  if (el) el.classList.add('selected');
}

function hidePanel() {
  selectedId = null;
  $('detail-panel').classList.add('hidden');
  document.querySelectorAll('.node-group').forEach(g => g.classList.remove('selected'));
}

// Panel renderers
function sec(title) { return `<div class="panel-section"><div class="panel-section-title">${esc(title)}</div>`; }
function row(l, v) { return `<div class="panel-row"><span class="panel-label">${esc(l)}</span><span class="panel-value">${esc(v ?? '-')}</span></div>`; }
function badges(items) { return '<div class="panel-badge-list">' + items.map(i => `<span class="panel-badge">${esc(i)}</span>`).join('') + '</div>'; }

function toggleRoutes(elId) {
  const el = document.getElementById(elId);
  if (!el) return;
  const btn = el.previousElementSibling;
  if (el.style.display === 'none') {
    el.style.display = 'block';
    if (btn) btn.textContent = btn.textContent.replace('▶', '▼');
  } else {
    el.style.display = 'none';
    if (btn) btn.textContent = btn.textContent.replace('▼', '▶');
  }
}

// Map a route targetSummary (e.g. "vpc:vpc-xxx" or "peering:tgw-xxx") to a graph node ID
function resolveRouteTarget(targetSummary) {
  if (!targetSummary || !data) return null;
  // targetSummary format: "resourceType:resourceId"
  const parts = targetSummary.split(':');
  if (parts.length < 2) return null;
  const resType = parts[0];
  const resId = parts.slice(1).join(':');

  // Search all nodes for a matching resourceId
  const nodes = data.topology.nodes;
  for (const node of nodes) {
    if (node.resourceId === resId) return node.id;
  }
  // Also try matching VPC IDs directly
  if (resType === 'vpc') {
    const match = nodes.find(n => n.type === 'vpc' && n.resourceId === resId);
    if (match) return match.id;
  }
  // Try matching TGW peering targets (the resourceId in external-tgw-peer nodes)
  if (resType === 'peering') {
    const match = nodes.find(n =>
      n.type === 'external-transit-gateway-peer' && n.resourceId === resId
    );
    if (match) return match.id;
  }
  return null;
}

// Highlight a target node on the diagram: flash it and pan to it
function highlightTarget(nodeId) {
  if (!nodeId || !layoutCache) return;

  // Remove previous highlights
  document.querySelectorAll('.node-group.highlight-pulse').forEach(el => el.classList.remove('highlight-pulse'));

  // Find the SVG node
  const el = document.querySelector(`[data-node-id="${CSS.escape(nodeId)}"]`);
  if (!el) return;

  // Add highlight class
  el.classList.add('highlight-pulse');

  // Pan the diagram to center on this node
  const node = layoutCache.laid[nodeId];
  if (node) {
    const wrap = document.querySelector('.canvas-wrap');
    const cx = wrap.clientWidth / 2;
    const cy = wrap.clientHeight / 2;
    const nodeCx = node.x + node.w / 2;
    const nodeCy = node.y + node.h / 2;
    transform.x = cx - nodeCx * transform.k;
    transform.y = cy - nodeCy * transform.k;
    applyTransform();
  }

  // Remove pulse after animation
  setTimeout(() => el.classList.remove('highlight-pulse'), 2000);
}

function vpcPanelHtml(vpc) {
  let h = sec('Network');
  h += row('VPC ID', vpc.id) + row('CIDRs', (vpc.cidrBlocks||[]).join(', '));
  h += row('Subnets', `${vpc.subnetCounts?.total || 0} (${vpc.subnetCounts?.public || 0} pub / ${vpc.subnetCounts?.private || 0} prv)`);
  h += '</div>';

  if (vpc.roleSummary) h += sec('Roles') + `<div style="font-size:0.78rem">${esc(vpc.roleSummary)}</div></div>`;

  if (vpc.internetGateways?.length) {
    h += sec('Internet Gateways');
    vpc.internetGateways.forEach(gw => { h += `<div class="subnet-mini"><div class="subnet-mini-name">🌍 ${esc(gw.name)}</div><div style="font-size:0.7rem;color:#6b7280">${esc(gw.id)}</div></div>`; });
    h += '</div>';
  }
  if (vpc.natGateways?.length) {
    h += sec('NAT Gateways');
    vpc.natGateways.forEach(gw => { h += `<div class="subnet-mini"><div class="subnet-mini-name">🔄 ${esc(gw.name)}</div>${row('State', gw.state)}${row('Public IP', (gw.publicIps||[]).join(', '))}</div>`; });
    h += '</div>';
  }

  (vpc.availabilityZones || []).forEach(az => {
    h += sec(az.availabilityZone);
    (az.subnets || []).forEach(sub => {
      const cc = catColor(sub.category);
      h += `<div class="subnet-mini" style="border-left:3px solid ${cc.text}">
        <div class="subnet-mini-header"><span class="subnet-mini-name">${cc.icon} ${esc(sub.displayName || sub.name)}</span>
        <span class="subnet-mini-badge ${sub.isPublic?'public':'private'}">${sub.isPublic?'public':'private'}</span></div>
        ${row('CIDR', sub.cidr)}${row('Category', sub.category)}`;
      if (sub.routeSummary?.length) {
        h += '<div style="margin-top:4px"><div style="font-size:0.65rem;color:#9ca3af;text-transform:uppercase">Routes</div>' + badges(sub.routeSummary) + '</div>';
      }
      h += '</div>';
    });
    h += '</div>';
  });

  if (vpc.loadBalancers?.length) {
    h += sec(`Load Balancers (${vpc.loadBalancers.length})`);
    vpc.loadBalancers.slice(0, 10).forEach(lb => {
      h += `<div class="subnet-mini"><div class="subnet-mini-header"><span class="subnet-mini-name">${esc(lb.name)}</span><span class="subnet-mini-badge ${lb.isPublic?'public':'private'}">${lb.type}</span></div></div>`;
    });
    if (vpc.loadBalancers.length > 10) h += `<div style="font-size:0.72rem;color:#9ca3af">+${vpc.loadBalancers.length - 10} more</div>`;
    h += '</div>';
  }
  return h;
}

function tgwPanelHtml(tgw) {
  let h = sec('Configuration');
  h += row('TGW ID', tgw.id) + row('State', tgw.state) + row('Owner', tgw.ownerId);
  h += row('Attachments', tgw.attachmentCount) + row('Peerings', tgw.peeringCount);
  h += '</div>' + sec('Attached VPCs') + badges(tgw.attachedVpcIds || []) + '</div>';

  const rts = tgw.routeTables || [];
  if (rts.length) {
    h += sec(`Route Tables (${rts.length})`);
    rts.forEach((rt, idx) => {
      const tags = [];
      if (rt.defaultAssociation) tags.push('Default Association');
      if (rt.defaultPropagation) tags.push('Default Propagation');
      const routes = rt.routes || [];
      const rtElId = `rt-toggle-${idx}`;

      h += `<div class="subnet-mini" style="border-left:3px solid #f59e0b">
        <div class="subnet-mini-header">
          <span class="subnet-mini-name">📋 ${esc(rt.name)}</span>
          <span class="subnet-mini-badge ${rt.state === 'available' ? 'public' : 'private'}">${esc(rt.state)}</span>
        </div>
        ${row('ID', rt.id)}
        ${tags.length ? '<div class="panel-badge-list" style="margin-top:4px">' + tags.map(t => `<span class="panel-badge" style="background:#fef3c7;border-color:#fcd34d;color:#92400e">${esc(t)}</span>`).join('') + '</div>' : ''}
        <div class="rt-toggle" style="margin-top:6px">
          <button class="rt-expand-btn" onclick="toggleRoutes('${rtElId}')">
            ▶ Routes (${routes.length})
          </button>
          <div id="${rtElId}" class="rt-routes-list" style="display:none">
            ${routes.length === 0 ? '<div style="font-size:0.72rem;color:#9ca3af;padding:4px 0">No routes</div>' : ''}
            <table class="rt-table">
              <thead><tr><th>Destination</th><th>Target</th><th>Type</th><th>State</th></tr></thead>
              <tbody>
                ${routes.map(r => {
                  const stColor = r.state === 'active' ? '#059669' : '#dc2626';
                  const typeColor = r.type === 'static' ? '#2563eb' : '#7c3aed';
                  const nodeId = resolveRouteTarget(r.targetSummary);
                  const targetHtml = nodeId
                    ? `<a href="#" class="rt-target-link" onclick="event.preventDefault();highlightTarget('${esc(nodeId)}')">${esc(r.targetSummary)}</a>`
                    : esc(r.targetSummary);
                  return `<tr>
                    <td class="rt-dest">${esc(r.destination)}</td>
                    <td class="rt-target">${targetHtml}</td>
                    <td><span class="rt-type-badge" style="color:${typeColor}">${esc(r.type)}</span></td>
                    <td><span style="color:${stColor};font-weight:600">${esc(r.state)}</span></td>
                  </tr>`;
                }).join('')}
              </tbody>
            </table>
          </div>
        </div>
      </div>`;
    });
    h += '</div>';
  }
  return h;
}

function extTgwPanelHtml(ext) {
  let h = sec('Peer Details');
  h += row('Name', ext.Name) + row('State', ext.State);
  h += row('Local TGW', ext.LocalTransitGatewayId) + row('Remote TGW', ext.RemoteTransitGatewayId);
  h += row('Remote Account', ext.RemoteAccountId) + row('Remote Region', ext.RemoteRegion);
  h += row('Attachment', ext.TransitGatewayAttachmentId) + '</div>';
  return h;
}

function extVpcPanelHtml(ext) {
  let h = sec('VPC Peering');
  h += row('Connection', ext.VpcPeeringConnectionId) + row('Source VPC', ext.SourceVpcName || ext.SourceVpcId);
  h += '</div>' + sec('Destinations') + badges(ext.Destinations || []) + '</div>';
  return h;
}

// ── Subnet Panel with Route Trace ──

function showSubnetPanel(sub, parentNodeId) {
  hideTooltip();
  const cc = catColor(sub._cat || sub.category);

  let h = sec('Subnet');
  h += row('Name', sub.displayName || sub.name);
  h += row('ID', sub.id);
  h += row('CIDR', sub.cidr);
  h += row('AZ', sub.azName || sub.availabilityZone || '-');
  h += row('Category', sub._cat || sub.category || '-');
  h += row('Public', sub.isPublic ? 'Yes' : 'No');
  h += '</div>';

  // Route entries
  const entries = sub.routeEntries || [];
  if (entries.length) {
    h += sec(`Route Table (${entries.length} entries)`);
    h += '<table class="rt-table"><thead><tr><th>Destination</th><th>Next Hop</th><th>Type</th></tr></thead><tbody>';
    entries.forEach(r => {
      const hopLabel = r.nextHopType === 'local' ? 'local' : `${r.nextHopType}: ${r.nextHopId}`;
      h += `<tr><td class="rt-dest">${esc(r.destination)}</td><td class="rt-target">${esc(hopLabel)}</td><td>${esc(r.state)}</td></tr>`;
    });
    h += '</tbody></table></div>';
  }

  // Route Trace input
  h += `<div class="panel-section">
    <div class="panel-section-title">🔍 Route Trace</div>
    <div class="trace-input-row">
      <input type="text" id="trace-dest" class="trace-input" placeholder="e.g. 10.199.1.5 or 8.8.8.8" autocomplete="off"/>
      <button class="trace-btn" onclick="runTrace('${esc(sub.id)}','${esc(parentNodeId)}')">Trace</button>
    </div>
    <div id="trace-result"></div>
  </div>`;

  $('panel-title').textContent = `${cc.icon} ${sub.displayName || sub.name}`;
  $('panel-body').innerHTML = h;
  $('detail-panel').classList.remove('hidden');

  // Focus the input
  setTimeout(() => { const inp = $('trace-dest'); if (inp) inp.focus(); }, 100);

  // Enter key to trace
  const inp = $('trace-dest');
  if (inp) inp.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') runTrace(sub.id, parentNodeId);
  });
}

// ── Route Trace Engine ──

function runTrace(subnetId, parentNodeId) {
  const destInput = ($('trace-dest')?.value || '').trim();
  if (!destInput) return;

  // Normalize: if user typed a bare IP, treat as /32
  const destIP = destInput.includes('/') ? destInput.split('/')[0] : destInput;

  const steps = [];
  const highlighted = [];

  // Step 1: Find the subnet and its VPC
  const subnetInfo = findSubnet(subnetId);
  if (!subnetInfo) {
    $('trace-result').innerHTML = traceError('Subnet not found');
    return;
  }

  steps.push({ icon: '📍', label: 'Source', detail: `${subnetInfo.name} (${subnetInfo.cidr})`, id: parentNodeId });

  // Step 2: Longest prefix match on subnet's route table
  const routeEntries = subnetInfo.routeEntries || [];
  const matched = longestPrefixMatch(destIP, routeEntries);

  if (!matched) {
    steps.push({ icon: '❌', label: 'No Route', detail: `No matching route for ${destIP}`, id: null });
    $('trace-result').innerHTML = renderTraceSteps(steps);
    return;
  }

  steps.push({ icon: '📋', label: 'VPC Route Match', detail: `${matched.destination} → ${matched.nextHopType}: ${matched.nextHopId}`, id: null });

  if (matched.nextHopType === 'local') {
    steps.push({ icon: '✅', label: 'Local Delivery', detail: `Destination is within VPC CIDR`, id: parentNodeId });
    $('trace-result').innerHTML = renderTraceSteps(steps);
    highlightTraceNodes(steps);
    return;
  }

  if (matched.nextHopType === 'gateway' && matched.nextHopId.startsWith('igw-')) {
    const nodeId = resolveRouteTarget(`gateway:${matched.nextHopId}`);
    steps.push({ icon: '🌍', label: 'Internet Gateway', detail: matched.nextHopId, id: nodeId || parentNodeId });
    steps.push({ icon: '🌐', label: 'Internet', detail: destIP, id: null });
    $('trace-result').innerHTML = renderTraceSteps(steps);
    highlightTraceNodes(steps);
    return;
  }

  if (matched.nextHopType === 'nat-gateway') {
    steps.push({ icon: '🔄', label: 'NAT Gateway', detail: matched.nextHopId, id: parentNodeId });
    steps.push({ icon: '🌐', label: 'Internet (via NAT)', detail: destIP, id: null });
    $('trace-result').innerHTML = renderTraceSteps(steps);
    highlightTraceNodes(steps);
    return;
  }

  if (matched.nextHopType === 'instance') {
    steps.push({ icon: '🖥️', label: 'EC2 Instance (ENI)', detail: matched.nextHopId, id: null });
    steps.push({ icon: '⚠️', label: 'Appliance Routing', detail: 'Traffic forwarded by instance (e.g. firewall)', id: null });
    $('trace-result').innerHTML = renderTraceSteps(steps);
    highlightTraceNodes(steps);
    return;
  }

  if (matched.nextHopType === 'vpc-peering') {
    const nodeId = resolveRouteTarget(`peering:${matched.nextHopId}`) || resolveRouteTarget(`vpc-peering:${matched.nextHopId}`);
    steps.push({ icon: '🔗', label: 'VPC Peering', detail: matched.nextHopId, id: nodeId });
    steps.push({ icon: '📍', label: 'Peer VPC', detail: destIP, id: nodeId });
    $('trace-result').innerHTML = renderTraceSteps(steps);
    highlightTraceNodes(steps);
    return;
  }

  // Transit Gateway — continue tracing through TGW route tables
  if (matched.nextHopType === 'transit-gateway') {
    const tgwId = matched.nextHopId;
    const tgwNodeId = `tgw:${tgwId}`;
    steps.push({ icon: '🔀', label: 'Transit Gateway', detail: tgwId, id: tgwNodeId });

    // Find TGW and its route tables
    const tgw = data.topology.transitGateways.find(t => t.id === tgwId);
    if (!tgw) {
      steps.push({ icon: '⚠️', label: 'TGW Not Found', detail: `${tgwId} not in local data`, id: null });
      $('trace-result').innerHTML = renderTraceSteps(steps);
      highlightTraceNodes(steps);
      return;
    }

    // Search all TGW route tables for a match
    const allTgwRoutes = [];
    (tgw.routeTables || []).forEach(rt => {
      (rt.routes || []).forEach(r => {
        allTgwRoutes.push({ ...r, routeTableName: rt.name, routeTableId: rt.id });
      });
    });

    const tgwMatch = longestPrefixMatch(destIP, allTgwRoutes.map(r => ({
      destination: r.destination,
      nextHopId: r.targetSummary?.split(':').slice(1).join(':') || r.targetSummary || '',
      nextHopType: r.targetSummary?.split(':')[0] || '',
      state: r.state,
      _orig: r,
    })));

    if (!tgwMatch) {
      steps.push({ icon: '🕳️', label: 'Blackhole / No TGW Route', detail: `No TGW route for ${destIP}`, id: null });
      $('trace-result').innerHTML = renderTraceSteps(steps);
      highlightTraceNodes(steps);
      return;
    }

    const origRoute = allTgwRoutes.find(r => r.destination === tgwMatch.destination);
    steps.push({ icon: '📋', label: `TGW Route (${origRoute?.routeTableName || '?'})`, detail: `${tgwMatch.destination} → ${tgwMatch.nextHopType}: ${tgwMatch.nextHopId}`, id: null });

    // Resolve TGW next hop
    const tgwTargetNodeId = resolveRouteTarget(`${tgwMatch.nextHopType}:${tgwMatch.nextHopId}`);

    if (tgwMatch.nextHopType === 'vpc') {
      const targetVpc = data.topology.vpcs.find(v => v.id === tgwMatch.nextHopId);
      const vpcLabel = targetVpc ? targetVpc.name : tgwMatch.nextHopId;
      steps.push({ icon: '🔲', label: `Destination VPC: ${vpcLabel}`, detail: tgwMatch.nextHopId, id: tgwTargetNodeId || `vpc:${tgwMatch.nextHopId}` });
    } else if (tgwMatch.nextHopType === 'peering') {
      const peerNode = data.topology.nodes.find(n => n.resourceId === tgwMatch.nextHopId);
      steps.push({ icon: '🌐', label: `TGW Peering: ${peerNode?.label || tgwMatch.nextHopId}`, detail: `Remote TGW ${tgwMatch.nextHopId}`, id: tgwTargetNodeId });
    } else {
      steps.push({ icon: '➡️', label: 'Next Hop', detail: `${tgwMatch.nextHopType}: ${tgwMatch.nextHopId}`, id: tgwTargetNodeId });
    }

    $('trace-result').innerHTML = renderTraceSteps(steps);
    highlightTraceNodes(steps);
    return;
  }

  // Fallback
  steps.push({ icon: '➡️', label: matched.nextHopType, detail: matched.nextHopId, id: null });
  $('trace-result').innerHTML = renderTraceSteps(steps);
  highlightTraceNodes(steps);
}

// ── Trace helpers ──

function findSubnet(subnetId) {
  for (const vpc of data.topology.vpcs) {
    for (const az of (vpc.availabilityZones || [])) {
      for (const sub of (az.subnets || [])) {
        if (sub.id === subnetId) return sub;
      }
    }
  }
  return null;
}

function ipToNum(ip) {
  const parts = ip.split('.').map(Number);
  return ((parts[0] << 24) | (parts[1] << 16) | (parts[2] << 8) | parts[3]) >>> 0;
}

function cidrContains(cidr, ip) {
  if (!cidr || !cidr.includes('/')) return false;
  const [net, bits] = cidr.split('/');
  const mask = bits === '0' ? 0 : (~0 << (32 - parseInt(bits))) >>> 0;
  return (ipToNum(net) & mask) === (ipToNum(ip) & mask);
}

function longestPrefixMatch(ip, routes) {
  let best = null;
  let bestBits = -1;

  for (const r of routes) {
    const dest = r.destination;
    if (!dest || !dest.includes('/')) continue;
    const bits = parseInt(dest.split('/')[1]);
    if (cidrContains(dest, ip) && bits > bestBits) {
      best = r;
      bestBits = bits;
    }
  }
  // Also check 0.0.0.0/0 default route
  if (!best) {
    best = routes.find(r => r.destination === '0.0.0.0/0');
  }
  return best;
}

function renderTraceSteps(steps) {
  return `<div class="trace-path">${steps.map((s, i) => {
    const clickable = s.id ? ` onclick="highlightTarget('${esc(s.id)}')" style="cursor:pointer"` : '';
    const arrow = i < steps.length - 1 ? '<div class="trace-arrow">↓</div>' : '';
    return `<div class="trace-step"${clickable}>
      <span class="trace-icon">${s.icon}</span>
      <div class="trace-step-body">
        <div class="trace-step-label">${esc(s.label)}</div>
        <div class="trace-step-detail">${esc(s.detail)}</div>
      </div>
    </div>${arrow}`;
  }).join('')}</div>`;
}

function traceError(msg) {
  return `<div class="trace-error">${esc(msg)}</div>`;
}

function highlightTraceNodes(steps) {
  // Clear previous
  document.querySelectorAll('.node-group.highlight-pulse').forEach(el => el.classList.remove('highlight-pulse'));
  // Highlight all nodes in the path
  steps.forEach(s => {
    if (!s.id) return;
    const el = document.querySelector(`[data-node-id="${CSS.escape(s.id)}"]`);
    if (el) el.classList.add('highlight-pulse');
  });
  // Remove after 3s
  setTimeout(() => {
    document.querySelectorAll('.node-group.highlight-pulse').forEach(el => el.classList.remove('highlight-pulse'));
  }, 3000);
}

// ── Events ──

function setupEvents() {
  const wrap = document.querySelector('.canvas-wrap');

  // Pan
  wrap.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;
    drag = { sx: e.clientX - transform.x, sy: e.clientY - transform.y, moved: false };
    wrap.style.cursor = 'grabbing';
  });
  document.addEventListener('mousemove', (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.sx;
    const dy = e.clientY - drag.sy;
    if (Math.abs(dx - transform.x) > 3 || Math.abs(dy - transform.y) > 3) drag.moved = true;
    transform.x = dx;
    transform.y = dy;
    applyTransform();
  });
  document.addEventListener('mouseup', () => {
    drag = null;
    wrap.style.cursor = 'grab';
  });

  // Zoom (wheel)
  wrap.addEventListener('wheel', (e) => {
    e.preventDefault();
    const rect = wrap.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const factor = e.deltaY > 0 ? 0.92 : 1.08;
    const newK = Math.max(0.05, Math.min(6, transform.k * factor));
    const ratio = newK / transform.k;
    transform.x = mx - (mx - transform.x) * ratio;
    transform.y = my - (my - transform.y) * ratio;
    transform.k = newK;
    applyTransform();
  }, { passive: false });

  // Click
  wrap.addEventListener('click', (e) => {
    if (drag?.moved) return;

    // Check if a subnet was clicked (via the subnet-group wrapper)
    const subnetGroup = e.target.closest('.subnet-group');
    if (subnetGroup) {
      const subnetId = subnetGroup.getAttribute('data-subnet-id');
      const nodeGroup = subnetGroup.closest('.node-group');
      const nodeId = nodeGroup?.getAttribute('data-node-id');
      if (subnetId && nodeId) {
        const node = layoutCache?.laid[nodeId];
        const sub = node?.subnets?.find(s => s.id === subnetId);
        if (sub) {
          showSubnetPanel(sub, nodeId);
          return;
        }
      }
    }

    const nodeEl = e.target.closest('.node-group');
    if (nodeEl) {
      showPanel(nodeEl.getAttribute('data-node-id'));
    } else {
      hidePanel();
    }
  });

  // Hover on subnets for tooltip
  wrap.addEventListener('mousemove', (e) => {
    if (drag) { hideTooltip(); return; }
    const subnetGroup = e.target.closest('.subnet-group');
    if (subnetGroup) {
      const subnetId = subnetGroup.getAttribute('data-subnet-id');
      if (subnetId && hoveredSubnet !== subnetId) {
        const nodeGroup = subnetGroup.closest('.node-group');
        const nodeId = nodeGroup?.getAttribute('data-node-id');
        const node = layoutCache?.laid[nodeId];
        const sub = node?.subnets?.find(s => s.id === subnetId);
        if (sub) {
          hoveredSubnet = subnetId;
          showTooltip(sub, e.clientX, e.clientY);
        }
      }
    } else {
      if (hoveredSubnet) { hoveredSubnet = null; hideTooltip(); }
    }
  });

  wrap.addEventListener('mouseleave', () => { hoveredSubnet = null; hideTooltip(); });

  // Toolbar
  $('zoom-in').addEventListener('click', () => zoom(0.15));
  $('zoom-out').addEventListener('click', () => zoom(-0.15));
  $('zoom-reset').addEventListener('click', () => { transform = { x: 0, y: 0, k: 1 }; applyTransform(); });
  $('fit-btn').addEventListener('click', fitToScreen);
  $('panel-close').addEventListener('click', hidePanel);

  // Toolbar file loader
  const tbFile = $('toolbar-file');
  if (tbFile) tbFile.addEventListener('change', (e) => {
    const file = e.target.files?.[0];
    if (file) loadFile(file);
    tbFile.value = '';
  });

  // Keyboard shortcuts
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') hidePanel();
    if (e.key === '0' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); fitToScreen(); }
  });

  window.addEventListener('resize', fitToScreen);
}

// Start
init();
