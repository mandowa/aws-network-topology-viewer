// App state
let topologyData = null;
let selectedNodeId = null;
let graphTransform = { scale: 1, translateX: 0, translateY: 0 };
let isDragging = false;
let dragStart = { x: 0, y: 0 };

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function safeString(value, fallback = '') {
  return typeof value === 'string' ? value : fallback;
}

function safeArray(value) {
  return Array.isArray(value) ? value : [];
}

function formatValue(value) {
  if (value === null || value === undefined || value === '') {
    return '-';
  }

  if (Array.isArray(value)) {
    return value.length ? value.map((item) => escapeHtml(item)).join(', ') : '-';
  }

  return escapeHtml(value);
}

function renderBadgeList(items, emptyLabel = 'None') {
  if (!items || !items.length) {
    return `<div class="empty-list">${escapeHtml(emptyLabel)}</div>`;
  }

  return `<div class="badge-wrap">${items
    .map((item) => `<span class="badge">${escapeHtml(item)}</span>`)
    .join('')}</div>`;
}

function renderInventoryList(items, renderItem, emptyLabel = 'No items found') {
  if (!items || !items.length) {
    return `<div class="empty-list">${escapeHtml(emptyLabel)}</div>`;
  }

  return `<div class="list-item-stack">${items.map(renderItem).join('')}</div>`;
}

function renderKeyValueRows(rows) {
  return rows
    .map(
      (row) => `
        <div class="detail-row">
          <span class="detail-label">${escapeHtml(row.label)}</span>
          <span class="detail-value">${formatValue(row.value)}</span>
        </div>
      `
    )
    .join('');
}

function renderSubnetSection(vpc) {
  const zones = vpc.availabilityZones || [];

  return `
    <div class="detail-block">
      <h3>Subnets by Availability Zone</h3>
      ${renderInventoryList(
        zones,
        (zone) => `
          <div class="list-item">
            <div class="list-item-title">${escapeHtml(zone.availabilityZone)}</div>
            <div class="list-item-body">${(zone.subnets || []).length} subnet(s)</div>
            <div class="subnet-stack">
              ${(zone.subnets || [])
                .map(
                  (subnet) => `
                    <div class="subnet-card">
                      <div class="subnet-header">
                        <div>
                          <div class="subnet-name">${escapeHtml(subnet.displayName || subnet.name || subnet.id)}</div>
                          <div class="subnet-id">${escapeHtml(subnet.id)}</div>
                        </div>
                        <div class="subnet-flags">
                          <span class="badge ${subnet.isPublic ? 'public' : 'private'}">${subnet.isPublic ? 'public' : 'private'}</span>
                          ${subnet.category ? `<span class="badge">${escapeHtml(subnet.category)}</span>` : ''}
                        </div>
                      </div>
                      ${renderKeyValueRows([
                        { label: 'CIDR', value: subnet.cidr },
                        { label: 'Public IP on Launch', value: subnet.mapPublicIpOnLaunch ? 'enabled' : 'disabled' }
                      ])}
                      <div class="nested-section">
                        <div class="nested-title">Routes</div>
                        ${renderBadgeList(subnet.routeSummary || [], 'No summarized routes')}
                      </div>
                    </div>
                  `
                )
                .join('')}
            </div>
          </div>
        `,
        'No subnet data found'
      )}
    </div>
  `;
}

function renderGatewaySection(title, items, rowsBuilder, emptyLabel) {
  return `
    <div class="detail-block">
      <h3>${escapeHtml(title)}</h3>
      ${renderInventoryList(
        items,
        (item) => `
          <div class="list-item">
            <div class="list-item-title">${escapeHtml(item.name || item.id)}</div>
            <div class="list-item-body mono-text">${escapeHtml(item.id)}</div>
            ${renderKeyValueRows(rowsBuilder(item))}
          </div>
        `,
        emptyLabel
      )}
    </div>
  `;
}

