import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import scripts.run_graph_web as graph_web
import scripts.pipeline_common as pipeline_common
import scripts.repair_canonical_graph as graph_repair
from scripts.graph_memory import entity_profile_card, graph_profile_quality
from scripts.living_graph.server import visual_graph
from scripts.living_graph.agent_runtime import tools as runtime_tools
from scripts.semantic_edge_builder import relationship_dossier_for_id


def sample_graph():
    return {
        "entities": [
            {
                "id": "person-a",
                "name": "Person A",
                "category": "person",
                "summary": "Person A is a public figure.",
                "links": {"official": "https://parliament.am/person-a"},
                "last_changed_run_id": "run-1",
                "change_type": "updated",
            },
            {
                "id": "E556684A576F0Ba9",
                "name": "E556684A576F0Ba9",
                "category": "person",
                "summary": "Hash-like node that should not render.",
            },
            {
                "id": "party-b",
                "name": "Party B",
                "category": "organization",
                "subtype": "party",
                "summary": "Party B is a political organization.",
            },
            {
                "id": "person-thin",
                "name": "Thin Person",
                "category": "person",
                "summary": "",
            },
        ],
        "relations": [
            {
                "id": "rel-a-party",
                "from": "person-a",
                "to": "party-b",
                "relation_type": "member_of",
                "status": "confirmed",
                "confidence": 0.91,
                "evidence_quote": "Person A is listed as a member of Party B.",
                "source_url": "https://parliament.am/person-a",
                "claim_ids": ["claim-1"],
                "evidence_ids": ["evidence-1"],
                "source_ids": ["source-1"],
                "last_changed_run_id": "run-1",
                "change_type": "new",
            }
        ],
        "claims": [
            {
                "id": "claim-1",
                "subject_vertex_id": "person-a",
                "object_vertex_id": "party-b",
                "claim_type": "member_of",
                "statement": "Person A is a member of Party B.",
            }
        ],
        "evidence": [{"id": "evidence-1", "quote": "Person A is listed as a member of Party B."}],
        "sources": [{"id": "source-1", "url": "https://parliament.am/person-a", "source_class": "official"}],
        "event_nodes": [],
        "story_mentions": [],
        "runtime": {},
    }


