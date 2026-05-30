import os
import shutil
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from scripts.pipeline_common import load_graph
from scripts.run_graph_web import prompt_command


ROOT = Path(__file__).resolve().parent
CANONICAL_GRAPH = ROOT / "content" / "graph" / "country-graph.json"


class PromptCommandPipelineTests(unittest.TestCase):
    @staticmethod
    def fake_workflow_response(prompt, workflow_name):
        return {
            "ok": True,
            "prompt": prompt,
            "workflow": workflow_name,
            "selected_workflow": workflow_name,
            "accepted_sources": [],
            "graph_diff": {
                "new_nodes": [],
                "updated_nodes": [],
                "new_links": [],
                "updated_links": [],
            },
            "ui_edge_payloads": [],
            "ui_highlights": {"node_ids": [], "link_ids": []},
        }

    @classmethod
    def setUpClass(cls):
        cls._temp_dir = tempfile.TemporaryDirectory()
        cls._temp_graph = Path(cls._temp_dir.name) / "country-graph.json"
        shutil.copy2(CANONICAL_GRAPH, cls._temp_graph)
        cls._previous_graph_override = os.environ.get("THIEZER_CANONICAL_GRAPH_PATH")
        os.environ["THIEZER_CANONICAL_GRAPH_PATH"] = str(cls._temp_graph)

    @classmethod
    def tearDownClass(cls):
        if cls._previous_graph_override is None:
            os.environ.pop("THIEZER_CANONICAL_GRAPH_PATH", None)
        else:
            os.environ["THIEZER_CANONICAL_GRAPH_PATH"] = cls._previous_graph_override
        cls._temp_dir.cleanup()

    def run_prompt(self, prompt):
        graph = load_graph()
        return prompt_command(graph, prompt)

    def assert_common_response_shape(self, response):
        self.assertTrue(response.get("ok"), response)
        self.assertIn(response.get("selected_workflow") or response.get("workflow"), {"topic_deep_research", "institutional_roster"})
        self.assertIsInstance(response.get("accepted_sources", []), list)
        self.assertIsInstance(response.get("graph_diff", {}), dict)
        self.assertIsInstance(response.get("ui_edge_payloads", []), list)
        self.assertIsInstance(response.get("ui_highlights", {}), dict)

    def test_ministers_prompt_returns_structured_payload(self):
        prompt = "Найди какие сейчас есть министры у нас и какие были в целом за период Пашиняна как премьера. И разбери их по всей глубине."
        with patch("scripts.run_graph_web.plan_command_workflow", return_value={"workflow": "institutional_roster", "model_selection": {}, "seed_queries": []}), patch("scripts.run_graph_web.run_institutional_roster_workflow") as mocked_workflow:
            mocked_workflow.return_value = self.fake_workflow_response(prompt, "institutional_roster")
            response = self.run_prompt(prompt)
        self.assert_common_response_shape(response)
        mocked_workflow.assert_called_once()

    def test_general_staff_prompt_returns_structured_payload(self):
        prompt = "Найди кто сейчас начальник Генштаба Армении, кто были начальники Генштаба за период Пашиняна как премьера, какие были назначения, снятия и ключевые изменения. Разбери по всей глубине."
        with patch("scripts.run_graph_web.plan_command_workflow", return_value={"workflow": "institutional_roster", "model_selection": {}, "seed_queries": []}), patch("scripts.run_graph_web.run_institutional_roster_workflow") as mocked_workflow:
            mocked_workflow.return_value = self.fake_workflow_response(prompt, "institutional_roster")
            response = self.run_prompt(prompt)
        self.assert_common_response_shape(response)
        mocked_workflow.assert_called_once()


if __name__ == "__main__":
    unittest.main()