function renderLoadBalancerSection(loadBalancers) {
  return `
    <div class="detail-block">
      <h3>Load Balancers</h3>
      ${renderInventoryList(
        loadBalancers,
        (lb) => `
          <div class="list-item">
            <div class="list-item-title">${escapeHtml(lb.name || lb.id)}</div>
            <div class="list-item-body mono-text">${escapeHtml(lb.id)}</div>
            ${renderKeyValueRows([
              { label: 'Type', value: lb.type },
              { label: 'Scheme', value: lb.scheme },
              { label: 'State', value: lb.state },
              { label: 'Reachability', value: lb.isPublic ? 'public' : 'internal' }
            ])}
            <div class="nested-section">
              <div class="nested-title">Subnets</div>
              ${renderBadgeList(lb.subnetIds || [], 'No subnet mapping')}
            </div>
            <div class="nested-section">
              <div class="nested-title">DNS</div>
              <div class="list-item-body mono-text">${escapeHtml(lb.dnsName || '-')}</div>
            </div>
          </div>
        `,
        'No load balancers in this VPC'
      )}
    </div>
  `;
}

function getNodeRelationships(nodeId) {
  return topologyData.topology.edges
    .filter((edge) => edge.source === nodeId || edge.target === nodeId)
    .map((edge) => {
      const isSource = edge.source === nodeId;
      const otherId = isSource ? edge.target : edge.source;
      const otherNode = topologyData.topology.indexes.nodeById[otherId];

      return {
        edge,
        direction: isSource ? 'outbound' : 'inbound',
        otherNode
      };
    });
}

function renderRelationshipSection(nodeId) {
  const relationships = getNodeRelationships(nodeId);

  if (!relationships.length) {
    return '';
  }

  return `
    <div class="detail-block">
      <h3>Relationships</h3>
      <div class="list-item-stack">
        ${relationships
          .map(({ edge, direction, otherNode }) => `
            <div class="list-item relationship-item">
              <div class="list-item-title">
                <span>${escapeHtml(edge.type)}</span>
                <span class="direction-chip">${direction === 'outbound' ? 'outbound' : 'inbound'}</span>
              </div>
              <div class="list-item-body">${escapeHtml(otherNode?.label || otherNode?.resourceId || 'Unknown node')}</div>
              ${renderKeyValueRows([
                { label: 'Node Type', value: otherNode?.type || '-' },
                { label: 'State', value: edge.state || 'active' },
                { label: 'Edge ID', value: edge.resourceId || edge.id }
              ])}
              ${edge.destinations?.length ? `
                <div class="nested-section">
                  <div class="nested-title">Destinations</div>
                  ${renderBadgeList(edge.destinations, 'No destinations')}
                </div>
              ` : ''}
            </div>
          `)
          .join('')}
      </div>
    </div>
  `;
}

function renderVpcDetails(vpc) {
  const totalSubnets = vpc.subnetCounts ? (vpc.subnetCounts.total || 0) : 0;

  return `
    <div class="detail-block">
      <h3>Network</h3>
      ${renderKeyValueRows([
        { label: 'CIDRs', value: (vpc.cidrBlocks || []).join(', ') },
        { label: 'Subnets', value: totalSubnets },
        { label: 'Public Subnets', value: vpc.subnetCounts?.public || 0 },
        { label: 'Private Subnets', value: vpc.subnetCounts?.private || 0 }
      ])}
    </div>

    <div class="detail-block">
      <h3>Connected Graph Nodes</h3>
      ${renderBadgeList(vpc.connectedGraphNodeIds || [], 'No connected nodes')}
    </div>

    ${vpc.roleSummary ? `
      <div class="detail-block">
        <h3>Role Summary</h3>
        <div class="list-item-body">${escapeHtml(vpc.roleSummary)}</div>
      </div>
    ` : ''}

    ${renderSubnetSection(vpc)}
    ${renderGatewaySection(
      'Internet Gateways',
      vpc.internetGateways || [],
      (gateway) => [
        { label: 'Attached VPCs', value: (gateway.attachedVpcIds || []).length },
        { label: 'Attached IDs', value: (gateway.attachedVpcIds || []).join(', ') }
      ],
      'No internet gateways attached'
    )}
    ${renderGatewaySection(
      'NAT Gateways',
      vpc.natGateways || [],
      (gateway) => [
        { label: 'State', value: gateway.state },
        { label: 'Connectivity', value: gateway.connectivityType },
        { label: 'Subnet', value: gateway.subnetId },
        { label: 'Public IPs', value: (gateway.publicIps || []).join(', ') || '-' },
        { label: 'Private IPs', value: (gateway.privateIps || []).join(', ') || '-' }
      ],
      'No NAT gateways in this VPC'
    )}
    ${renderLoadBalancerSection(vpc.loadBalancers || [])}
  `;
}