class GraphRagContractTests(unittest.TestCase):
    def test_entity_profile_card_contract_and_quality(self):
        graph = sample_graph()
        card = entity_profile_card(graph, "person-a")
        self.assertEqual(card["contract"], "EntityProfileContract.v1")
        self.assertGreaterEqual(card["profile_quality"]["source_count"], 1)
        self.assertGreaterEqual(card["profile_quality"]["official_source_count"], 1)
        self.assertTrue(card["direct_network"])
        self.assertIn("biography_or_history", card)

    def test_profile_quality_report_marks_thin_entities(self):
        report = graph_profile_quality(sample_graph())
        thin = [item for item in report["items"] if item["entity_id"] == "person-thin"][0]
        self.assertEqual(report["contract"], "ProfileQualityReport.v1")
        self.assertEqual(thin["profile_quality"]["coverage"], "thin")
        self.assertIn("source_links", thin["profile_quality"]["missing_sections"])

    def test_relationship_dossier_contract_uses_claims_and_evidence(self):
        dossier = relationship_dossier_for_id(sample_graph(), "rel-a-party")
        self.assertEqual(dossier["contract"], "RelationshipDossierContract.v1")
        self.assertEqual(dossier["canonical_or_derived"], "canonical")
        self.assertEqual(dossier["relation_class"], "membership")
        self.assertTrue(dossier["direct_claims"])
        self.assertTrue(dossier["evidence"])

    def test_node_research_exposes_research_run_contract_without_graph_write(self):
        graph = sample_graph()
        with patch.object(graph_web, "search_web", lambda query, limit=4: []):
            result = graph_web.node_research(graph, "person-a", budget=1)
        self.assertTrue(result["ok"])
        self.assertEqual(result["research_run"]["contract"], "ResearchRunContract.v1")
        self.assertEqual(result["research_run"]["target_entities"], ["person-a"])
        self.assertIn("graph_diff", result["research_run"])

    def test_visual_graph_payload_contains_change_markers(self):
        payload = visual_graph(sample_graph(), latest_diff={"run_id": "run-1"})
        node = next(item for item in payload["nodes"] if item["id"] == "person-a")
        edge = next(item for item in payload["edges"] if item["id"] == "rel-a-party")
        self.assertEqual(node["last_changed_run_id"], "run-1")
        self.assertEqual(node["change_type"], "updated")
        self.assertEqual(edge["last_changed_run_id"], "run-1")
        self.assertEqual(edge["change_type"], "new")

    def test_hash_like_vertex_proposals_are_rejected(self):
        with patch.object(runtime_tools, "load_graph", return_value={"vertices": [], "edges": [], "claims": [], "sources": [], "evidence": []}):
            with patch.object(runtime_tools, "write_json") as write_json:
                with patch.object(runtime_tools, "save_tool_call") as save_tool_call:
                    with patch.object(runtime_tools, "save_artifact") as save_artifact:
                        diff = runtime_tools.propose_graph_update(
                            "run-1",
                            "item-1",
                            {
                                "entity": {"id": "E556684A576F0Ba9", "label": "E556684A576F0Ba9", "category": "person", "summary": "Hash-like vertex"},
                                "claims": [],
                                "profile_update": {},
                                "source_url": "https://example.com",
                                "evidence_quote": "example",
                                "updated_at": "2026-05-06T00:00:00Z",
                            },
                        )
        self.assertTrue(diff["rejected"])
        self.assertEqual(diff["rejected"][0]["reason"], "hash_like_label")
        write_json.assert_not_called()

    def test_canonical_graph_writes_merge_instead_of_replace(self):
        with tempfile.TemporaryDirectory() as tempdir:
            graph_path = Path(tempdir) / "country-graph.json"
            with patch.object(pipeline_common, "CANONICAL_GRAPH", graph_path):
                pipeline_common.write_json(
                    graph_path,
                    {
                        "vertices": [{"id": "node-a", "label": "Node A", "category": "person"}],
                        "edges": [],
                        "claims": [],
                        "sources": [],
                        "evidence": [],
                        "events": [],
                        "relations": [],
                        "derived_relations": [],
                        "runtime": {},
                        "indexes": {},
                        "migration": {"admission_policy_version": 2},
                    },
                )
                pipeline_common.write_json(
                    graph_path,
                    {
                        "vertices": [{"id": "node-b", "label": "Node B", "category": "party"}],
                        "edges": [{"id": "edge-b", "from": "node-a", "to": "node-b", "type": "member_of", "relation_type": "member_of", "status": "probable", "confidence": 0.6}],
                        "claims": [{"id": "claim-b", "subject_vertex_id": "node-a", "object_vertex_id": "node-b", "claim_type": "member_of", "statement": "Node A is a member of Node B.", "source_ids": [], "evidence_ids": []}],
                        "sources": [{"id": "source-b", "url": "https://example.com", "source_class": "official"}],
                        "evidence": [{"id": "evidence-b", "source_id": "source-b", "url": "https://example.com", "supports_claim_ids": ["claim-b"]}],
                        "events": [],
                        "relations": [],
                        "derived_relations": [],
                        "runtime": {},
                        "indexes": {},
                        "migration": {"admission_policy_version": 2},
                    },
                )
                merged = pipeline_common.load_json(graph_path, {})
            self.assertEqual({row["id"] for row in merged["vertices"]}, {"node-a", "node-b"})
            self.assertEqual({row["id"] for row in merged["edges"]}, {"edge-b"})
            self.assertEqual({row["id"] for row in merged["claims"]}, {"claim-b"})

    def test_repair_helpers_reject_sentence_like_vertices(self):
        ok, reason = graph_repair._should_keep_vertex({"id": "person-government-team-members", "label": "Government Team Members", "category": "person"})  # type: ignore[attr-defined]
        self.assertFalse(ok)
        self.assertIn(reason, {"missing_human_readable_name", "internal_id_leak"})
        ok, reason = graph_repair._should_keep_vertex({"id": "office-chief-of-staff-of-the-prime-minister-arayik-harutyunyan-met-with-anthony-banbury", "label": "Chief of Staff of the Prime Minister Arayik Harutyunyan met with Anthony Banbury, President and CEO of the International Foundation for Electoral Systems (IFES)", "category": "office"})  # type: ignore[attr-defined]
        self.assertFalse(ok)
        self.assertEqual(reason, "internal_id_leak")


if __name__ == "__main__":
    unittest.main()
