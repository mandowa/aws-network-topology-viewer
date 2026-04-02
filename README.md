# AWS Network Topology Viewer

Interactive architecture diagram viewer for AWS network infrastructure. Visualizes VPCs, subnets, Transit Gateways, peering connections, and route paths in a structured, enterprise-grade layout.

![License](https://img.shields.io/badge/license-MIT-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Static Site](https://img.shields.io/badge/frontend-vanilla%20JS-yellow)

## Features

- **Structured Architecture Diagram** — VPCs as containers with AZ lanes, color-coded subnets by role (Public Edge, Security, DMZ, Cloud Native, Platform, etc.)
- **Transit Gateway Visualization** — TGW nodes with route tables and route entries displayed inline
- **Route Trace** — Click any subnet, enter a destination IP, and trace the full routing path through VPC route tables → TGW route tables → final destination
- **Clickable Targets** — Click any route target to highlight and pan to the corresponding node on the diagram
- **Hover Tooltips** — Hover over subnets to see route summaries without opening the detail panel
- **Pan / Zoom** — Mouse drag to pan, scroll to zoom, keyboard shortcuts (Esc, Cmd+0)
- **File Upload Mode** — Works on GitHub Pages without server-side data; drag & drop your topology JSON
- **External Peers** — Shows TGW peering and VPC peering connections to external accounts/regions

## Quick Start

### Option A: GitHub Pages (no server needed)

1. Visit the [hosted viewer](https://mandowa.github.io/aws-network-topology-viewer/viewer/)
2. Generate your topology JSON (see below)
3. Drag & drop the file onto the page

### Option B: Local Development

```bash
git clone https://github.com/mandowa/aws-network-topology-viewer.git
cd aws-network-topology-viewer

# Generate data (see below), then:
python3 -m http.server 8080
# Open http://localhost:8080/viewer/
```

## Generating Topology Data

### Prerequisites

- AWS CLI v2 configured with appropriate credentials
- Python 3.10+

### Required IAM Permissions

Attach this read-only policy to your IAM role or user:

```json
{
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
}
```

### Step 1: Export AWS Resources

```bash
P=your-profile
R=ap-northeast-2

aws ec2 describe-vpcs --profile $P --region $R -o json > vpcs.json
aws ec2 describe-subnets --profile $P --region $R -o json > subnets.json
aws ec2 describe-route-tables --profile $P --region $R -o json > route-tables.json
aws ec2 describe-internet-gateways --profile $P --region $R -o json > internet-gateways.json
aws ec2 describe-nat-gateways --profile $P --region $R -o json > nat-gateways.json
aws ec2 describe-transit-gateways --profile $P --region $R -o json > transit-gateways.json
aws ec2 describe-transit-gateway-attachments --profile $P --region $R -o json > tgw-attachments.json
aws ec2 describe-transit-gateway-peering-attachments --profile $P --region $R -o json > tgw-peering-attachments.json
aws ec2 describe-transit-gateway-route-tables --profile $P --region $R -o json > tgw-route-tables.json
aws elbv2 describe-load-balancers --profile $P --region $R -o json > loadbalancers.json
```

### Step 2: Export TGW Routes (Optional)

```bash
bash fetch-tgw-routes.sh --profile $P --region $R
```

This enables the Route Trace feature to follow traffic through TGW route tables.

### Step 3: Generate Topology

```bash
python3 generate_aws_diagram.py
```

Outputs:
- `aws-network-topology.json` — data for the viewer
- `aws-network-architecture.drawio` — draw.io diagram

## Project Structure

```
├── generate_aws_diagram.py    # Topology generator (reads JSON, outputs topology)
├── fetch-tgw-routes.sh        # Helper to export TGW route entries
├── viewer/
│   ├── index.html             # Viewer entry point
│   ├── app.js                 # Diagram rendering, layout, route trace engine
│   └── style.css              # Styles
└── tests/
    └── test_generate_aws_diagram.py
```

## Security

All AWS data files (`*.json`) are excluded from the repository via `.gitignore`. The viewer runs entirely client-side — no data is sent to any server. When using GitHub Pages, topology data stays in your browser.

## License

MIT
