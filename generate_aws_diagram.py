from __future__ import annotations

import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

JsonObject = dict[str, object]


class AWSNetworkDiagramGenerator:
    def __init__(self) -> None:
        self.base_path: Path = Path(__file__).resolve().parent
        self.vpcs: list[JsonObject] = []
        self.subnets: list[JsonObject] = []
        self.route_tables: list[JsonObject] = []
        self.tgws: list[JsonObject] = []
        self.tgw_attachments: list[JsonObject] = []
        self.tgw_peering_attachments: list[JsonObject] = []
        self.tgw_route_tables: list[JsonObject] = []
        self.internet_gateways: list[JsonObject] = []
        self.nat_gateways: list[JsonObject] = []
        self.load_balancers: list[JsonObject] = []

    def load_json(self, filename: str) -> JsonObject:
        try:
            with (self.base_path / filename).open("r", encoding="utf-8") as file_handle:
                payload: object = json.load(file_handle)
                return payload if isinstance(payload, dict) else {}
        except FileNotFoundError:
            print(f"⚠️  找不到 {filename}，跳過")
            return {}
        except json.JSONDecodeError as error:
            print(f"❌ {filename} 格式錯誤: {error}")
            return {}

    def _as_object(self, value: object) -> JsonObject:
        return value if isinstance(value, dict) else {}

    def _as_object_list(self, value: object) -> list[JsonObject]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    def _as_str(self, value: object, default: str = "") -> str:
        return value if isinstance(value, str) else default

    def _as_bool(self, value: object, default: bool = False) -> bool:
        return value if isinstance(value, bool) else default

    def load_all_data(self) -> None:
        print("📊 正在載入 AWS 網路資源...")
        print("--------------------------------------------------")

        dataset_map = [
            ("vpcs.json", "Vpcs", "vpcs", "VPC"),
            ("subnets.json", "Subnets", "subnets", "Subnet"),
            ("route-tables.json", "RouteTables", "route_tables", "Route Table"),
            (
                "internet-gateways.json",
                "InternetGateways",
                "internet_gateways",
                "Internet Gateway",
            ),
            ("nat-gateways.json", "NatGateways", "nat_gateways", "NAT Gateway"),
            ("transit-gateways.json", "TransitGateways", "tgws", "Transit Gateway"),
            (
                "tgw-attachments.json",
                "TransitGatewayAttachments",
                "tgw_attachments",
                "TGW Attachment",
            ),
            (
                "tgw-peering-attachments.json",
                "TransitGatewayPeeringAttachments",
                "tgw_peering_attachments",
                "TGW Peering Attachment",
            ),
            (
                "tgw-route-tables.json",
                "TransitGatewayRouteTables",
                "tgw_route_tables",
                "TGW Route Table",
            ),
            ("loadbalancers.json", "LoadBalancers", "load_balancers", "Load Balancer"),
        ]

        for filename, key, attribute, label in dataset_map:
            payload = self.load_json(filename)
            resources = self._as_object_list(payload.get(key, []))
            setattr(self, attribute, resources)
            print(f"  ✓ {label}: {len(resources)} 個")

        print("--------------------------------------------------")

    def _get_name_from_tags(self, tags: list[JsonObject] | None, default: str) -> str:
        if not tags:
            return default

        for tag in tags:
            if self._as_str(tag.get("Key")) == "Name":
                return self._as_str(tag.get("Value"), default)

        return default

    def _tag_lookup(self, tags: list[JsonObject] | None) -> dict[str, str]:
        if not tags:
            return {}
        return {
            self._as_str(tag.get("Key")): self._as_str(tag.get("Value")) for tag in tags
        }

    def _is_public_subnet(self, subnet_id: str) -> bool:
        for route_table in self._get_effective_route_tables_for_subnet(subnet_id):
            for route in self._as_object_list(route_table.get("Routes", [])):
                gateway_id = self._as_str(route.get("GatewayId"))
                if gateway_id.startswith("igw-"):
                    return True

        return False

    def _get_subnet_by_id(self, subnet_id: str) -> JsonObject | None:
        for subnet in self.subnets:
            if subnet.get("SubnetId") == subnet_id:
                return subnet
        return None

    def _get_effective_route_tables_for_subnet(
        self, subnet_id: str
    ) -> list[JsonObject]:
        subnet = self._get_subnet_by_id(subnet_id)
        if subnet is None:
            return []

        subnet_vpc_id = self._as_str(subnet.get("VpcId"))
        explicit_matches: list[JsonObject] = []
        main_matches: list[JsonObject] = []

        for route_table in self.route_tables:
            if self._as_str(route_table.get("VpcId")) != subnet_vpc_id:
                continue

            for association in self._as_object_list(
                route_table.get("Associations", [])
            ):
                if self._as_str(association.get("SubnetId")) == subnet_id:
                    explicit_matches.append(route_table)
                    break
                if self._as_bool(association.get("Main")):
                    main_matches.append(route_table)
                    break

        if explicit_matches:
            return explicit_matches
        return main_matches

    def _get_subnet_route_info(self, subnet_id: str) -> list[str]:
        routes: list[str] = []

        for route_table in self._get_effective_route_tables_for_subnet(subnet_id):
            for route in self._as_object_list(route_table.get("Routes", [])):
                destination = self._as_str(
                    route.get(
                        "DestinationCidrBlock",
                        self._as_str(route.get("DestinationPrefixListId"), "Unknown"),
                    ),
                    "Unknown",
                )
                target = self._as_str(
                    route.get("GatewayId")
                    or route.get("NatGatewayId")
                    or route.get("TransitGatewayId")
                    or route.get("VpcPeeringConnectionId")
                    or route.get("DestinationPrefixListId")
                    or route.get("InstanceId")
                    or "Local"
                )
                if target != "Local" and target != "local":
                    routes.append(f"{destination} → {target}")

        deduped: list[str] = []
        seen: set[str] = set()
        for item in routes:
            if item in seen:
                continue
            seen.add(item)
            deduped.append(item)
        return deduped

    def _get_tgw_owner_id(self, tgw: JsonObject) -> str:
        options = [tgw.get("OwnerId"), tgw.get("TransitGatewayOwnerId")]
        for value in options:
            if value:
                return value
        return "Unknown"

    def _find_peering_for_tgw(self, tgw_id: str) -> list[JsonObject]:
        matched: list[JsonObject] = []
        for peering in self.tgw_peering_attachments:
            accepter_info = peering.get("AccepterTgwInfo", {})
            requester_info = peering.get("RequesterTgwInfo", {})
            if (
                accepter_info.get("TransitGatewayId") == tgw_id
                or requester_info.get("TransitGatewayId") == tgw_id
            ):
                matched.append(peering)
        return matched

    def _build_peering_label(self, peering: JsonObject, local_tgw_id: str) -> str:
        requester_info = peering.get("RequesterTgwInfo", {})
        accepter_info = peering.get("AccepterTgwInfo", {})
        attachment_id = peering.get("TransitGatewayAttachmentId", "Unknown")
        state = peering.get("State", "Unknown")

        if requester_info.get("TransitGatewayId") == local_tgw_id:
            local_info = requester_info
            remote_info = accepter_info
        else:
            local_info = accepter_info
            remote_info = requester_info

        local_account = local_info.get("OwnerId", "Unknown")
        remote_account = remote_info.get("OwnerId", "Unknown")
        remote_region = remote_info.get("Region", "Unknown")
        remote_tgw_id = remote_info.get("TransitGatewayId", "Unknown")
        external_text = (
            "External Account" if remote_account != local_account else "Same Account"
        )

        return (
            f"TGW Peering\n{attachment_id}\n"
            f"State: {state}\n"
            f"{external_text}: {remote_account}\n"
            f"Remote TGW: {remote_tgw_id}\n"
            f"Remote Region: {remote_region}"
        )

    def _local_tgw_ids(self) -> set[str]:
        return {
            self._as_str(tgw.get("TransitGatewayId"))
            for tgw in self.tgws
            if self._as_str(tgw.get("TransitGatewayId"))
        }

    def _collect_external_tgw_peers(self) -> list[JsonObject]:
        local_tgw_ids = self._local_tgw_ids()
        peers: list[JsonObject] = []
        seen_remote_keys: set[tuple[str, str, str]] = set()

        for peering in self.tgw_peering_attachments:
            requester_info = self._as_object(peering.get("RequesterTgwInfo"))
            accepter_info = self._as_object(peering.get("AccepterTgwInfo"))
            requester_id = self._as_str(requester_info.get("TransitGatewayId"))
            accepter_id = self._as_str(accepter_info.get("TransitGatewayId"))

            if requester_id in local_tgw_ids and accepter_id not in local_tgw_ids:
                local_tgw_id = requester_id
                remote_info = accepter_info
            elif accepter_id in local_tgw_ids and requester_id not in local_tgw_ids:
                local_tgw_id = accepter_id
                remote_info = requester_info
            else:
                continue

            remote_tgw_id = self._as_str(remote_info.get("TransitGatewayId"), "Unknown")
            remote_account = self._as_str(remote_info.get("OwnerId"), "Unknown")
            remote_region = self._as_str(remote_info.get("Region"), "Unknown")
            remote_key = (local_tgw_id, remote_tgw_id, remote_account)
            if remote_key in seen_remote_keys:
                continue
            seen_remote_keys.add(remote_key)
            peers.append(
                {
                    "LocalTransitGatewayId": local_tgw_id,
                    "RemoteTransitGatewayId": remote_tgw_id,
                    "RemoteAccountId": remote_account,
                    "RemoteRegion": remote_region,
                    "TransitGatewayAttachmentId": self._as_str(
                        peering.get("TransitGatewayAttachmentId"), "Unknown"
                    ),
                    "State": self._as_str(peering.get("State"), "Unknown"),
                    "Name": self._get_name_from_tags(
                        self._as_object_list(peering.get("Tags")), remote_tgw_id
                    ),
                }
            )

        peers.sort(
            key=lambda peer: (
                self._as_str(peer.get("LocalTransitGatewayId")),
                self._as_str(peer.get("RemoteAccountId")),
                self._as_str(peer.get("Name")),
            )
        )
        return peers

    def _collect_vpc_peering_connections(self) -> list[JsonObject]:
        local_vpc_ids = {
            self._as_str(vpc.get("VpcId"))
            for vpc in self.vpcs
            if self._as_str(vpc.get("VpcId"))
        }
        vpc_lookup = {
            self._as_str(vpc.get("VpcId")): vpc
            for vpc in self.vpcs
            if self._as_str(vpc.get("VpcId"))
        }
        peering_map: dict[str, JsonObject] = {}

        for route_table in self.route_tables:
            source_vpc_id = self._as_str(route_table.get("VpcId"))
            if source_vpc_id not in local_vpc_ids:
                continue

            source_vpc = vpc_lookup.get(source_vpc_id, {})
            source_vpc_name = self._get_name_from_tags(
                self._as_object_list(source_vpc.get("Tags")), source_vpc_id
            )

            for route in self._as_object_list(route_table.get("Routes", [])):
                peering_id = self._as_str(route.get("VpcPeeringConnectionId"))
                if not peering_id:
                    continue

                connection = peering_map.setdefault(
                    peering_id,
                    {
                        "VpcPeeringConnectionId": peering_id,
                        "SourceVpcId": source_vpc_id,
                        "SourceVpcName": source_vpc_name,
                        "Destinations": [],
                        "RouteTableIds": [],
                    },
                )
                destination = self._as_str(route.get("DestinationCidrBlock"), "Unknown")
                if destination not in connection["Destinations"]:
                    connection["Destinations"].append(destination)
                route_table_id = self._as_str(
                    route_table.get("RouteTableId"), "Unknown"
                )
                if route_table_id not in connection["RouteTableIds"]:
                    connection["RouteTableIds"].append(route_table_id)

        connections = list(peering_map.values())
        for connection in connections:
            destinations = connection.get("Destinations", [])
            if isinstance(destinations, list):
                destinations.sort()
            route_table_ids = connection.get("RouteTableIds", [])
            if isinstance(route_table_ids, list):
                route_table_ids.sort()

        connections.sort(
            key=lambda connection: (
                self._as_str(connection.get("SourceVpcName")),
                self._as_str(connection.get("VpcPeeringConnectionId")),
            )
        )
        return connections

    def _external_tgw_peer_label(self, peer: JsonObject) -> str:
        return (
            "External TGW Peer\n"
            f"{self._as_str(peer.get('Name'), 'Unknown Peer')}\n"
            f"Remote TGW: {self._as_str(peer.get('RemoteTransitGatewayId'), 'Unknown')}\n"
            f"Account: {self._as_str(peer.get('RemoteAccountId'), 'Unknown')}\n"
            f"Region: {self._as_str(peer.get('RemoteRegion'), 'Unknown')}"
        )

    def _vpc_peering_label(self, connection: JsonObject) -> str:
        destination_values = connection.get("Destinations", [])
        if isinstance(destination_values, list):
            destinations_text = ", ".join(
                value for value in destination_values if isinstance(value, str)
            )
        else:
            destinations_text = "Unknown"

        route_table_values = connection.get("RouteTableIds", [])
        if isinstance(route_table_values, list):
            route_table_count = len(route_table_values)
        else:
            route_table_count = 0

        return (
            "External VPC Peer\n"
            f"{self._as_str(connection.get('VpcPeeringConnectionId'), 'Unknown')}\n"
            f"Destinations: {destinations_text or 'Unknown'}\n"
            f"Source: {self._as_str(connection.get('SourceVpcName'), 'Unknown')}\n"
            f"Route Tables: {route_table_count}"
        )

    def _layout_cards(
        self,
        count: int,
        card_width: int,
        card_height: int,
        container_width: int,
        *,
        left_padding: int = 30,
        right_padding: int = 30,
        top_padding: int = 0,
        horizontal_gap: int = 20,
        vertical_gap: int = 16,
    ) -> tuple[list[tuple[int, int]], int]:
        if count <= 0:
            return [], top_padding

        usable_width = max(1, container_width - left_padding - right_padding)
        cards_per_row = max(
            1, (usable_width + horizontal_gap) // (card_width + horizontal_gap)
        )
        positions: list[tuple[int, int]] = []
        rows = (count + cards_per_row - 1) // cards_per_row

        for index in range(count):
            row = index // cards_per_row
            column = index % cards_per_row
            x = left_padding + column * (card_width + horizontal_gap)
            y = top_padding + row * (card_height + vertical_gap)
            positions.append((x, y))

        total_height = (
            top_padding + rows * card_height + max(rows - 1, 0) * vertical_gap
        )
        return positions, total_height

    def _group_vpc_subnets(self, vpc_id: str) -> dict[str, list[JsonObject]]:
        groups: dict[str, list[JsonObject]] = defaultdict(list)
        for subnet in self.subnets:
            if subnet.get("VpcId") != vpc_id:
                continue
            groups[subnet.get("AvailabilityZone", "unknown-az")].append(subnet)

        for availability_zone in groups:
            groups[availability_zone].sort(
                key=lambda subnet: self._get_name_from_tags(
                    subnet.get("Tags"), subnet["SubnetId"]
                )
            )

        return dict(sorted(groups.items()))

    def _role_tokens(self, subnet: JsonObject) -> str:
        tags = self._tag_lookup(subnet.get("Tags"))
        alias = tags.get("smt:net:alias", "")
        name = self._get_name_from_tags(
            subnet.get("Tags"), subnet.get("SubnetId", "Subnet")
        )
        return f"{name} {alias}".lower()

    def _matches_any_pattern(self, text: str, patterns: tuple[str, ...]) -> bool:
        return any(re.search(pattern, text) for pattern in patterns)

    def _is_public_facing_subnet(self, subnet: JsonObject) -> bool:
        tokens = self._role_tokens(subnet)
        return (
            self._is_public_subnet(subnet.get("SubnetId", ""))
            or subnet.get("MapPublicIpOnLaunch", False)
            or self._matches_any_pattern(tokens, (r"public\b",))
        )

    def _classify_subnet(self, subnet: JsonObject) -> tuple[str, str]:
        tags = self._tag_lookup(subnet.get("Tags"))
        alias = tags.get("smt:net:alias", "")
        name = self._get_name_from_tags(
            subnet.get("Tags"), subnet.get("SubnetId", "Subnet")
        )
        combined = self._role_tokens(subnet)
        is_public = self._is_public_facing_subnet(subnet)

        # Public exposure takes precedence because the overview emphasizes the
        # network boundary before deeper workload roles.
        if is_public or "public" in combined:
            return "Public Edge", alias or name
        if "dmz" in combined:
            return "DMZ", alias or name
        if self._matches_any_pattern(combined, (r"security", r"inspection", r"\bf5\b")):
            return "Security", alias or name
        if self._matches_any_pattern(
            combined, (r"cloudnative", r"\beks\b", r"kubernetes")
        ):
            return "Cloud Native", alias or name
        if self._matches_any_pattern(
            combined,
            (r"trusted", r"private", r"\bapp\b", r"\bapi\b"),
        ):
            return "Private App", alias or name
        if self._matches_any_pattern(
            combined,
            (r"infra", r"\bmgmt\b", r"management", r"shared"),
        ):
            return "Platform", alias or name
        if "tgw" in combined:
            return "Transit", alias or name
        return "Application", alias or name

    def _category_style(self, category: str) -> str:
        style_map = {
            "Public Edge": "rounded=1;whiteSpace=wrap;html=1;fillColor=#ffe6cc;strokeColor=#d79b00;fontSize=11;fontStyle=1;",
            "DMZ": "rounded=1;whiteSpace=wrap;html=1;fillColor=#f8cecc;strokeColor=#b85450;fontSize=11;fontStyle=1;",
            "Security": "rounded=1;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;fontSize=11;fontStyle=1;",
            "Cloud Native": "rounded=1;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;fontSize=11;",
            "Private App": "rounded=1;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;fontSize=11;",
            "Platform": "rounded=1;whiteSpace=wrap;html=1;fillColor=#e1d5e7;strokeColor=#9673a6;fontSize=11;",
            "Transit": "rounded=1;whiteSpace=wrap;html=1;fillColor=#e8d9ff;strokeColor=#7c3aed;fontSize=11;",
            "Application": "rounded=1;whiteSpace=wrap;html=1;fillColor=#f5f5f5;strokeColor=#666666;fontSize=11;",
        }
        return style_map.get(category, style_map["Application"])

    def _category_sort_key(self, item: tuple[str, int]) -> tuple[int, int, str]:
        order = {
            "Public Edge": 0,
            "DMZ": 1,
            "Security": 2,
            "Cloud Native": 3,
            "Private App": 4,
            "Platform": 5,
            "Transit": 6,
            "Application": 7,
        }
        category, count = item
        return (-count, order.get(category, 99), category)

    def _format_count(
        self, count: int, singular: str, plural: str | None = None
    ) -> str:
        plural_label = plural or f"{singular}s"
        label = singular if count == 1 else plural_label
        return f"{count} {label}"

    def _vpc_cidr_blocks(self, vpc: JsonObject) -> list[str]:
        cidr_blocks: list[str] = []
        seen: set[str] = set()

        primary_cidr = self._as_str(vpc.get("CidrBlock"))
        if primary_cidr:
            cidr_blocks.append(primary_cidr)
            seen.add(primary_cidr)

        for association in self._as_object_list(vpc.get("CidrBlockAssociationSet", [])):
            cidr_block = self._as_str(association.get("CidrBlock"))
            if not cidr_block or cidr_block in seen:
                continue
            cidr_blocks.append(cidr_block)
            seen.add(cidr_block)

        return cidr_blocks

    def _format_vpc_cidrs(self, vpc: JsonObject) -> str:
        cidr_blocks = self._vpc_cidr_blocks(vpc)
        return ", ".join(cidr_blocks) if cidr_blocks else "Unknown CIDR"

    def _summarize_purpose_groups(self) -> list[str]:
        counts: Counter[str] = Counter()
        for subnet in self.subnets:
            category, _ = self._classify_subnet(subnet)
            counts[category] += 1

        lines = ["Purpose Groups"]
        for category, count in sorted(counts.items(), key=self._category_sort_key):
            lines.append(f"• {category}: {self._format_count(count, 'subnet')}")
        return lines

    def _summarize_subnet_roles(self, vpc_id: str) -> str:
        counts: Counter[str] = Counter(
            self._classify_subnet(subnet)[0]
            for subnet in self.subnets
            if subnet.get("VpcId") == vpc_id
        )
        if not counts:
            return "Roles: none"

        top_roles = sorted(counts.items(), key=self._category_sort_key)[:3]
        role_summary = ", ".join(f"{category} {count}" for category, count in top_roles)
        return f"Roles: {role_summary}"

    def _summarize_vpc(self, vpc: JsonObject) -> list[str]:
        vpc_id = vpc["VpcId"]
        vpc_name = self._get_name_from_tags(vpc.get("Tags"), vpc_id)
        vpc_subnets = [
            subnet for subnet in self.subnets if subnet.get("VpcId") == vpc_id
        ]
        public_count = sum(
            1 for subnet in vpc_subnets if self._is_public_facing_subnet(subnet)
        )
        private_count = len(vpc_subnets) - public_count
        az_count = len({subnet.get("AvailabilityZone") for subnet in vpc_subnets})
        balancer_count = sum(
            1 for lb in self.load_balancers if lb.get("VpcId") == vpc_id
        )
        nat_count = sum(1 for nat in self.nat_gateways if nat.get("VpcId") == vpc_id)

        return [
            f"{vpc_name} · {self._format_vpc_cidrs(vpc)}",
            f"Subnets: {len(vpc_subnets)} ({public_count} public / {private_count} private)",
            f"Availability Zones: {az_count}",
            f"Load Balancers: {balancer_count}",
            f"NAT Gateways: {nat_count}",
        ]

    def _summarize_connectivity(self) -> list[str]:
        public_lbs = [
            lb for lb in self.load_balancers if lb.get("Scheme") == "internet-facing"
        ]
        internal_lbs = [
            lb for lb in self.load_balancers if lb.get("Scheme") != "internet-facing"
        ]
        return [
            "External Connectivity",
            f"Internet Gateways: {len(self.internet_gateways)}",
            f"NAT Gateways: {len(self.nat_gateways)}",
            f"TGW Peerings: {len(self.tgw_peering_attachments)}",
            f"Internal Load Balancers: {len(internal_lbs)}",
            f"Public Load Balancers: {len(public_lbs)}",
        ]

    def _vpc_tgws(self, vpc_id: str) -> list[JsonObject]:
        attached_tgw_ids = {
            attachment.get("TransitGatewayId")
            for attachment in self.tgw_attachments
            if attachment.get("ResourceType") == "vpc"
            and attachment.get("ResourceId") == vpc_id
        }
        return [
            tgw for tgw in self.tgws if tgw.get("TransitGatewayId") in attached_tgw_ids
        ]

    def _load_balancer_samples(self, vpc_id: str, limit: int = 4) -> list[str]:
        matches = [lb for lb in self.load_balancers if lb.get("VpcId") == vpc_id]
        names = sorted(lb.get("LoadBalancerName", "unknown-lb") for lb in matches)
        sample = names[:limit]
        if len(names) > limit:
            sample.append(f"… +{len(names) - limit} more")
        return sample

    def _estimate_az_lane_height(self, subnet_count: int) -> int:
        visible_subnets = min(subnet_count, 4)
        top_padding = 38
        card_height = 64
        card_gap = 8
        bottom_padding = 16
        lane_height = top_padding + bottom_padding

        if visible_subnets:
            lane_height += visible_subnets * card_height
            lane_height += max(visible_subnets - 1, 0) * card_gap

        if subnet_count > 4:
            lane_height += card_gap + 42

        return lane_height

    def _estimate_footer_height(self, service_lines: list[str]) -> int:
        footer_lines = ["Services"] + (
            service_lines if service_lines else ["No load balancers mapped"]
        )
        return self._estimate_text_block_height(
            footer_lines,
            chars_per_line=32,
            base_padding=20,
            line_height=16,
        )

    def _estimate_text_block_height(
        self,
        lines: list[str],
        *,
        chars_per_line: int,
        base_padding: int,
        line_height: int,
    ) -> int:
        wrapped_line_count = 0
        for line in lines:
            wrapped_line_count += max(1, (len(line) // max(chars_per_line, 1)) + 1)
        return base_padding + wrapped_line_count * line_height

    def _compute_az_layout(
        self,
        vpc_width: int,
        az_count: int,
        *,
        outer_padding: int = 20,
        lane_gap: int = 14,
    ) -> tuple[int, int]:
        inner_width = max(1, vpc_width - (outer_padding * 2))
        if az_count <= 0:
            return inner_width, lane_gap

        if az_count == 1:
            return inner_width, 0

        preferred_min_lane_width = 60
        max_gap_without_shrinking = (
            inner_width - (az_count * preferred_min_lane_width)
        ) // (az_count - 1)

        if max_gap_without_shrinking >= 0:
            effective_gap = min(lane_gap, max_gap_without_shrinking)
            lane_width = max(
                preferred_min_lane_width,
                (inner_width - (effective_gap * (az_count - 1))) // az_count,
            )
            return lane_width, effective_gap

        compressed_gap = min(lane_gap, 6)
        lane_width = max(
            1,
            (inner_width - (compressed_gap * (az_count - 1))) // az_count,
        )
        return lane_width, compressed_gap

    def _az_child_width(self, az_width: int, horizontal_padding: int = 28) -> int:
        return max(40, az_width - horizontal_padding)

    def _attachment_label(self, attachment: JsonObject) -> str:
        attachment_id = attachment.get("TransitGatewayAttachmentId", "Attachment")
        name = self._get_name_from_tags(attachment.get("Tags"), attachment_id)
        resource_type = attachment.get("ResourceType", "unknown")
        resource_id = attachment.get("ResourceId", "unknown-resource")
        state = attachment.get("State", "unknown")
        return f"{name}\n{resource_type}: {resource_id}\nState: {state}"

    def _availability_zone_subnet_payload(self, subnet: JsonObject) -> JsonObject:
        subnet_id = self._as_str(subnet.get("SubnetId"), "unknown-subnet")
        category, display_name = self._classify_subnet(subnet)
        tags = self._tag_lookup(self._as_object_list(subnet.get("Tags")))
        routes = self._get_subnet_route_info(subnet_id)

        return {
            "id": subnet_id,
            "name": self._get_name_from_tags(
                self._as_object_list(subnet.get("Tags")), subnet_id
            ),
            "displayName": display_name,
            "alias": tags.get("smt:net:alias", ""),
            "category": category,
            "cidr": self._as_str(subnet.get("CidrBlock"), "Unknown CIDR"),
            "availabilityZone": self._as_str(
                subnet.get("AvailabilityZone"), "unknown-az"
            ),
            "isPublic": self._is_public_facing_subnet(subnet),
            "mapPublicIpOnLaunch": self._as_bool(
                subnet.get("MapPublicIpOnLaunch"), False
            ),
            "routeSummary": routes,
        }

    def _load_balancer_payload(self, load_balancer: JsonObject) -> JsonObject:
        attached_subnets = [
            self._as_str(availability_zone.get("SubnetId"))
            for availability_zone in self._as_object_list(
                load_balancer.get("AvailabilityZones", [])
            )
            if self._as_str(availability_zone.get("SubnetId"))
        ]
        return {
            "id": self._as_str(load_balancer.get("LoadBalancerArn"))
            or self._as_str(load_balancer.get("LoadBalancerName"), "unknown-lb"),
            "name": self._as_str(load_balancer.get("LoadBalancerName"), "unknown-lb"),
            "scheme": self._as_str(load_balancer.get("Scheme"), "unknown"),
            "type": self._as_str(load_balancer.get("Type"), "unknown"),
            "dnsName": self._as_str(load_balancer.get("DNSName")),
            "state": self._as_str(
                self._as_object(load_balancer.get("State")).get("Code"), "unknown"
            ),
            "subnetIds": attached_subnets,
            "isPublic": self._as_str(load_balancer.get("Scheme")) == "internet-facing",
        }

    def _internet_gateway_payload(self, internet_gateway: JsonObject) -> JsonObject:
        gateway_id = self._as_str(
            internet_gateway.get("InternetGatewayId"), "unknown-igw"
        )
        return {
            "id": gateway_id,
            "name": self._get_name_from_tags(
                self._as_object_list(internet_gateway.get("Tags")), gateway_id
            ),
            "attachedVpcIds": [
                self._as_str(attachment.get("VpcId"))
                for attachment in self._as_object_list(
                    internet_gateway.get("Attachments", [])
                )
                if self._as_str(attachment.get("VpcId"))
            ],
        }

    def _nat_gateway_payload(self, nat_gateway: JsonObject) -> JsonObject:
        nat_gateway_id = self._as_str(nat_gateway.get("NatGatewayId"), "unknown-nat")
        addresses = self._as_object_list(nat_gateway.get("NatGatewayAddresses", []))
        public_ips = [
            self._as_str(address.get("PublicIp"))
            for address in addresses
            if self._as_str(address.get("PublicIp"))
        ]
        private_ips = [
            self._as_str(address.get("PrivateIp"))
            for address in addresses
            if self._as_str(address.get("PrivateIp"))
        ]
        return {
            "id": nat_gateway_id,
            "name": self._get_name_from_tags(
                self._as_object_list(nat_gateway.get("Tags")), nat_gateway_id
            ),
            "vpcId": self._as_str(nat_gateway.get("VpcId")),
            "subnetId": self._as_str(nat_gateway.get("SubnetId")),
            "state": self._as_str(nat_gateway.get("State"), "unknown"),
            "connectivityType": self._as_str(
                nat_gateway.get("ConnectivityType"), "unknown"
            ),
            "publicIps": public_ips,
            "privateIps": private_ips,
        }

    def _transit_gateway_payload(self, tgw: JsonObject) -> JsonObject:
        transit_gateway_id = self._as_str(tgw.get("TransitGatewayId"), "unknown-tgw")
        vpc_attachments = [
            attachment
            for attachment in self.tgw_attachments
            if self._as_str(attachment.get("TransitGatewayId")) == transit_gateway_id
            and self._as_str(attachment.get("ResourceType")) == "vpc"
        ]
        peerings = self._find_peering_for_tgw(transit_gateway_id)
        return {
            "id": transit_gateway_id,
            "name": self._get_name_from_tags(
                self._as_object_list(tgw.get("Tags")), transit_gateway_id
            ),
            "ownerId": self._get_tgw_owner_id(tgw),
            "state": self._as_str(tgw.get("State"), "unknown"),
            "attachedVpcIds": [
                self._as_str(attachment.get("ResourceId"))
                for attachment in vpc_attachments
                if self._as_str(attachment.get("ResourceId"))
            ],
            "attachmentCount": len(vpc_attachments),
            "peeringCount": len(peerings),
        }

    def _graph_node_type_contracts(self) -> list[JsonObject]:
        return [
            {
                "type": "transit-gateway",
                "resourceKind": "aws-resource",
                "isSynthetic": False,
                "description": "Canonical AWS Transit Gateway node.",
            },
            {
                "type": "vpc",
                "resourceKind": "aws-resource",
                "isSynthetic": False,
                "description": "Canonical AWS VPC node.",
            },
            {
                "type": "external-transit-gateway-peer",
                "resourceKind": "external-placeholder",
                "isSynthetic": True,
                "description": "Synthetic node representing a remote TGW peer outside the local snapshots.",
            },
            {
                "type": "external-vpc-peer",
                "resourceKind": "external-placeholder",
                "isSynthetic": True,
                "description": "Synthetic node representing external VPC connectivity inferred from local route tables.",
            },
        ]

    def _graph_edge_type_contracts(self) -> list[JsonObject]:
        return [
            {
                "type": "tgw-attachment",
                "relationship": "attachment",
                "isSynthetic": False,
                "isInferred": False,
                "description": "Canonical TGW attachment edge between a Transit Gateway and VPC.",
            },
            {
                "type": "tgw-peering",
                "relationship": "peering",
                "isSynthetic": False,
                "isInferred": False,
                "description": "TGW peering edge from a local Transit Gateway to a synthetic remote peer node.",
            },
            {
                "type": "vpc-peering",
                "relationship": "reachable-peering",
                "isSynthetic": True,
                "isInferred": True,
                "description": "Inferred connectivity edge from a VPC to a synthetic external peer node using route table evidence.",
            },
        ]

    def _graph_model_contract(self) -> JsonObject:
        return {
            "hierarchySource": "topology.vpcs",
            "graphSource": "topology.nodes and topology.edges",
            "indexSource": "topology.indexes",
            "nodeTypes": self._graph_node_type_contracts(),
            "edgeTypes": self._graph_edge_type_contracts(),
        }

    def _graph_node_id(self, node_type: str, resource_id: str) -> str:
        return f"{node_type}:{resource_id}"

    def _sort_unique_strings(self, values: list[str]) -> list[str]:
        return sorted({value for value in values if value})

    def _build_graph_indexes(
        self, topology_nodes: list[JsonObject], topology_edges: list[JsonObject]
    ) -> JsonObject:
        node_by_id: dict[str, JsonObject] = {}
        edge_by_id: dict[str, JsonObject] = {}
        node_ids_by_type: defaultdict[str, list[str]] = defaultdict(list)
        edge_ids_by_type: defaultdict[str, list[str]] = defaultdict(list)
        outgoing_edge_ids_by_node_id: defaultdict[str, list[str]] = defaultdict(list)
        incoming_edge_ids_by_node_id: defaultdict[str, list[str]] = defaultdict(list)
        adjacent_node_ids_by_node_id: defaultdict[str, list[str]] = defaultdict(list)

        for node in topology_nodes:
            node_id = self._as_str(node.get("id"))
            node_type = self._as_str(node.get("type"))
            if not node_id:
                continue
            node_by_id[node_id] = node
            if node_type:
                node_ids_by_type[node_type].append(node_id)

        for edge in topology_edges:
            edge_id = self._as_str(edge.get("id"))
            edge_type = self._as_str(edge.get("type"))
            source_id = self._as_str(edge.get("source"))
            target_id = self._as_str(edge.get("target"))

            if edge_id:
                edge_by_id[edge_id] = edge
                if edge_type:
                    edge_ids_by_type[edge_type].append(edge_id)

            if source_id and edge_id:
                outgoing_edge_ids_by_node_id[source_id].append(edge_id)
            if target_id and edge_id:
                incoming_edge_ids_by_node_id[target_id].append(edge_id)

            if source_id and target_id:
                adjacent_node_ids_by_node_id[source_id].append(target_id)
                adjacent_node_ids_by_node_id[target_id].append(source_id)

        return {
            "nodeById": node_by_id,
            "edgeById": edge_by_id,
            "nodeIdsByType": {
                node_type: self._sort_unique_strings(node_ids)
                for node_type, node_ids in sorted(node_ids_by_type.items())
            },
            "edgeIdsByType": {
                edge_type: self._sort_unique_strings(edge_ids)
                for edge_type, edge_ids in sorted(edge_ids_by_type.items())
            },
            "outgoingEdgeIdsByNodeId": {
                node_id: self._sort_unique_strings(edge_ids)
                for node_id, edge_ids in sorted(outgoing_edge_ids_by_node_id.items())
            },
            "incomingEdgeIdsByNodeId": {
                node_id: self._sort_unique_strings(edge_ids)
                for node_id, edge_ids in sorted(incoming_edge_ids_by_node_id.items())
            },
            "adjacentNodeIdsByNodeId": {
                node_id: self._sort_unique_strings(node_ids)
                for node_id, node_ids in sorted(adjacent_node_ids_by_node_id.items())
            },
        }

    def build_topology_model(self) -> JsonObject:
        external_tgw_peers = self._collect_external_tgw_peers()
        vpc_peering_connections = self._collect_vpc_peering_connections()

        purpose_group_counts: Counter[str] = Counter()
        for subnet in self.subnets:
            category, _ = self._classify_subnet(subnet)
            purpose_group_counts[category] += 1

        topology_nodes: list[JsonObject] = []
        topology_edges: list[JsonObject] = []

        for tgw in self.tgws:
            tgw_id = self._as_str(tgw.get("TransitGatewayId"))
            topology_nodes.append(
                {
                    "id": self._graph_node_id("tgw", tgw_id),
                    "type": "transit-gateway",
                    "resourceId": tgw_id,
                    "resourceKind": "aws-resource",
                    "isSynthetic": False,
                    "label": self._get_name_from_tags(
                        self._as_object_list(tgw.get("Tags")), tgw_id
                    ),
                }
            )

        for vpc in self.vpcs:
            vpc_id = self._as_str(vpc.get("VpcId"))
            topology_nodes.append(
                {
                    "id": self._graph_node_id("vpc", vpc_id),
                    "type": "vpc",
                    "resourceId": vpc_id,
                    "resourceKind": "aws-resource",
                    "isSynthetic": False,
                    "label": self._get_name_from_tags(
                        self._as_object_list(vpc.get("Tags")), vpc_id
                    ),
                }
            )

        for peer in external_tgw_peers:
            peer_id = self._graph_node_id(
                "external-tgw-peer",
                (
                    f"{self._as_str(peer.get('LocalTransitGatewayId'))}:"
                    f"{self._as_str(peer.get('RemoteTransitGatewayId'))}:"
                    f"{self._as_str(peer.get('RemoteAccountId'))}"
                ),
            )
            topology_nodes.append(
                {
                    "id": peer_id,
                    "type": "external-transit-gateway-peer",
                    "resourceId": self._as_str(peer.get("RemoteTransitGatewayId")),
                    "resourceKind": "external-placeholder",
                    "isSynthetic": True,
                    "isInferred": False,
                    "source": "tgw-peering-attachments.json",
                    "label": self._as_str(peer.get("Name"), "Unknown Peer"),
                }
            )

        for connection in vpc_peering_connections:
            peering_id = self._as_str(
                connection.get("VpcPeeringConnectionId"), "unknown"
            )
            topology_nodes.append(
                {
                    "id": self._graph_node_id("external-vpc-peer", peering_id),
                    "type": "external-vpc-peer",
                    "resourceId": peering_id,
                    "resourceKind": "external-placeholder",
                    "isSynthetic": True,
                    "isInferred": True,
                    "source": "route-tables.json",
                    "label": peering_id,
                }
            )

        for attachment in self.tgw_attachments:
            if self._as_str(attachment.get("ResourceType")) != "vpc":
                continue
            transit_gateway_id = self._as_str(attachment.get("TransitGatewayId"))
            vpc_id = self._as_str(attachment.get("ResourceId"))
            if not transit_gateway_id or not vpc_id:
                continue
            topology_edges.append(
                {
                    "id": self._as_str(
                        attachment.get("TransitGatewayAttachmentId"),
                        f"tgw-attachment:{transit_gateway_id}:{vpc_id}",
                    ),
                    "type": "tgw-attachment",
                    "source": self._graph_node_id("tgw", transit_gateway_id),
                    "target": self._graph_node_id("vpc", vpc_id),
                    "relationship": "attachment",
                    "resourceKind": "aws-resource",
                    "resourceId": self._as_str(
                        attachment.get("TransitGatewayAttachmentId"),
                        f"tgw-attachment:{transit_gateway_id}:{vpc_id}",
                    ),
                    "isSynthetic": False,
                    "isInferred": False,
                    "state": self._as_str(attachment.get("State"), "unknown"),
                    "displayLabel": self._attachment_label(attachment),
                    "label": self._attachment_label(attachment),
                }
            )

        for peer in external_tgw_peers:
            local_tgw_id = self._as_str(peer.get("LocalTransitGatewayId"))
            remote_tgw_id = self._as_str(peer.get("RemoteTransitGatewayId"))
            remote_account_id = self._as_str(peer.get("RemoteAccountId"))
            if not local_tgw_id:
                continue
            topology_edges.append(
                {
                    "id": self._as_str(
                        peer.get("TransitGatewayAttachmentId"),
                        f"tgw-peering:{local_tgw_id}:{remote_tgw_id}:{remote_account_id}",
                    ),
                    "type": "tgw-peering",
                    "source": self._graph_node_id("tgw", local_tgw_id),
                    "target": self._graph_node_id(
                        "external-tgw-peer",
                        f"{local_tgw_id}:{remote_tgw_id}:{remote_account_id}",
                    ),
                    "relationship": "peering",
                    "resourceKind": "aws-resource",
                    "resourceId": self._as_str(
                        peer.get("TransitGatewayAttachmentId"),
                        f"tgw-peering:{local_tgw_id}:{remote_tgw_id}:{remote_account_id}",
                    ),
                    "isSynthetic": False,
                    "isInferred": False,
                    "state": self._as_str(peer.get("State"), "unknown"),
                }
            )

        for connection in vpc_peering_connections:
            source_vpc_id = self._as_str(connection.get("SourceVpcId"))
            peering_id = self._as_str(connection.get("VpcPeeringConnectionId"))
            if not source_vpc_id or not peering_id:
                continue
            topology_edges.append(
                {
                    "id": f"vpc-peering:{peering_id}",
                    "type": "vpc-peering",
                    "source": self._graph_node_id("vpc", source_vpc_id),
                    "target": self._graph_node_id("external-vpc-peer", peering_id),
                    "relationship": "reachable-peering",
                    "resourceKind": "external-placeholder",
                    "resourceId": peering_id,
                    "isSynthetic": True,
                    "isInferred": True,
                    "inferenceSource": "route-tables.json",
                    "routeTableIds": connection.get("RouteTableIds", []),
                    "destinations": connection.get("Destinations", []),
                    "displayLabel": self._vpc_peering_label(connection),
                    "label": self._vpc_peering_label(connection),
                }
            )

        vpc_payloads: list[JsonObject] = []
        for vpc in self.vpcs:
            vpc_id = self._as_str(vpc.get("VpcId"), "unknown-vpc")
            vpc_name = self._get_name_from_tags(
                self._as_object_list(vpc.get("Tags")), vpc_id
            )
            vpc_subnets = [
                subnet
                for subnet in self.subnets
                if self._as_str(subnet.get("VpcId")) == vpc_id
            ]
            az_groups = self._group_vpc_subnets(vpc_id)
            public_count = sum(
                1 for subnet in vpc_subnets if self._is_public_facing_subnet(subnet)
            )
            private_count = len(vpc_subnets) - public_count
            availability_zone_payloads: list[JsonObject] = []
            for availability_zone, subnets in az_groups.items():
                availability_zone_payloads.append(
                    {
                        "availabilityZone": availability_zone,
                        "subnets": [
                            self._availability_zone_subnet_payload(subnet)
                            for subnet in subnets
                        ],
                    }
                )

            internet_gateways = [
                self._internet_gateway_payload(internet_gateway)
                for internet_gateway in self.internet_gateways
                if vpc_id
                in [
                    self._as_str(attachment.get("VpcId"))
                    for attachment in self._as_object_list(
                        internet_gateway.get("Attachments", [])
                    )
                ]
            ]
            nat_gateways = [
                self._nat_gateway_payload(nat_gateway)
                for nat_gateway in self.nat_gateways
                if self._as_str(nat_gateway.get("VpcId")) == vpc_id
            ]
            load_balancers = [
                self._load_balancer_payload(load_balancer)
                for load_balancer in self.load_balancers
                if self._as_str(load_balancer.get("VpcId")) == vpc_id
            ]
            attached_transit_gateways = [
                self._transit_gateway_payload(tgw) for tgw in self._vpc_tgws(vpc_id)
            ]

            vpc_payloads.append(
                {
                    "id": vpc_id,
                    "graphNodeId": self._graph_node_id("vpc", vpc_id),
                    "name": vpc_name,
                    "cidrBlocks": self._vpc_cidr_blocks(vpc),
                    "roleSummary": self._summarize_subnet_roles(vpc_id),
                    "subnetCounts": {
                        "total": len(vpc_subnets),
                        "public": public_count,
                        "private": private_count,
                    },
                    "availabilityZones": availability_zone_payloads,
                    "internetGateways": internet_gateways,
                    "natGateways": nat_gateways,
                    "loadBalancers": load_balancers,
                    "transitGateways": attached_transit_gateways,
                    "connectedGraphNodeIds": self._sort_unique_strings(
                        [
                            self._graph_node_id(
                                "tgw", self._as_str(tgw.get("TransitGatewayId"))
                            )
                            for tgw in self._vpc_tgws(vpc_id)
                            if self._as_str(tgw.get("TransitGatewayId"))
                        ]
                        + [
                            self._graph_node_id(
                                "external-vpc-peer",
                                self._as_str(connection.get("VpcPeeringConnectionId")),
                            )
                            for connection in vpc_peering_connections
                            if self._as_str(connection.get("SourceVpcId")) == vpc_id
                            and self._as_str(connection.get("VpcPeeringConnectionId"))
                        ]
                    ),
                }
            )

        topology_indexes = self._build_graph_indexes(topology_nodes, topology_edges)
        adjacent_node_ids_by_node_id = topology_indexes.get(
            "adjacentNodeIdsByNodeId", {}
        )
        if not isinstance(adjacent_node_ids_by_node_id, dict):
            adjacent_node_ids_by_node_id = {}

        transit_gateway_payloads = []
        for tgw in self.tgws:
            transit_gateway_id = self._as_str(
                tgw.get("TransitGatewayId"), "unknown-tgw"
            )
            payload = self._transit_gateway_payload(tgw)
            payload["graphNodeId"] = self._graph_node_id("tgw", transit_gateway_id)
            payload["connectedGraphNodeIds"] = self._sort_unique_strings(
                adjacent_node_ids_by_node_id.get(payload["graphNodeId"], [])
                if isinstance(payload["graphNodeId"], str)
                else []
            )
            transit_gateway_payloads.append(payload)

        external_transit_gateway_peer_payloads = []
        for peer in external_tgw_peers:
            local_tgw_id = self._as_str(peer.get("LocalTransitGatewayId"))
            remote_tgw_id = self._as_str(peer.get("RemoteTransitGatewayId"))
            remote_account_id = self._as_str(peer.get("RemoteAccountId"))
            peer_payload = dict(peer)
            peer_payload["graphNodeId"] = self._graph_node_id(
                "external-tgw-peer",
                f"{local_tgw_id}:{remote_tgw_id}:{remote_account_id}",
            )
            peer_payload["connectedGraphNodeIds"] = self._sort_unique_strings(
                adjacent_node_ids_by_node_id.get(peer_payload["graphNodeId"], [])
                if isinstance(peer_payload["graphNodeId"], str)
                else []
            )
            external_transit_gateway_peer_payloads.append(peer_payload)

        external_vpc_peering_payloads = []
        for connection in vpc_peering_connections:
            peering_id = self._as_str(connection.get("VpcPeeringConnectionId"))
            connection_payload = dict(connection)
            connection_payload["graphNodeId"] = self._graph_node_id(
                "external-vpc-peer", peering_id
            )
            connection_payload["connectedGraphNodeIds"] = self._sort_unique_strings(
                adjacent_node_ids_by_node_id.get(connection_payload["graphNodeId"], [])
                if isinstance(connection_payload["graphNodeId"], str)
                else []
            )
            external_vpc_peering_payloads.append(connection_payload)

        return {
            "metadata": {
                "schemaVersion": "1.1",
                "generatedAt": datetime.now().isoformat(),
                "sourceFiles": [
                    "vpcs.json",
                    "subnets.json",
                    "route-tables.json",
                    "internet-gateways.json",
                    "nat-gateways.json",
                    "transit-gateways.json",
                    "tgw-attachments.json",
                    "tgw-peering-attachments.json",
                    "loadbalancers.json",
                ],
                "graphModel": self._graph_model_contract(),
            },
            "summary": {
                "vpcCount": len(self.vpcs),
                "subnetCount": len(self.subnets),
                "transitGatewayCount": len(self.tgws),
                "transitGatewayPeeringCount": len(self.tgw_peering_attachments),
                "externalTransitGatewayPeerCount": len(external_tgw_peers),
                "externalVpcPeeringCount": len(vpc_peering_connections),
                "internetGatewayCount": len(self.internet_gateways),
                "natGatewayCount": len(self.nat_gateways),
                "loadBalancerCount": len(self.load_balancers),
                "publicLoadBalancerCount": sum(
                    1
                    for load_balancer in self.load_balancers
                    if self._as_str(load_balancer.get("Scheme")) == "internet-facing"
                ),
                "internalLoadBalancerCount": sum(
                    1
                    for load_balancer in self.load_balancers
                    if self._as_str(load_balancer.get("Scheme")) != "internet-facing"
                ),
                "purposeGroups": [
                    {
                        "name": category,
                        "subnetCount": count,
                    }
                    for category, count in sorted(
                        purpose_group_counts.items(), key=self._category_sort_key
                    )
                ],
            },
            "topology": {
                "vpcs": vpc_payloads,
                "transitGateways": transit_gateway_payloads,
                "externalTransitGatewayPeers": external_transit_gateway_peer_payloads,
                "externalVpcPeerings": external_vpc_peering_payloads,
                "nodes": topology_nodes,
                "edges": topology_edges,
                "indexes": topology_indexes,
            },
        }

    def _add_cell(
        self,
        root_cell: ET.Element,
        cell_id: int,
        value: str,
        style: str,
        *,
        parent: str = "1",
        vertex: bool = True,
        edge: bool = False,
        source: str | None = None,
        target: str | None = None,
        x: int = 0,
        y: int = 0,
        width: int = 0,
        height: int = 0,
    ) -> ET.Element:
        attributes = {
            "id": str(cell_id),
            "value": value,
            "style": style,
            "parent": parent,
        }
        if vertex:
            attributes["vertex"] = "1"
        if edge:
            attributes["edge"] = "1"
        if source is not None:
            attributes["source"] = source
        if target is not None:
            attributes["target"] = target

        cell = ET.SubElement(root_cell, "mxCell", attributes)
        geometry_attributes = {"as": "geometry"}
        if edge:
            geometry_attributes["relative"] = "1"
        else:
            geometry_attributes.update(
                {"x": str(x), "y": str(y), "width": str(width), "height": str(height)}
            )
        ET.SubElement(cell, "mxGeometry", geometry_attributes)
        return cell

    def generate_drawio_xml(self) -> str:
        summary_width = 600
        vpc_width = 700
        vpc_gap = 40
        tgw_width = 300
        tgw_gap = 60
        topology_x = 40
        summary_gap = 40
        external_summary_card_height = 70
        external_summary_card_gap = 25
        external_detail_card_width = 250
        external_detail_card_height = 94
        external_detail_card_gap = 20

        external_tgw_peers = self._collect_external_tgw_peers()
        vpc_peering_connections = self._collect_vpc_peering_connections()

        vpc_group_map = {
            vpc["VpcId"]: self._group_vpc_subnets(vpc["VpcId"]) for vpc in self.vpcs
        }
        max_az_lane_height = max(
            (
                self._estimate_az_lane_height(len(subnets))
                for az_groups in vpc_group_map.values()
                for subnets in az_groups.values()
            ),
            default=220,
        )
        max_footer_height = max(
            (
                self._estimate_footer_height(self._load_balancer_samples(vpc["VpcId"]))
                for vpc in self.vpcs
            ),
            default=64,
        )
        vpc_height = 68 + max_az_lane_height + 12 + max_footer_height + 18

        vpc_content_width = (
            max(1, len(self.vpcs)) * vpc_width + max(len(self.vpcs) - 1, 0) * vpc_gap
        )
        tgw_content_width = (
            max(1, len(self.tgws)) * tgw_width
            + max(len(self.tgws) - 1, 0) * tgw_gap
            + 80
        )
        external_summary_width = (
            220 + 220 + 240 + 240 + (external_summary_card_gap * 3) + 60
        )
        external_detail_count = len(external_tgw_peers) + len(vpc_peering_connections)
        external_detail_content_width = (
            max(1, external_detail_count) * external_detail_card_width
            + max(external_detail_count - 1, 0) * external_detail_card_gap
            + 60
        )
        topology_width = max(
            1460,
            vpc_content_width + 40,
            tgw_content_width,
            external_summary_width,
            external_detail_content_width,
        )
        summary_x = topology_x + topology_width + summary_gap
        page_width = summary_x + summary_width + 40

        root = ET.Element(
            "mxfile",
            {
                "host": "app.diagrams.net",
                "modified": datetime.now().isoformat(),
                "agent": "AWS Network Diagram Generator v1.0",
                "etag": "aws-network",
                "version": "21.0.0",
                "type": "device",
            },
        )
        diagram = ET.SubElement(
            root,
            "diagram",
            {"name": "AWS Network Architecture", "id": "aws-network-diagram-1"},
        )
        graph = ET.SubElement(
            diagram,
            "mxGraphModel",
            {
                "dx": "1800",
                "dy": "1100",
                "grid": "1",
                "gridSize": "10",
                "guides": "1",
                "tooltips": "1",
                "connect": "1",
                "arrows": "1",
                "fold": "1",
                "page": "1",
                "pageScale": "1",
                "pageWidth": str(page_width),
                "pageHeight": "1600",
                "math": "0",
                "shadow": "0",
            },
        )
        root_cell = ET.SubElement(graph, "root")
        ET.SubElement(root_cell, "mxCell", {"id": "0"})
        ET.SubElement(root_cell, "mxCell", {"id": "1", "parent": "0"})

        cell_id = 2

        self._add_cell(
            root_cell,
            cell_id,
            "AWS Network Topology Overview",
            "rounded=1;whiteSpace=wrap;html=1;fillColor=#1f2937;strokeColor=#111827;fontColor=#ffffff;fontStyle=1;fontSize=22;spacing=12;",
            x=40,
            y=20,
            width=topology_width,
            height=60,
        )
        cell_id += 1

        self._add_cell(
            root_cell,
            cell_id,
            "Cleaner layered topology focused on traffic flow, VPC roles, and cross-network connectivity.",
            "rounded=1;whiteSpace=wrap;html=1;fillColor=#f3f4f6;strokeColor=#d1d5db;fontSize=12;spacing=10;",
            x=40,
            y=90,
            width=topology_width,
            height=40,
        )
        cell_id += 1

        summary_panel_id = str(cell_id)
        self._add_cell(
            root_cell,
            cell_id,
            "Topology Summary",
            "swimlane;rounded=1;whiteSpace=wrap;html=1;fillColor=#fff7e6;strokeColor=#d6b656;fontStyle=1;fontSize=18;startSize=34;",
            x=summary_x,
            y=20,
            width=summary_width,
            height=1240,
        )
        cell_id += 1

        current_summary_y = 50
        for lines in [
            self._summarize_connectivity(),
            self._summarize_purpose_groups(),
        ] + [self._summarize_vpc(vpc) for vpc in self.vpcs]:
            height = max(
                96,
                self._estimate_text_block_height(
                    lines,
                    chars_per_line=46,
                    base_padding=24,
                    line_height=18,
                ),
            )
            self._add_cell(
                root_cell,
                cell_id,
                "\n".join(lines),
                "rounded=1;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#d1d5db;align=left;verticalAlign=top;fontSize=12;spacing=10;",
                parent=summary_panel_id,
                x=20,
                y=current_summary_y,
                width=summary_width - 40,
                height=height,
            )
            current_summary_y += height + 14
            cell_id += 1

        summary_panel_height = max(340, current_summary_y + 18)

        topology_y = 160
        layer_gap = 26
        external_detail_rows = 1 if external_detail_count else 0
        if external_detail_count > 0:
            external_card_positions, external_cards_total_height = self._layout_cards(
                external_detail_count,
                external_detail_card_width,
                external_detail_card_height,
                topology_width,
                left_padding=30,
                right_padding=30,
                top_padding=140,
                horizontal_gap=external_detail_card_gap,
                vertical_gap=16,
            )
        else:
            external_card_positions = []
            external_cards_total_height = 140

        external_layer_height = max(
            170,
            external_cards_total_height + (24 if external_detail_rows else 0),
        )

        external_layer_id = str(cell_id)
        self._add_cell(
            root_cell,
            cell_id,
            "External Connectivity",
            "swimlane;rounded=1;whiteSpace=wrap;html=1;fillColor=#e8f1ff;strokeColor=#6c8ebf;fontStyle=1;fontSize=16;startSize=30;",
            x=topology_x,
            y=topology_y,
            width=topology_width,
            height=external_layer_height,
        )
        cell_id += 1

        x_cursor = 30
        for label, width in [
            (f"Internet Gateways\n{len(self.internet_gateways)} attached", 220),
            (f"NAT Egress\n{len(self.nat_gateways)} managed exits", 220),
            (
                f"Internal Load Balancers\n{len([lb for lb in self.load_balancers if lb.get('Scheme') != 'internet-facing'])}",
                240,
            ),
            (
                f"TGW Peerings\n{len(self.tgw_peering_attachments)} cross-network links",
                240,
            ),
        ]:
            self._add_cell(
                root_cell,
                cell_id,
                label,
                "rounded=1;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#8fb1e3;fontSize=13;fontStyle=1;",
                parent=external_layer_id,
                x=x_cursor,
                y=55,
                width=width,
                height=external_summary_card_height,
            )
            x_cursor += width + 25
            cell_id += 1

        external_tgw_peer_cell_map: dict[tuple[str, str, str], str] = {}
        external_vpc_peering_cell_map: dict[str, str] = {}

        for peer_index, peer in enumerate(external_tgw_peers):
            x_position, y_position = external_card_positions[peer_index]
            peer_key = (
                self._as_str(peer.get("LocalTransitGatewayId")),
                self._as_str(peer.get("RemoteTransitGatewayId")),
                self._as_str(peer.get("RemoteAccountId")),
            )
            external_tgw_peer_cell_map[peer_key] = str(cell_id)
            self._add_cell(
                root_cell,
                cell_id,
                self._external_tgw_peer_label(peer),
                "rounded=1;whiteSpace=wrap;html=1;fillColor=#fff4e6;strokeColor=#f59e0b;fontSize=12;fontStyle=1;",
                parent=external_layer_id,
                x=x_position,
                y=y_position,
                width=external_detail_card_width,
                height=external_detail_card_height,
            )
            cell_id += 1

        base_vpc_peering_index = len(external_tgw_peers)
        for connection_index, connection in enumerate(vpc_peering_connections):
            x_position, y_position = external_card_positions[
                base_vpc_peering_index + connection_index
            ]
            peering_id = self._as_str(
                connection.get("VpcPeeringConnectionId"), "Unknown"
            )
            external_vpc_peering_cell_map[peering_id] = str(cell_id)
            self._add_cell(
                root_cell,
                cell_id,
                self._vpc_peering_label(connection),
                "rounded=1;whiteSpace=wrap;html=1;fillColor=#fef3c7;strokeColor=#d97706;fontSize=12;fontStyle=1;",
                parent=external_layer_id,
                x=x_position,
                y=y_position,
                width=external_detail_card_width,
                height=external_detail_card_height,
            )
            cell_id += 1

        tgw_layer_y = topology_y + external_layer_height + layer_gap
        transit_layer_id = str(cell_id)
        self._add_cell(
            root_cell,
            cell_id,
            "Transit Gateway Hub",
            "swimlane;rounded=1;whiteSpace=wrap;html=1;fillColor=#ede9fe;strokeColor=#7c3aed;fontStyle=1;fontSize=16;startSize=30;",
            x=topology_x,
            y=tgw_layer_y,
            width=topology_width,
            height=190,
        )
        cell_id += 1

        tgw_cell_map: dict[str, str] = {}
        tgw_x = 40
        for tgw in self.tgws:
            tgw_id = tgw.get("TransitGatewayId", "unknown-tgw")
            tgw_name = self._get_name_from_tags(tgw.get("Tags"), tgw_id)
            owner_id = self._get_tgw_owner_id(tgw)
            peerings = self._find_peering_for_tgw(tgw_id)
            attached_vpcs = [
                attachment
                for attachment in self.tgw_attachments
                if attachment.get("TransitGatewayId") == tgw_id
                and attachment.get("ResourceType") == "vpc"
            ]
            tgw_cell_map[tgw_id] = str(cell_id)
            self._add_cell(
                root_cell,
                cell_id,
                f"{tgw_name}\n{tgw_id}\nOwner: {owner_id}\nVPC Attachments: {len(attached_vpcs)}\nPeerings: {len(peerings)}",
                "rounded=1;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#8b5cf6;fontSize=12;fontStyle=1;",
                parent=transit_layer_id,
                x=tgw_x,
                y=54,
                width=tgw_width,
                height=92,
            )
            cell_id += 1
            tgw_x += tgw_width + tgw_gap

        vpc_layer_y = tgw_layer_y + 190 + layer_gap
        vpc_cell_map: dict[str, str] = {}

        for index, vpc in enumerate(self.vpcs):
            vpc_id = vpc["VpcId"]
            vpc_name = self._get_name_from_tags(vpc.get("Tags"), vpc_id)
            vpc_cell_map[vpc_id] = str(cell_id)
            vpc_x = topology_x + (index * (vpc_width + vpc_gap))
            vpc_y = vpc_layer_y
            self._add_cell(
                root_cell,
                cell_id,
                f"{vpc_name}\n{vpc_id}\nCIDRs: {self._format_vpc_cidrs(vpc)}\n{self._summarize_subnet_roles(vpc_id)}",
                "swimlane;rounded=1;whiteSpace=wrap;html=1;fillColor=#e5f3ea;strokeColor=#82b366;fontStyle=1;fontSize=16;startSize=36;",
                x=vpc_x,
                y=vpc_y,
                width=vpc_width,
                height=vpc_height,
            )
            parent_id = str(cell_id)
            cell_id += 1

            az_groups = vpc_group_map[vpc_id]
            az_width, az_gap = self._compute_az_layout(vpc_width, len(az_groups))

            for az_index, (availability_zone, subnets) in enumerate(az_groups.items()):
                az_lane_height = self._estimate_az_lane_height(len(subnets))
                az_parent_id = str(cell_id)
                self._add_cell(
                    root_cell,
                    cell_id,
                    availability_zone,
                    "swimlane;rounded=1;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#9ca3af;fontStyle=1;fontSize=13;startSize=28;",
                    parent=parent_id,
                    x=20 + (az_index * (az_width + az_gap)),
                    y=68,
                    width=az_width,
                    height=az_lane_height,
                )
                cell_id += 1

                subnet_y = 38
                subnet_card_width = self._az_child_width(az_width)
                for subnet in subnets[:4]:
                    subnet_id = subnet.get("SubnetId", "unknown-subnet")
                    category, display_name = self._classify_subnet(subnet)
                    routes = self._get_subnet_route_info(subnet_id)
                    route_hint = routes[0] if routes else "No external route summary"
                    self._add_cell(
                        root_cell,
                        cell_id,
                        f"{display_name}\n{category}\n{subnet.get('CidrBlock', 'Unknown CIDR')}\n{route_hint}",
                        self._category_style(category),
                        parent=az_parent_id,
                        x=14,
                        y=subnet_y,
                        width=subnet_card_width,
                        height=64,
                    )
                    cell_id += 1
                    subnet_y += 72

                if len(subnets) > 4:
                    self._add_cell(
                        root_cell,
                        cell_id,
                        f"… {len(subnets) - 4} more subnets in {availability_zone}",
                        "rounded=1;whiteSpace=wrap;html=1;fillColor=#f9fafb;strokeColor=#d1d5db;fontSize=11;dashed=1;",
                        parent=az_parent_id,
                        x=14,
                        y=subnet_y,
                        width=subnet_card_width,
                        height=42,
                    )
                    cell_id += 1

            service_lines = self._load_balancer_samples(vpc_id)
            footer_value = "Services\n" + (
                "\n".join(service_lines)
                if service_lines
                else "No load balancers mapped"
            )
            footer_height = self._estimate_footer_height(service_lines)
            self._add_cell(
                root_cell,
                cell_id,
                footer_value,
                "rounded=1;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#82b366;fontSize=11;align=left;verticalAlign=top;spacing=8;",
                parent=parent_id,
                x=20,
                y=68 + max_az_lane_height + 12,
                width=vpc_width - 40,
                height=footer_height,
            )
            cell_id += 1

        graph.set(
            "pageHeight",
            str(max(1600, vpc_layer_y + vpc_height + 120, summary_panel_height + 80)),
        )

        summary_panel = root_cell.find(f"mxCell[@id='{summary_panel_id}']")
        if summary_panel is not None:
            summary_geometry = summary_panel.find("mxGeometry")
            if summary_geometry is not None:
                summary_geometry.set("height", str(summary_panel_height))

        edge_style = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;strokeColor=#6b7280;strokeWidth=2;endArrow=block;"

        for attachment in self.tgw_attachments:
            if attachment.get("ResourceType") != "vpc":
                continue
            source = tgw_cell_map.get(attachment.get("TransitGatewayId"))
            target = vpc_cell_map.get(attachment.get("ResourceId"))
            if source is None or target is None:
                continue
            self._add_cell(
                root_cell,
                cell_id,
                self._attachment_label(attachment),
                edge_style,
                vertex=False,
                edge=True,
                source=source,
                target=target,
            )
            cell_id += 1

        for peering in self.tgw_peering_attachments:
            requester_info = self._as_object(peering.get("RequesterTgwInfo"))
            accepter_info = self._as_object(peering.get("AccepterTgwInfo"))
            requester_id = self._as_str(requester_info.get("TransitGatewayId"))
            accepter_id = self._as_str(accepter_info.get("TransitGatewayId"))

            if requester_id in tgw_cell_map and accepter_id in tgw_cell_map:
                self._add_cell(
                    root_cell,
                    cell_id,
                    self._build_peering_label(peering, requester_id),
                    "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;strokeColor=#7c3aed;strokeWidth=2;dashed=1;endArrow=open;",
                    vertex=False,
                    edge=True,
                    source=tgw_cell_map[requester_id],
                    target=tgw_cell_map[accepter_id],
                )
                cell_id += 1
                continue

            if requester_id in tgw_cell_map:
                local_tgw_id = requester_id
                remote_info = accepter_info
            elif accepter_id in tgw_cell_map:
                local_tgw_id = accepter_id
                remote_info = requester_info
            else:
                continue

            remote_key = (
                local_tgw_id,
                self._as_str(remote_info.get("TransitGatewayId"), "Unknown"),
                self._as_str(remote_info.get("OwnerId"), "Unknown"),
            )
            target = external_tgw_peer_cell_map.get(remote_key)
            source = tgw_cell_map.get(local_tgw_id)
            if source is None or target is None:
                continue
            self._add_cell(
                root_cell,
                cell_id,
                self._build_peering_label(peering, local_tgw_id),
                "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;strokeColor=#f59e0b;strokeWidth=2;dashed=1;endArrow=open;",
                vertex=False,
                edge=True,
                source=source,
                target=target,
            )
            cell_id += 1

        vpc_peering_edge_style = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;strokeColor=#d97706;strokeWidth=2;dashed=1;endArrow=open;"
        for connection in vpc_peering_connections:
            source = vpc_cell_map.get(self._as_str(connection.get("SourceVpcId")))
            target = external_vpc_peering_cell_map.get(
                self._as_str(connection.get("VpcPeeringConnectionId"))
            )
            if source is None or target is None:
                continue
            self._add_cell(
                root_cell,
                cell_id,
                self._vpc_peering_label(connection),
                vpc_peering_edge_style,
                vertex=False,
                edge=True,
                source=source,
                target=target,
            )
            cell_id += 1

        return ET.tostring(root, encoding="unicode")

    def save_diagram(self, output_file: str = "aws-network-architecture.drawio") -> str:
        xml_content = self.generate_drawio_xml()
        output_path = self.base_path / output_file
        output_path.write_text(xml_content, encoding="utf-8")
        return str(output_path)

    def save_topology_json(self, output_file: str = "aws-network-topology.json") -> str:
        topology_model = self.build_topology_model()
        output_path = self.base_path / output_file
        output_path.write_text(
            json.dumps(topology_model, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return str(output_path)


def check_aws_cli() -> bool:
    return bool(os.system("aws --version > /dev/null 2>&1") == 0)


def main() -> int:
    generator = AWSNetworkDiagramGenerator()
    generator.load_all_data()
    diagram_output_path = generator.save_diagram()
    topology_output_path = generator.save_topology_json()
    print(f"✅ 已輸出拓樸圖：{diagram_output_path}")
    print(f"✅ 已輸出拓樸資料：{topology_output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