function renderTransitGatewayDetails(tgw) {
  return `
    <div class="detail-block">
      <h3>Configuration</h3>
      ${renderKeyValueRows([
        { label: 'State', value: tgw.state },
        { label: 'Owner ID', value: tgw.ownerId },
        { label: 'Attachments', value: tgw.attachmentCount || 0 },
        { label: 'Peerings', value: tgw.peeringCount || 0 }
      ])}
    </div>

    <div class="detail-block">
      <h3>Connected Graph Nodes</h3>
      ${renderBadgeList(tgw.connectedGraphNodeIds || [], 'No connected nodes')}
    </div>

    <div class="detail-block">
      <h3>Attached VPC IDs</h3>
      ${renderBadgeList(tgw.attachedVpcIds || [], 'No attached VPCs')}
    </div>
  `;
}

function renderExternalTransitGatewayDetails(extTgw) {
  return `
    <div class="detail-block">
      <h3>Peer Configuration</h3>
      ${renderKeyValueRows([
        { label: 'State', value: extTgw.State },
        { label: 'Local TGW', value: extTgw.LocalTransitGatewayId },
        { label: 'Remote TGW', value: extTgw.RemoteTransitGatewayId },
        { label: 'Remote Account', value: extTgw.RemoteAccountId },
        { label: 'Remote Region', value: extTgw.RemoteRegion },
        { label: 'Attachment', value: extTgw.TransitGatewayAttachmentId }
      ])}
    </div>

    <div class="detail-block">
      <h3>Connected Graph Nodes</h3>
      ${renderBadgeList(extTgw.connectedGraphNodeIds || [], 'No connected nodes')}
    </div>
  `;
}

function renderExternalVpcDetails(extVpc) {
  return `
    <div class="detail-block">
      <h3>Peering Details</h3>
      ${renderKeyValueRows([
        { label: 'Peering Connection', value: extVpc.VpcPeeringConnectionId },
        { label: 'Source VPC', value: extVpc.SourceVpcName || extVpc.SourceVpcId },
        { label: 'Route Tables', value: (extVpc.RouteTableIds || []).length }
      ])}
    </div>

    <div class="detail-block">
      <h3>Destinations</h3>
      ${renderBadgeList(extVpc.Destinations || [], 'No destinations found')}
    </div>

    <div class="detail-block">
      <h3>Route Table IDs</h3>
      ${renderBadgeList(extVpc.RouteTableIds || [], 'No route tables recorded')}
    </div>

    <div class="detail-block">
      <h3>Connected Graph Nodes</h3>
      ${renderBadgeList(extVpc.connectedGraphNodeIds || [], 'No connected nodes')}
    </div>
  `;
}

// DOM Elements
const elements = {
  metadata: document.getElementById('metadata'),
  summaryCards: document.getElementById('summary-cards'),
  purposeGroups: document.getElementById('purpose-groups'),
  vpcSearch: document.getElementById('vpc-search'),
  vpcList: document.getElementById('vpc-list'),
  graphContainer: document.getElementById('graph-container'),
  detailContent: document.getElementById('detail-content'),
  legend: document.getElementById('graph-legend')
};

async function init() {
  try {
    const response = await fetch('../aws-network-topology.json');
    if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
    topologyData = await response.json();
    
    renderMetadata();
    renderSummary();
    renderPurposeGroups();
    renderVpcList();
    renderGraph();
    setupEventListeners();
    
    // Default selection
    if (topologyData.topology.vpcs.length > 0) {
      selectNode(topologyData.topology.vpcs[0].graphNodeId);
    }
  } catch (error) {
    console.error('Failed to load topology data:', error);
    elements.metadata.textContent = 'Error loading data';
    const message = error instanceof Error ? error.message : 'Unknown error';
    elements.detailContent.innerHTML = `<div class="empty-state"><p class="muted">Failed to load data: ${escapeHtml(message)}</p></div>`;
  }
}

function renderMetadata() {
  const generatedAtSource = topologyData?.metadata?.generatedAt;
  const generatedAt = generatedAtSource ? new Date(generatedAtSource) : null;
  const generatedLabel = generatedAt && !Number.isNaN(generatedAt.getTime())
    ? generatedAt.toLocaleString()
    : 'Unknown';
  const schemaVersion = topologyData?.metadata?.schemaVersion || 'unknown';
  elements.metadata.textContent = `Generated: ${generatedLabel} | v${schemaVersion}`;
}

