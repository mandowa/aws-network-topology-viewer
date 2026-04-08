# AWS Network Topology Viewer

Interactive architecture diagram viewer for AWS network infrastructure. Visualizes VPCs, subnets, Transit Gateways, peering connections, Route 53 hosted zones, and route paths in a structured, enterprise-grade layout.

![License](https://img.shields.io/badge/license-MIT-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Static Site](https://img.shields.io/badge/frontend-vanilla%20JS-yellow)

## Features

- **Structured Architecture Diagram** — VPCs as containers with AZ lanes, color-coded subnets by role (Public Edge, Security, DMZ, Cloud Native, Platform, etc.)
- **Transit Gateway Visualization** — TGW nodes with route tables and route entries displayed inline
- **Route 53 Hosted Zones** — Shows owned zones with cross-account VPC sharing, shared zones from other accounts, and AWS service zones (VPC endpoints, EKS, EFS)
- **Route Trace** — Click any subnet, enter a destination IP, and trace the full routing path through VPC route tables → TGW route tables → final destination
- **VPC Filter** — Default view shows only the primary VPC; toggle to show all VPCs
- **Accordion Detail Panel** — Collapsible sections for Gateways, Subnets, Load Balancers, Route 53, and Relationships
- **Clickable Targets** — Click any route target to highlight and pan to the corresponding node
- **Hover Tooltips** — Hover over subnets to see route summaries
- **Pan / Zoom** — Mouse drag to pan, scroll to zoom, keyboard shortcuts (Esc, Cmd+0, P to print position)
- **File Upload Mode** — Works on GitHub Pages without server-side data; drag & drop your topology JSON
- **External Peers** — Shows TGW peering and VPC peering connections to external accounts/regions

## Deployment Options

### Option A: S3 Static Hosting + Lambda (Recommended)

Fully automated — Lambda fetches AWS data every 24 hours and updates the viewer on S3. IP whitelist for access control.

```bash
bash deploy/deploy.sh \
  --profile YOUR_PROFILE \
  --allowed-ips "1.2.3.4/32,5.6.7.0/24"
```

For multi-account deployments, use `--stack-name` to avoid S3 bucket name conflicts:

```bash
# Account A (DR)
bash deploy/deploy.sh --profile dft-dr --stack-name nw-viewer-dr --allowed-ips "..."

# Account B (Prod)
bash deploy/deploy.sh --profile dft-prod --stack-name nw-viewer-prod --allowed-ips "..."
```

This creates:
- S3 bucket with static website hosting + IP whitelist
- Lambda function that fetches all AWS network data via boto3
- EventBridge rule triggering Lambda every 24 hours

Manual refresh:
```bash
aws lambda invoke --function-name network-topology-viewer-refresh /tmp/out.json
```

### Option B: GitHub Pages (Manual Upload)

1. Visit the [hosted viewer](https://mandowa.github.io/aws-network-topology-viewer/viewer/)
2. Generate your topology JSON (see below)
3. Drag & drop the file onto the page

### Option C: Local Development

```bash
git clone https://github.com/mandowa/aws-network-topology-viewer.git
cd aws-network-topology-viewer
# Generate data (see below), then:
python3 -m http.server 8080
# Open http://localhost:8080/viewer/
```

## Generating Topology Data (Manual)

### Required IAM Permissions

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
      "elasticloadbalancing:DescribeLoadBalancers",
      "route53:ListHostedZones",
      "route53:GetHostedZone",
      "route53:ListHostedZonesByVPC"
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
aws route53 list-hosted-zones --output json > hosted-zones.json
```

### Step 2: Export TGW Routes (Optional)

```bash
bash fetch-tgw-routes.sh --profile $P --region $R
```

### Step 3: Export Route 53 Details (Optional)

```bash
bash fetch-route53-details.sh --profile $P --region $R
```

### Step 4: Generate Topology

```bash
python3 generate_aws_diagram.py
```

Outputs:
- `aws-network-topology.json` — data for the viewer
- `aws-network-architecture.drawio` — draw.io diagram

## Project Structure

```
├── generate_aws_diagram.py        # Topology generator (reads JSON, outputs topology)
├── fetch-tgw-routes.sh            # Helper to export TGW route entries
├── fetch-route53-details.sh       # Helper to export Route 53 zone details
├── viewer/
│   ├── index.html                 # Viewer entry point
│   ├── app.js                     # Diagram rendering, layout, route trace engine
│   └── style.css                  # Styles
├── deploy/
│   ├── deploy.sh                  # One-command deployment to S3 + Lambda
│   ├── lambda_handler.py          # Lambda: fetches AWS data via boto3, uploads to S3
│   └── template.yaml              # CloudFormation: S3 + Lambda + EventBridge + IP whitelist
└── tests/
    └── test_generate_aws_diagram.py
```

## Security

- All AWS data files (`*.json`) are excluded from the repository via `.gitignore`
- The viewer runs entirely client-side — no data is sent to any server
- S3 deployment uses IP whitelist via bucket policy
- Lambda role has read-only access to network resources

## License

MIT
