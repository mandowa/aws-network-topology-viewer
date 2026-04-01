from __future__ import annotations

import importlib.util
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import ClassVar, override


MODULE_PATH = Path(__file__).resolve().parents[1] / "generate_aws_diagram.py"
MODULE_SPEC = importlib.util.spec_from_file_location(
    "generate_aws_diagram", MODULE_PATH
)
assert MODULE_SPEC is not None
assert MODULE_SPEC.loader is not None
MODULE = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(MODULE)
AWSNetworkDiagramGenerator = MODULE.AWSNetworkDiagramGenerator


class GenerateAwsDiagramTests(unittest.TestCase):
    generator: ClassVar[AWSNetworkDiagramGenerator]

    @classmethod
    @override
    def setUpClass(cls):
        cls.generator = AWSNetworkDiagramGenerator()
        cls.generator.load_all_data()

    def test_generate_drawio_xml_is_valid_xml(self):
        xml_content = self.generator.generate_drawio_xml()

        root = ET.fromstring(xml_content)

        self.assertEqual(root.tag, "mxfile")

    def test_generate_drawio_xml_includes_layered_topology_and_summary_panel(self):
        xml_content = self.generator.generate_drawio_xml()

        self.assertIn("AWS Network Topology Overview", xml_content)
        self.assertIn("Topology Summary", xml_content)
        self.assertIn("Transit Gateway Hub", xml_content)
        self.assertIn("External Connectivity", xml_content)
        self.assertIn("TCK", xml_content)
        self.assertIn("Security", xml_content)
        self.assertIn("Purpose Groups", xml_content)
        self.assertIn("External TGW Peer", xml_content)
        self.assertIn("External VPC Peer", xml_content)

    def test_classify_subnet_uses_role_aware_categories(self):
        subnet_by_name = {
            self.generator._get_name_from_tags(
                subnet.get("Tags"), subnet.get("SubnetId", "")
            ): subnet
            for subnet in self.generator.subnets
        }

        self.assertEqual(
            self.generator._classify_subnet(subnet_by_name["TCK_CloudNativePrivate-a"])[
                0
            ],
            "Cloud Native",
        )
        self.assertEqual(
            self.generator._classify_subnet(subnet_by_name["TCK_Trusted-a"])[0],
            "Private App",
        )
        self.assertEqual(
            self.generator._classify_subnet(subnet_by_name["TCK_InfraMgmt-c"])[0],
            "Platform",
        )

    def test_category_style_maps_expected_palette(self):
        self.assertIn("fillColor=#e1d5e7", self.generator._category_style("Platform"))
        self.assertIn(
            "fillColor=#dae8fc", self.generator._category_style("Cloud Native")
        )
        self.assertIn("fillColor=#fff2cc", self.generator._category_style("Security"))

    def test_format_count_uses_correct_singular_and_plural_labels(self):
        self.assertEqual(self.generator._format_count(1, "subnet"), "1 subnet")
        self.assertEqual(self.generator._format_count(2, "subnet"), "2 subnets")

    def test_compute_az_layout_preserves_width_for_dense_az_counts(self):
        lane_width, lane_gap = self.generator._compute_az_layout(700, 6)

        self.assertEqual(lane_gap, 14)
        self.assertGreaterEqual(lane_width, 60)
        self.assertLessEqual((lane_width * 6) + (lane_gap * 5), 660)

    def test_compute_az_layout_stays_within_vpc_width_for_high_az_counts(self):
        lane_width, lane_gap = self.generator._compute_az_layout(700, 12)

        self.assertLessEqual((lane_width * 12) + (lane_gap * 11), 660)
        self.assertGreaterEqual(lane_gap, 0)
        self.assertGreaterEqual(lane_width, 1)

    def test_az_child_width_stays_positive_under_extreme_compression(self):
        self.assertEqual(self.generator._az_child_width(12), 40)
        self.assertEqual(self.generator._az_child_width(80), 52)

    def test_route_table_precedence_prefers_explicit_subnet_association(self):
        generator = AWSNetworkDiagramGenerator()
        generator.subnets = [
            {"SubnetId": "subnet-1", "VpcId": "vpc-1", "Tags": []},
        ]
        generator.route_tables = [
            {
                "RouteTableId": "rtb-main",
                "VpcId": "vpc-1",
                "Associations": [{"Main": True}],
                "Routes": [{"DestinationCidrBlock": "0.0.0.0/0", "GatewayId": "igw-1"}],
            },
            {
                "RouteTableId": "rtb-explicit",
                "VpcId": "vpc-1",
                "Associations": [{"SubnetId": "subnet-1"}],
                "Routes": [
                    {
                        "DestinationCidrBlock": "0.0.0.0/0",
                        "TransitGatewayId": "tgw-1",
                    }
                ],
            },
        ]

        effective_tables = generator._get_effective_route_tables_for_subnet("subnet-1")

        self.assertEqual(len(effective_tables), 1)
        self.assertEqual(effective_tables[0]["RouteTableId"], "rtb-explicit")
        self.assertFalse(generator._is_public_subnet("subnet-1"))

    def test_classify_subnet_keeps_public_precedence_over_other_roles(self):
        subnet = {
            "SubnetId": "subnet-public-security",
            "Tags": [
                {"Key": "Name", "Value": "public-security-zone"},
                {"Key": "smt:net:alias", "Value": "inspection-public"},
            ],
            "MapPublicIpOnLaunch": False,
        }

        category, display_name = self.generator._classify_subnet(subnet)

        self.assertEqual(category, "Public Edge")
        self.assertEqual(display_name, "inspection-public")

    def test_generate_drawio_xml_keeps_subnet_cards_visible_for_dense_az_layouts(self):
        generator = AWSNetworkDiagramGenerator()
        generator.vpcs = [
            {"VpcId": "vpc-dense", "CidrBlock": "10.0.0.0/16", "Tags": []}
        ]
        generator.tgws = []
        generator.tgw_attachments = []
        generator.tgw_peering_attachments = []
        generator.internet_gateways = []
        generator.nat_gateways = []
        generator.load_balancers = []
        generator.route_tables = []
        generator.subnets = [
            {
                "SubnetId": f"subnet-{index}",
                "VpcId": "vpc-dense",
                "AvailabilityZone": f"az-{index}",
                "CidrBlock": f"10.0.{index}.0/24",
                "Tags": [{"Key": "Name", "Value": f"dense-{index}"}],
            }
            for index in range(1, 25)
        ]

        xml_content = generator.generate_drawio_xml()
        root = ET.fromstring(xml_content)
        cells = root.findall("diagram/mxGraphModel/root/mxCell")

        subnet_cells = [
            cell for cell in cells if cell.attrib.get("value", "").startswith("dense-")
        ]

        self.assertTrue(subnet_cells)
        for cell in subnet_cells:
            geometry = cell.find("mxGeometry")
            self.assertIsNotNone(geometry)
            assert geometry is not None
            self.assertGreaterEqual(int(geometry.attrib["width"]), 40)

    def test_generate_drawio_xml_uses_dynamic_layout_and_role_styles(self):
        xml_content = self.generator.generate_drawio_xml()
        root = ET.fromstring(xml_content)

        graph = root.find("diagram/mxGraphModel")
        self.assertIsNotNone(graph)
        assert graph is not None
        self.assertGreaterEqual(int(graph.attrib["pageHeight"]), 1600)

        cells = root.findall("diagram/mxGraphModel/root/mxCell")
        summary_panel = next(
            cell for cell in cells if cell.attrib.get("value") == "Topology Summary"
        )
        summary_geometry = summary_panel.find("mxGeometry")
        self.assertIsNotNone(summary_geometry)
        assert summary_geometry is not None
        self.assertGreater(int(summary_geometry.attrib["height"]), 300)

        self.assertIn(
            self.generator._summarize_subnet_roles("vpc-0a0fb3ab856e73fa4"), xml_content
        )
        self.assertIn(
            self.generator._summarize_subnet_roles("vpc-028bfb7f2d8b84cbf"), xml_content
        )
        self.assertIn("fillColor=#dae8fc", xml_content)
        self.assertIn("fillColor=#fff2cc", xml_content)
        self.assertNotIn("1 subnets", xml_content)

    def test_format_vpc_cidrs_includes_secondary_associated_ranges(self):
        vpc = {
            "VpcId": "vpc-secondary",
            "CidrBlock": "10.159.64.0/18",
            "CidrBlockAssociationSet": [
                {"CidrBlock": "10.159.64.0/18"},
                {"CidrBlock": "10.158.192.0/18"},
            ],
        }

        self.assertEqual(
            self.generator._format_vpc_cidrs(vpc),
            "10.159.64.0/18, 10.158.192.0/18",
        )

    def test_generate_drawio_xml_includes_all_vpc_cidrs_for_multi_cidr_vpc(self):
        xml_content = self.generator.generate_drawio_xml()

        self.assertIn("TCK · 10.159.64.0/18, 10.158.192.0/18", xml_content)
        self.assertIn(
            "TCK&#10;vpc-0a0fb3ab856e73fa4&#10;CIDRs: 10.159.64.0/18, 10.158.192.0/18&#10;",
            xml_content,
        )

    def test_collect_external_tgw_peers_returns_unique_remote_peers(self):
        peers = self.generator._collect_external_tgw_peers()

        self.assertEqual(len(peers), 4)
        self.assertEqual(
            {
                peer["RemoteTransitGatewayId"]
                for peer in peers
                if "RemoteTransitGatewayId" in peer
            },
            {
                "tgw-08ce130fec5a8960f",
                "tgw-00c51b4708a49e3c0",
                "tgw-025766b1f30ab631a",
                "tgw-0f794004ff6748b98",
            },
        )

    def test_build_topology_model_includes_schema_version_and_graph_contract(self):
        topology_model = self.generator.build_topology_model()

        metadata = topology_model["metadata"]
        self.assertEqual(metadata["schemaVersion"], "1.1")

        graph_model = metadata["graphModel"]
        self.assertEqual(graph_model["hierarchySource"], "topology.vpcs")
        self.assertEqual(
            graph_model["graphSource"], "topology.nodes and topology.edges"
        )
        self.assertEqual(graph_model["indexSource"], "topology.indexes")

        node_type_lookup = {
            item["type"]: item for item in graph_model["nodeTypes"] if "type" in item
        }
        self.assertTrue(
            node_type_lookup["transit-gateway"]["resourceKind"] == "aws-resource"
        )
        self.assertTrue(
            node_type_lookup["external-transit-gateway-peer"]["isSynthetic"]
        )

        edge_type_lookup = {
            item["type"]: item for item in graph_model["edgeTypes"] if "type" in item
        }
        self.assertFalse(edge_type_lookup["tgw-attachment"]["isInferred"])
        self.assertTrue(edge_type_lookup["vpc-peering"]["isInferred"])

    def test_build_topology_model_distinguishes_canonical_and_synthetic_graph_objects(
        self,
    ):
        topology_model = self.generator.build_topology_model()
        nodes = topology_model["topology"]["nodes"]
        edges = topology_model["topology"]["edges"]

        transit_gateway_nodes = [
            node for node in nodes if node.get("type") == "transit-gateway"
        ]
        self.assertTrue(transit_gateway_nodes)
        self.assertTrue(
            all(not node.get("isSynthetic") for node in transit_gateway_nodes)
        )
        self.assertTrue(
            all(
                node.get("resourceKind") == "aws-resource"
                for node in transit_gateway_nodes
            )
        )

        external_nodes = [
            node
            for node in nodes
            if node.get("type") == "external-transit-gateway-peer"
        ]
        self.assertTrue(external_nodes)
        self.assertTrue(all(node.get("isSynthetic") for node in external_nodes))
        self.assertTrue(
            all(
                node.get("source") == "tgw-peering-attachments.json"
                for node in external_nodes
            )
        )

        attachment_edges = [
            edge for edge in edges if edge.get("type") == "tgw-attachment"
        ]
        self.assertTrue(attachment_edges)
        self.assertTrue(
            all(edge.get("relationship") == "attachment" for edge in attachment_edges)
        )
        self.assertTrue(all(not edge.get("isSynthetic") for edge in attachment_edges))
        self.assertTrue(all("displayLabel" in edge for edge in attachment_edges))

    def test_build_topology_model_adds_graph_indexes_and_connected_node_references(
        self,
    ):
        topology_model = self.generator.build_topology_model()

        topology = topology_model["topology"]
        indexes = topology["indexes"]

        node_by_id = indexes["nodeById"]
        edge_by_id = indexes["edgeById"]
        node_ids_by_type = indexes["nodeIdsByType"]
        adjacent_node_ids_by_node_id = indexes["adjacentNodeIdsByNodeId"]

        self.assertIn("tgw:tgw-07a7e47fad4adddaa", node_by_id)
        self.assertIn("vpc:vpc-0a0fb3ab856e73fa4", node_by_id)
        self.assertIn("tgw-attach-0cb09bfcfb9ebc838", edge_by_id)
        self.assertIn("vpc", node_ids_by_type)
        self.assertIn("transit-gateway", node_ids_by_type)
        self.assertIn(
            "vpc:vpc-0a0fb3ab856e73fa4",
            adjacent_node_ids_by_node_id["tgw:tgw-07a7e47fad4adddaa"],
        )

        tck_vpc = next(
            vpc for vpc in topology["vpcs"] if vpc.get("id") == "vpc-0a0fb3ab856e73fa4"
        )
        self.assertEqual(tck_vpc["graphNodeId"], "vpc:vpc-0a0fb3ab856e73fa4")
        self.assertIn("tgw:tgw-07a7e47fad4adddaa", tck_vpc["connectedGraphNodeIds"])
        self.assertIn(
            "external-vpc-peer:pcx-0818b6b5dedf5320d", tck_vpc["connectedGraphNodeIds"]
        )

        tgw = next(
            item
            for item in topology["transitGateways"]
            if item.get("id") == "tgw-07a7e47fad4adddaa"
        )
        self.assertEqual(tgw["graphNodeId"], "tgw:tgw-07a7e47fad4adddaa")
        self.assertIn("vpc:vpc-0a0fb3ab856e73fa4", tgw["connectedGraphNodeIds"])

        external_peer = next(
            item
            for item in topology["externalTransitGatewayPeers"]
            if item.get("RemoteTransitGatewayId") == "tgw-08ce130fec5a8960f"
        )
        self.assertTrue(external_peer["graphNodeId"].startswith("external-tgw-peer:"))
        self.assertIn(
            "tgw:tgw-07a7e47fad4adddaa", external_peer["connectedGraphNodeIds"]
        )

        external_vpc_peer = topology["externalVpcPeerings"][0]
        self.assertEqual(
            external_vpc_peer["graphNodeId"],
            "external-vpc-peer:pcx-0818b6b5dedf5320d",
        )
        self.assertIn(
            "vpc:vpc-0a0fb3ab856e73fa4",
            external_vpc_peer["connectedGraphNodeIds"],
        )

    def test_build_topology_model_marks_route_inferred_vpc_peerings(self):
        generator = AWSNetworkDiagramGenerator()
        generator.vpcs = [
            {
                "VpcId": "vpc-1",
                "CidrBlock": "10.0.0.0/16",
                "Tags": [{"Key": "Name", "Value": "AppVpc"}],
            }
        ]
        generator.subnets = [
            {
                "SubnetId": "subnet-1",
                "VpcId": "vpc-1",
                "AvailabilityZone": "az-1",
                "CidrBlock": "10.0.1.0/24",
                "Tags": [{"Key": "Name", "Value": "private-a"}],
            }
        ]
        generator.route_tables = [
            {
                "RouteTableId": "rtb-1",
                "VpcId": "vpc-1",
                "Associations": [{"Main": True}],
                "Routes": [
                    {
                        "DestinationCidrBlock": "172.16.0.0/16",
                        "VpcPeeringConnectionId": "pcx-123",
                    }
                ],
            }
        ]
        generator.tgws = []
        generator.tgw_attachments = []
        generator.tgw_peering_attachments = []
        generator.internet_gateways = []
        generator.nat_gateways = []
        generator.load_balancers = []

        topology_model = generator.build_topology_model()
        nodes = topology_model["topology"]["nodes"]
        edges = topology_model["topology"]["edges"]

        peer_node = next(
            node for node in nodes if node.get("id") == "external-vpc-peer:pcx-123"
        )
        self.assertTrue(peer_node["isSynthetic"])
        self.assertTrue(peer_node["isInferred"])
        self.assertEqual(peer_node["source"], "route-tables.json")

        peering_edge = next(
            edge for edge in edges if edge.get("id") == "vpc-peering:pcx-123"
        )
        self.assertTrue(peering_edge["isSynthetic"])
        self.assertTrue(peering_edge["isInferred"])
        self.assertEqual(peering_edge["relationship"], "reachable-peering")
        self.assertEqual(peering_edge["inferenceSource"], "route-tables.json")
        self.assertEqual(peering_edge["routeTableIds"], ["rtb-1"])
        self.assertEqual(peering_edge["destinations"], ["172.16.0.0/16"])

    def test_generate_drawio_xml_connects_local_tgws_to_external_peer_nodes(self):
        xml_content = self.generator.generate_drawio_xml()
        root = ET.fromstring(xml_content)
        cells = root.findall("diagram/mxGraphModel/root/mxCell")

        external_tgw_nodes = [
            cell
            for cell in cells
            if cell.attrib.get("value", "").startswith("External TGW Peer")
        ]
        external_tgw_node_ids = {cell.attrib["id"] for cell in external_tgw_nodes}
        external_tgw_edges = [
            cell
            for cell in cells
            if cell.attrib.get("edge") == "1"
            and cell.attrib.get("target") in external_tgw_node_ids
        ]

        self.assertEqual(len(external_tgw_nodes), 4)
        self.assertTrue(external_tgw_edges)
        self.assertTrue(
            any(
                "Remote TGW: tgw-08ce130fec5a8960f" in cell.attrib.get("value", "")
                for cell in external_tgw_nodes
            )
        )

    def test_generate_drawio_xml_connects_vpcs_to_external_vpc_peering_nodes(self):
        generator = AWSNetworkDiagramGenerator()
        generator.vpcs = [
            {
                "VpcId": "vpc-1",
                "CidrBlock": "10.0.0.0/16",
                "Tags": [{"Key": "Name", "Value": "AppVpc"}],
            }
        ]
        generator.subnets = [
            {
                "SubnetId": "subnet-1",
                "VpcId": "vpc-1",
                "AvailabilityZone": "az-1",
                "CidrBlock": "10.0.1.0/24",
                "Tags": [{"Key": "Name", "Value": "private-a"}],
            }
        ]
        generator.route_tables = [
            {
                "RouteTableId": "rtb-1",
                "VpcId": "vpc-1",
                "Associations": [{"Main": True}],
                "Routes": [
                    {
                        "DestinationCidrBlock": "172.16.0.0/16",
                        "VpcPeeringConnectionId": "pcx-123",
                    }
                ],
            }
        ]
        generator.tgws = []
        generator.tgw_attachments = []
        generator.tgw_peering_attachments = []
        generator.internet_gateways = []
        generator.nat_gateways = []
        generator.load_balancers = []

        xml_content = generator.generate_drawio_xml()
        root = ET.fromstring(xml_content)
        cells = root.findall("diagram/mxGraphModel/root/mxCell")

        vpc_peer_nodes = [
            cell
            for cell in cells
            if cell.attrib.get("vertex") == "1"
            and cell.attrib.get("value", "").startswith("External VPC Peer")
        ]
        vpc_peer_node_ids = {cell.attrib["id"] for cell in vpc_peer_nodes}
        vpc_peer_edges = [
            cell
            for cell in cells
            if cell.attrib.get("edge") == "1"
            and cell.attrib.get("target") in vpc_peer_node_ids
        ]

        self.assertEqual(len(vpc_peer_nodes), 1)
        self.assertTrue(vpc_peer_edges)
        self.assertIn("pcx-123", vpc_peer_nodes[0].attrib.get("value", ""))


if __name__ == "__main__":
    _ = unittest.main()