function renderSummary() {
  const s = topologyData.summary;
  const cards = [
    { label: 'VPCs', value: s.vpcCount },
    { label: 'Subnets', value: s.subnetCount },
    { label: 'Transit Gateways', value: s.transitGatewayCount },
    { label: 'TGW Peers', value: s.transitGatewayPeeringCount },
    { label: 'IGWs', value: s.internetGatewayCount },
    { label: 'NAT Gateways', value: s.natGatewayCount },
    { label: 'Load Balancers', value: s.loadBalancerCount }
  ];
  
  elements.summaryCards.innerHTML = cards.map(c => `
    <div class="card">
      <div class="card-value">${c.value || 0}</div>
      <div class="card-label">${c.label}</div>
    </div>
  `).join('');
}

function renderPurposeGroups() {
  if (!topologyData.summary.purposeGroups) return;
  elements.purposeGroups.innerHTML = topologyData.summary.purposeGroups.map(pg => `
    <span class="tag">${escapeHtml(pg.name)} (${pg.subnetCount})</span>
  `).join('');
}

function renderVpcList() {
  const searchTerm = elements.vpcSearch.value.toLowerCase();
  const vpcs = topologyData.topology.vpcs.filter(vpc => {
    const vpcName = safeString(vpc.name, 'Unnamed VPC');
    const vpcId = safeString(vpc.id, 'unknown-vpc');

    return vpcName.toLowerCase().includes(searchTerm) || vpcId.toLowerCase().includes(searchTerm);
  }
  );
  
  elements.vpcList.innerHTML = vpcs.map(vpc => `
    <li class="vpc-item ${selectedNodeId === vpc.graphNodeId ? 'active' : ''}" data-node-id="${escapeHtml(safeString(vpc.graphNodeId, ''))}">
      <div class="vpc-name">${escapeHtml(safeString(vpc.name, 'Unnamed VPC'))}</div>
      <div class="vpc-id">${escapeHtml(safeString(vpc.id, 'unknown-vpc'))}</div>
    </li>
  `).join('');
}

function renderGraph() {
  const width = elements.graphContainer.clientWidth || 600;
  const height = elements.graphContainer.clientHeight || 400;
  const nodes = JSON.parse(JSON.stringify(topologyData.topology.nodes));
  const edges = topologyData.topology.edges;
  
  // Legend
  elements.legend.innerHTML = `
    <div class="legend-item"><div class="legend-dot vpc"></div><span>VPC</span></div>
    <div class="legend-item"><div class="legend-dot tgw"></div><span>TGW</span></div>
    <div class="legend-item"><div class="legend-dot external-tgw"></div><span>Ext TGW</span></div>
    <div class="legend-item"><div class="legend-dot external-vpc"></div><span>Ext VPC</span></div>
  `;

  // Force Layout
  nodes.forEach(n => {
    n.x = width / 2 + (Math.random() - 0.5) * 100;
    n.y = height / 2 + (Math.random() - 0.5) * 100;
    n.vx = 0; n.vy = 0;
  });

  const k = Math.sqrt((width * height) / (nodes.length || 1));
  for (let i = 0; i < 300; i++) {
    for (let j = 0; j < nodes.length; j++) {
      for (let l = j + 1; l < nodes.length; l++) {
        let dx = nodes[j].x - nodes[l].x;
        let dy = nodes[j].y - nodes[l].y;
        let dsq = dx*dx + dy*dy || 0.01;
        let force = 10000 / dsq;
        let f = Math.min(force, 50); // cap force
        nodes[j].vx += f * dx; nodes[j].vy += f * dy;
        nodes[l].vx -= f * dx; nodes[l].vy -= f * dy;
      }
    }
    edges.forEach(e => {
      let source = nodes.find(n => n.id === e.source);
      let target = nodes.find(n => n.id === e.target);
      if (!source || !target) return;
      let dx = target.x - source.x;
      let dy = target.y - source.y;
      let dist = Math.sqrt(dx*dx + dy*dy) || 0.1;
      let force = 0.05 * (dist - k);
      source.vx += force * dx / dist; source.vy += force * dy / dist;
      target.vx -= force * dx / dist; target.vy -= force * dy / dist;
    });
    nodes.forEach(n => {
      n.vx += (width/2 - n.x) * 0.01;
      n.vy += (height/2 - n.y) * 0.01;
      n.vx *= 0.8; n.vy *= 0.8;
      n.x += n.vx; n.y += n.vy;
      n.x = Math.max(20, Math.min(width - 20, n.x));
      n.y = Math.max(20, Math.min(height - 20, n.y));
    });
  }

  const transform = `translate(${graphTransform.translateX}, ${graphTransform.translateY}) scale(${graphTransform.scale})`;
  let svg = `<svg width="100%" height="100%" id="graph-svg">`;
  svg += `<g id="graph-content" transform="${transform}">`;
  
  // Edges
  edges.forEach(e => {
    const s = nodes.find(n => n.id === e.source);
    const t = nodes.find(n => n.id === e.target);
    if (!s || !t) return;
    svg += `<line class="edge" id="edge-${safeString(e.id, '').replace(/[^a-zA-Z0-9-]/g, '-')}" data-source="${escapeHtml(safeString(s.id, ''))}" data-target="${escapeHtml(safeString(t.id, ''))}" x1="${s.x}" y1="${s.y}" x2="${t.x}" y2="${t.y}"><title>${escapeHtml(e.label || e.type)}</title></line>`;
  });

  // Nodes
  nodes.forEach(n => {
    let color = 'var(--color-node-vpc)';
    if (n.type === 'transit-gateway') color = 'var(--color-node-tgw)';
    else if (n.type === 'external-transit-gateway-peer') color = '#06b6d4';
    else if (n.type === 'external-vpc-peer') color = '#f97316';
    
    svg += `
      <g class="node" id="node-${safeString(n.id, '').replace(/[^a-zA-Z0-9-]/g, '-')}" data-node-id="${escapeHtml(safeString(n.id, ''))}" transform="translate(${n.x},${n.y})">
        <circle r="12" fill="${color}" stroke="var(--color-border)"><title>${escapeHtml(n.label || n.id)}</title></circle>
        <text class="node-label" y="24">${escapeHtml(n.label || n.id)}</text>
      </g>
    `;
  });
  
  svg += `</g></svg>`;
  elements.graphContainer.innerHTML = svg;
  
  // Restore selection highlighting
  if (selectedNodeId) {
    highlightGraph(selectedNodeId);
  }
}

