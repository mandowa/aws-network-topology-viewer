"""
Lambda handler: Fetches AWS network resources via boto3,
generates topology JSON using the existing generator,
and uploads to S3.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import boto3


def fetch_aws_data(region: str, tmp_dir: Path) -> None:
    """Fetch all AWS network data via boto3 and save as JSON files."""
    ec2 = boto3.client("ec2", region_name=region)
    elbv2 = boto3.client("elbv2", region_name=region)
    route53 = boto3.client("route53")

    datasets = [
        ("vpcs.json", "Vpcs", lambda: ec2.describe_vpcs()),
        ("subnets.json", "Subnets", lambda: ec2.describe_subnets()),
        ("route-tables.json", "RouteTables", lambda: ec2.describe_route_tables()),
        (
            "internet-gateways.json",
            "InternetGateways",
            lambda: ec2.describe_internet_gateways(),
        ),
        ("nat-gateways.json", "NatGateways", lambda: ec2.describe_nat_gateways()),
        (
            "transit-gateways.json",
            "TransitGateways",
            lambda: ec2.describe_transit_gateways(),
        ),
        (
            "tgw-attachments.json",
            "TransitGatewayAttachments",
            lambda: ec2.describe_transit_gateway_attachments(),
        ),
        (
            "tgw-peering-attachments.json",
            "TransitGatewayPeeringAttachments",
            lambda: ec2.describe_transit_gateway_peering_attachments(),
        ),
        (
            "tgw-route-tables.json",
            "TransitGatewayRouteTables",
            lambda: ec2.describe_transit_gateway_route_tables(),
        ),
        (
            "loadbalancers.json",
            "LoadBalancers",
            lambda: elbv2.describe_load_balancers(),
        ),
        (
            "hosted-zones.json",
            "HostedZones",
            lambda: route53.list_hosted_zones(),
        ),
    ]

    for filename, key, fetcher in datasets:
        try:
            resp = fetcher()
            data = {key: resp.get(key, [])}
            (tmp_dir / filename).write_text(
                json.dumps(data, indent=2, default=str), encoding="utf-8"
            )
            print(f"  ✓ {filename}: {len(data[key])} items")
        except Exception as e:
            print(f"  ⚠ {filename}: {e}")
            (tmp_dir / filename).write_text("{}", encoding="utf-8")

    # TGW routes
    fetch_tgw_routes(ec2, tmp_dir)

    # Route 53 zone details + zones by VPC
    fetch_route53_details(route53, ec2, region, tmp_dir)


def fetch_tgw_routes(ec2: object, tmp_dir: Path) -> None:
    """Fetch TGW routes for each route table."""
    routes_by_table = {}
    try:
        rt_data = json.loads((tmp_dir / "tgw-route-tables.json").read_text())
        for rt in rt_data.get("TransitGatewayRouteTables", []):
            rt_id = rt.get("TransitGatewayRouteTableId", "")
            if not rt_id:
                continue
            try:
                resp = ec2.search_transit_gateway_routes(
                    TransitGatewayRouteTableId=rt_id,
                    Filters=[{"Name": "state", "Values": ["active", "blackhole"]}],
                )
                routes_by_table[rt_id] = resp.get("Routes", [])
            except Exception as e:
                print(f"  ⚠ TGW routes for {rt_id}: {e}")
    except Exception as e:
        print(f"  ⚠ TGW routes: {e}")

    (tmp_dir / "tgw-routes.json").write_text(
        json.dumps({"TransitGatewayRoutesByTable": routes_by_table}, indent=2, default=str),
        encoding="utf-8",
    )
    total = sum(len(v) for v in routes_by_table.values())
    print(f"  ✓ tgw-routes.json: {total} routes ({len(routes_by_table)} tables)")


def fetch_route53_details(route53: object, ec2: object, region: str, tmp_dir: Path) -> None:
    """Fetch hosted zone details and zones-by-VPC."""
    # Zone details
    details = []
    try:
        zones_data = json.loads((tmp_dir / "hosted-zones.json").read_text())
        for zone in zones_data.get("HostedZones", []):
            if not zone.get("Config", {}).get("PrivateZone"):
                continue
            zone_id = zone["Id"].replace("/hostedzone/", "")
            try:
                detail = route53.get_hosted_zone(Id=zone_id)
                detail.pop("ResponseMetadata", None)
                details.append(detail)
            except Exception as e:
                print(f"  ⚠ Zone detail {zone_id}: {e}")
    except Exception as e:
        print(f"  ⚠ Zone details: {e}")

    (tmp_dir / "hosted-zone-details.json").write_text(
        json.dumps({"HostedZoneDetails": details}, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"  ✓ hosted-zone-details.json: {len(details)} zones")

    # Zones by VPC
    zones_by_vpc = {}
    try:
        vpcs_data = json.loads((tmp_dir / "vpcs.json").read_text())
        for vpc in vpcs_data.get("Vpcs", []):
            vpc_id = vpc.get("VpcId", "")
            if not vpc_id:
                continue
            try:
                resp = route53.list_hosted_zones_by_vpc(
                    VPCId=vpc_id, VPCRegion=region
                )
                zones_by_vpc[vpc_id] = resp.get("HostedZoneSummaries", [])
            except Exception as e:
                print(f"  ⚠ Zones for {vpc_id}: {e}")
    except Exception as e:
        print(f"  ⚠ Zones by VPC: {e}")

    (tmp_dir / "hosted-zones-by-vpc.json").write_text(
        json.dumps({"HostedZonesByVpc": zones_by_vpc}, indent=2, default=str),
        encoding="utf-8",
    )
    total = sum(len(v) for v in zones_by_vpc.values())
    print(f"  ✓ hosted-zones-by-vpc.json: {total} zones ({len(zones_by_vpc)} VPCs)")


def handler(event, context):
    """Lambda entry point."""
    bucket = os.environ["S3_BUCKET"]
    region = os.environ.get("AWS_DATA_REGION", "ap-northeast-2")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        # 1. Fetch AWS data
        print("=== Fetching AWS data ===")
        fetch_aws_data(region, tmp_dir)

        # 2. Run topology generator
        print("\n=== Generating topology ===")
        # Add generator to path
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from generate_aws_diagram import AWSNetworkDiagramGenerator

        gen = AWSNetworkDiagramGenerator()
        gen.base_path = tmp_dir
        gen.load_all_data()
        topology = gen.build_topology_model()

        # 3. Upload to S3
        print("\n=== Uploading to S3 ===")
        s3 = boto3.client("s3")
        s3.put_object(
            Bucket=bucket,
            Key="data/topology.json",
            Body=json.dumps(topology, indent=2, ensure_ascii=False),
            ContentType="application/json",
        )
        print(f"  ✓ Uploaded data/topology.json to s3://{bucket}")

    return {"statusCode": 200, "body": "Topology updated"}