function selectNode(nodeId) {
  selectedNodeId = nodeId;
  renderVpcList(); // update active class
  highlightGraph(nodeId);
  renderDetails(nodeId);
}

function highlightGraph(nodeId) {
  const adjacent = topologyData.topology.indexes.adjacentNodeIdsByNodeId[nodeId] || [];
  const relatedNodes = new Set([nodeId, ...adjacent]);
  
  document.querySelectorAll('.node').forEach(el => {
    const id = el.getAttribute('data-node-id');
    if (!nodeId) {
      el.classList.remove('dimmed', 'active');
    } else if (id === nodeId) {
      el.classList.add('active');
      el.classList.remove('dimmed');
    } else if (relatedNodes.has(id)) {
      el.classList.remove('dimmed', 'active');
    } else {
      el.classList.add('dimmed');
      el.classList.remove('active');
    }
  });

  document.querySelectorAll('.edge').forEach(el => {
    if (!nodeId) {
      el.classList.remove('dimmed', 'active');
      return;
    }
    const s = el.getAttribute('data-source');
    const t = el.getAttribute('data-target');
    if (s === nodeId || t === nodeId) {
      el.classList.add('active');
      el.classList.remove('dimmed');
    } else {
      el.classList.add('dimmed');
      el.classList.remove('active');
    }
  });
}

function renderDetails(nodeId) {
  if (!nodeId) {
    elements.detailContent.innerHTML = `
      <div class="empty-state">
        <p>Select a VPC or graph node to view its configuration and relationships.</p>
      </div>`;
    return;
  }

  const node = topologyData.topology.nodes.find(n => n.id === nodeId);
  if (!node) {
    elements.detailContent.innerHTML = `
      <div class="empty-state">
        <p class="muted">The selected node could not be found in the current topology data.</p>
      </div>`;
    return;
  }

  let html = `<div class="detail-block">
    <div class="detail-title">${escapeHtml(node.label || node.id)}</div>
    <div class="detail-subtitle">${escapeHtml(node.type)} | ${escapeHtml(node.id)}</div>
  </div>`;

  // Render specific details based on type
  if (node.type === 'vpc') {
    const vpc = topologyData.topology.vpcs.find(v => v.graphNodeId === nodeId);
    if (vpc) {
      html += renderVpcDetails(vpc);
    }
  } else if (node.type === 'transit-gateway') {
    const tgw = topologyData.topology.transitGateways.find(t => t.graphNodeId === nodeId);
    if (tgw) {
      html += renderTransitGatewayDetails(tgw);
    }
  } else if (node.type === 'external-transit-gateway-peer') {
    const extTgw = topologyData.topology.externalTransitGatewayPeers.find(t => t.graphNodeId === nodeId);
    if (extTgw) {
      html += renderExternalTransitGatewayDetails(extTgw);
    }
  } else if (node.type === 'external-vpc-peer') {
    const extVpc = topologyData.topology.externalVpcPeerings.find(v => v.graphNodeId === nodeId);
    if (extVpc) {
      html += renderExternalVpcDetails(extVpc);
    }
  }

  html += renderRelationshipSection(nodeId);

  elements.detailContent.innerHTML = html;
}

function zoomGraph(delta, centerX, centerY) {
  const newScale = Math.max(0.1, Math.min(5, graphTransform.scale + delta));
  if (newScale === graphTransform.scale) return;

  const scaleRatio = newScale / graphTransform.scale;
  graphTransform.translateX = centerX - (centerX - graphTransform.translateX) * scaleRatio;
  graphTransform.translateY = centerY - (centerY - graphTransform.translateY) * scaleRatio;
  graphTransform.scale = newScale;

  const content = document.getElementById('graph-content');
  if (content) {
    content.setAttribute('transform', `translate(${graphTransform.translateX}, ${graphTransform.translateY}) scale(${graphTransform.scale})`);
  }
}

function resetGraphView() {
  graphTransform = { scale: 1, translateX: 0, translateY: 0 };
  renderGraph();
}

function setupEventListeners() {
  elements.vpcSearch.addEventListener('input', () => {
    renderVpcList();
  });

  elements.vpcList.addEventListener('click', (e) => {
    const item = e.target.closest('.vpc-item');
    if (item) {
      const nodeId = item.getAttribute('data-node-id');
      selectNode(nodeId);
    }
  });

  elements.graphContainer.addEventListener('click', (e) => {
    if (isDragging) return;
    const nodeEl = e.target.closest('.node');
    if (nodeEl) {
      const nodeId = nodeEl.getAttribute('data-node-id');
      selectNode(nodeId);
    } else {
      selectNode(null);
    }
  });

  elements.graphContainer.addEventListener('wheel', (e) => {
    e.preventDefault();
    const rect = elements.graphContainer.getBoundingClientRect();
    const centerX = e.clientX - rect.left;
    const centerY = e.clientY - rect.top;
    const delta = e.deltaY > 0 ? -0.1 : 0.1;
    zoomGraph(delta, centerX, centerY);
  }, { passive: false });

  elements.graphContainer.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;
    isDragging = false;
    dragStart = { x: e.clientX - graphTransform.translateX, y: e.clientY - graphTransform.translateY };
    elements.graphContainer.style.cursor = 'grabbing';
  });

  document.addEventListener('mousemove', (e) => {
    if (dragStart.x === 0 && dragStart.y === 0) return;
    const dx = e.clientX - dragStart.x;
    const dy = e.clientY - dragStart.y;
    if (Math.abs(dx - graphTransform.translateX) > 3 || Math.abs(dy - graphTransform.translateY) > 3) {
      isDragging = true;
    }
    graphTransform.translateX = dx;
    graphTransform.translateY = dy;
    const content = document.getElementById('graph-content');
    if (content) {
      content.setAttribute('transform', `translate(${graphTransform.translateX}, ${graphTransform.translateY}) scale(${graphTransform.scale})`);
    }
  });

  document.addEventListener('mouseup', () => {
    dragStart = { x: 0, y: 0 };
    elements.graphContainer.style.cursor = 'default';
    setTimeout(() => { isDragging = false; }, 50);
  });

  document.getElementById('zoom-in')?.addEventListener('click', () => {
    const rect = elements.graphContainer.getBoundingClientRect();
    zoomGraph(0.25, rect.width / 2, rect.height / 2);
  });

  document.getElementById('zoom-out')?.addEventListener('click', () => {
    const rect = elements.graphContainer.getBoundingClientRect();
    zoomGraph(-0.25, rect.width / 2, rect.height / 2);
  });

  document.getElementById('zoom-reset')?.addEventListener('click', resetGraphView);
  
  window.addEventListener('resize', () => {
    renderGraph();
  });
}

// Start app
init();
