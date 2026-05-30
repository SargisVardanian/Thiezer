import json
import re
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from scripts.living_graph.agent_runtime import runtime, task_db, workers
from scripts.living_graph.agent_runtime.government_am import parse_government_members_page, parse_prime_minister_staff_structure_page
from scripts.living_graph.research_tools import claim_extractor
from scripts.living_graph.research_tools.temporal_planner import build_role_queries, extract_year_range, month_windows, year_windows
from scripts.living_graph.research_tools.search_provider import DeterministicOfficialSearchProvider
from scripts.living_graph.research_tools.source_registry import load_source_registry_snapshot
from scripts.living_graph.question_generator import generate_research_questions
from scripts.living_graph.research_queue import load_question_queue, mark_question_attempt, mark_question_status, next_queued_question, question_to_run_payload, start_next_question_run
from scripts.living_graph.subgraph_builder import build_subgraph
from scripts import national_graph_cycle
from scripts import model_runtime
from scripts.pipeline_common import (
    append_claim_records,
    build_entity_registry,
    canonical_graph_path,
    canonical_person_key,
    claim_records_index,
    entity_types_compatible,
    load_claim_records,
    load_entity_alias_index,
    resolve_entity,
)


ROSTER_HTML = """
<html><body>
<a href="deputies.php?ID=1500&lang=eng&sel=details">Simonyan Alen (President of the National Assembly)</a>
<a href="deputies.php?ID=1501&lang=eng&sel=details">Arshakyan Hakob (Vice President of the National Assembly)</a>
<a href="deputies.php?ID=1502&lang=eng&sel=details">Aslanyan Vahe (Deputy)</a>
</body></html>
"""

FACTIONS_HTML = """
<html><body>
"Civil Contract" Faction
Simonyan Alen
Arshakyan Hakob
Aslanyan Vahe
</body></html>
"""

PROFILE_HTML = """
<html><body>
| Alen Simonyan Birth date
Birth date
16.01.1980
Party
"Civil Contract"
Faction
"Civil Contract" Faction
E-mail
alen.simonyan@parliament.am
He was born in Yerevan. He served in parliament and held public office.
</body></html>
"""

GOV_MEMBERS_HTML = """
<html><body>
<div id="min-bl1"><a href="/en/gov-members/1029/">Anahit<br />Avanesyan</a><p>Minister of Health</p></div>
<div id="min-bl1"><a href="/en/gov-members/791/">Ararat<br />Mirzoyan</a><p>Minister of Foreign Affairs</p></div>
</body></html>
"""

GOV_STAFF_STRUCTURE_HTML = """
<html><body>
<h3>Chief of Staff</h3>
<div class="staff-structure">
  <p class="staff-name"><a href="/en/staff-structure/other/788/">Arayik Harutyunyan</a></p>
</div>
<h3>Deputy Chiefs of Prime Minister Staff</h3>
<div class="staff-structure">
  <p><strong><a href="/en/staff-structure/other/956/">Armenak Khachatryan</a></strong></p>
  <p><strong><a href="/en/staff-structure/other/1042/">Artur Hovsepyan</a></strong></p>
</div>
<h3>Staff Departments</h3>
<div class="staff-structure">
  <p class="staff-name">Department for Relations with the National Assembly</p>
  <p>Head: <a href="/en/staff-structure/other/717/">Anahit Stephanyan</a></p>
</div>
</body></html>
"""

MINISTER_PROFILE_HTML = """
<html><body>
<div class="member-profile">
  <p>Anahit Avanesyan serves as Minister of Health.</p>
  <p>She was born in Yerevan and has served in public administration for many years.</p>
  <p>She graduated from Yerevan State Medical University and worked in the healthcare sector.</p>
</div>
</body></html>
"""


class AgentRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        root = Path(self.tempdir.name)
        self.db_path = root / "tasks.sqlite"
        self.latest_path = root / "latest.json"
        self.runs_log = root / "runs.jsonl"
        self.claims_log = root / "claims.jsonl"
        self.graph_path = root / "country-graph.json"
        self.patches = [
            patch.dict("os.environ", {"THIEZER_CANONICAL_GRAPH_PATH": str(self.graph_path)}),
            patch.object(task_db, "DB_PATH", self.db_path),
            patch.object(runtime, "LATEST_RESEARCH_RUN_FILE", self.latest_path),
            patch.object(runtime, "RESEARCH_RUNS_LOG", self.runs_log),
            patch.object(workers, "append_claim_records", side_effect=lambda claims: append_claim_records(claims, path=self.claims_log)),
            patch.object(workers, "write_entity_registry", return_value={}),
            patch.object(
                claim_extractor,
                "call_parser_model",
                return_value=({}, {"ok": False, "provider": "deterministic", "model": "rules", "raw": "", "error": "mocked"}),
            ),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        task_db.init_db()

    def _set_work_item_status(self, item_id: str, status: str, error: str = "") -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                "UPDATE work_items SET status = ?, error = ?, updated_at = datetime('now') WHERE item_id = ?",
                (status, error, item_id),
            )
            conn.commit()

    def test_start_run_creates_parliament_discovery_item(self):
        started = runtime.start_run("Изучи депутатов парламента Армении после 2021", {"budget_pages": 20, "max_depth": 2})
        self.assertEqual(started["run_type"], "parliament_roster_enrichment")
        trace = task_db.build_research_trace(started["run_id"])
        self.assertEqual(len(trace["work_items"]), 1)
        self.assertEqual(trace["work_items"][0]["item_type"], "discover_parliament_roster")

    def test_role_history_prompt_routes_to_role_history_enrichment(self):
        started = runtime.start_run("Найди всех руководителей аппарата премьер-министра Никола Пашиняна за период 2018-2026 и дай их биографии", {"budget_pages": 20, "max_depth": 2})
        self.assertEqual(started["run_type"], "role_history_enrichment")
        trace = task_db.build_research_trace(started["run_id"])
        self.assertEqual(trace["work_items"][0]["item_type"], "discover_role_history")
        self.assertEqual(trace["run"].get("target_role"), "Head/Chief of Staff of the Prime Minister of Armenia")
        self.assertEqual(trace["run"].get("date_from"), 2018)
        self.assertEqual(trace["run"].get("date_to"), 2026)
        self.assertEqual(trace["run"].get("context_person"), "Nikol Pashinyan")
        self.assertEqual(trace["run"].get("requested_entities"), ["persons", "offices", "institutions", "companies", "parties"])
        self.assertEqual(trace["run"].get("temporal_granularity"), "year")
        self.assertNotIn("infer", str(trace["run"].get("target_entity", "")).lower())

    def test_complete_biography_prompt_does_not_match_mp_substring(self):
        started = runtime.start_run("Complete a source-backed biography profile for Artur Hovsepyan.", {"budget_pages": 7, "max_depth": 2})
        self.assertEqual(started["run_type"], "generic_topic_research")

    def test_temporal_planner_builds_year_and_month_windows(self):
        self.assertEqual(extract_year_range("2018-2026"), (2018, 2026))
        windows = year_windows(2018, 2020)
        self.assertEqual(len(windows), 3)
        self.assertEqual(windows[0].granularity, "year")
        month_label = month_windows(2020)[0].label()
        self.assertIn("2020-01-01", month_label)
        queries = build_role_queries(target_person="Nikol Pashinyan", office_family="Chief of Staff of the Prime Minister", window=month_windows(2020)[0])
        self.assertTrue(any("2020-01" in query for query in queries))

    def test_discovery_step_creates_fetch_work_items(self):
        started = runtime.start_run("Изучи депутатов парламента Армении после 2021", {"budget_pages": 20, "max_depth": 2})

        def fake_fetch(run_id, item_id, url):
            if "sel=factions" in url:
                return {"body": FACTIONS_HTML, "final_url": url}
            return {"body": ROSTER_HTML, "final_url": url}

        with patch.object(workers, "fetch_url_logged", side_effect=fake_fetch):
            trace = runtime.run_steps(started["run_id"], max_steps=1)

        self.assertTrue(trace["ok"])
        item_types = [item["item_type"] for item in trace["work_items"]]
        self.assertEqual(item_types.count("fetch_deputy_profile"), 3)
        self.assertIn("build_deputy_relations", item_types)
        self.assertIn("rebuild_profiles", item_types)
        self.assertEqual(trace["counts"]["done"], 1)
        self.assertTrue(self.latest_path.exists())

    def test_fetch_profile_creates_extract_item(self):
        started = runtime.start_run("Изучи депутатов парламента Армении после 2021", {"budget_pages": 20, "max_depth": 2})

        def fake_fetch(run_id, item_id, url):
            task_db.save_tool_call(run_id, item_id, "fetch_url", {"url": url}, {"url": url, "status": "visited"})
            if "sel=factions" in url:
                return {"body": FACTIONS_HTML, "final_url": url}
            if "ID=1500" in url:
                return {"body": PROFILE_HTML, "final_url": url}
            return {"body": ROSTER_HTML, "final_url": url}

        with patch.object(workers, "fetch_url_logged", side_effect=fake_fetch):
            runtime.run_steps(started["run_id"], max_steps=1)
            trace = runtime.resume_run(started["run_id"], max_steps=1)

        item_types = [item["item_type"] for item in trace["work_items"]]
        self.assertIn("extract_deputy_claims", item_types)
        self.assertGreaterEqual(len(trace["tool_calls"]), 1)

    def test_zero_roster_marks_run_failed_retryable(self):
        started = runtime.start_run("Изучи депутатов парламента Армении после 2021", {"budget_pages": 20, "max_depth": 2})

        def fake_fetch(run_id, item_id, url):
            return {"body": "<html></html>", "final_url": url}

        with patch.object(workers, "fetch_url_logged", side_effect=fake_fetch):
            trace = runtime.run_steps(started["run_id"], max_steps=1)

        self.assertEqual(trace["status"], "failed_retryable")
        self.assertIn("roster parser returned 0 records", " ".join(trace["run"]["failure_explanation"].split("; ")))

    def test_completed_run_cannot_have_waiting_items(self):
        started = runtime.start_run("Изучи депутатов парламента Армении после 2021", {"budget_pages": 20, "max_depth": 2})
        item = task_db.next_item(started["run_id"])
        self.assertIsNotNone(item)
        self._set_work_item_status(item["item_id"], "waiting", "retry me")
        trace = runtime.run_steps(started["run_id"], max_steps=1)
        self.assertEqual(trace["status"], "failed_retryable")
        self.assertEqual(trace["run"].get("current_stage"), "failed_retryable")
        self.assertEqual(trace["counts"].get("waiting", 0), 0)
        self.assertEqual(trace["counts"].get("failed", 0), 1)
        self.assertNotEqual(trace["run"].get("current_stage"), "rebuild_profiles")

    def test_gov_am_fixture_parses_ministers_and_ministries(self):
        parsed = parse_government_members_page(GOV_MEMBERS_HTML, "https://www.gov.am/en/gov-members/")
        self.assertEqual(len(parsed["people"]), 2)
        self.assertEqual(parsed["people"][0]["name"], "Anahit Avanesyan")
        self.assertEqual(parsed["people"][0]["ministry_name"], "Ministry of Health")

    def test_gov_staff_structure_parser_extracts_staff_names(self):
        parsed = parse_prime_minister_staff_structure_page(GOV_STAFF_STRUCTURE_HTML, "https://www.gov.am/en/staff-structure/")
        names = [person["name"] for person in parsed["people"]]
        self.assertIn("Arayik Harutyunyan", names)
        self.assertIn("Armenak Khachatryan", names)
        self.assertIn("Artur Hovsepyan", names)
        self.assertIn("Anahit Stephanyan", names)
        anahit = next(person for person in parsed["people"] if person["name"] == "Anahit Stephanyan")
        self.assertEqual(anahit["department_name"], "Department for Relations with the National Assembly")
        self.assertEqual(anahit["title"], "Head of Department for Relations with the National Assembly")

    def test_official_search_fallback_returns_government_sources(self):
        provider = DeterministicOfficialSearchProvider()
        results = provider.search("Обнови данные по всем нынешним министрам в Армении", max_results=5)
        urls = [item.url for item in results]
        self.assertIn("https://www.gov.am/en/gov-members/", urls)

    def test_source_registry_includes_official_role_history_sources(self):
        sources = load_source_registry_snapshot()
        urls = {str(item.get("url") or "").strip() for item in sources}
        self.assertIn("https://www.primeminister.am", urls)
        self.assertIn("https://www.gov.am", urls)
        self.assertIn("https://www.parliament.am", urls)
        self.assertIn("https://www.arlis.am", urls)
        self.assertIn("https://www.e-register.am/en/", urls)

    def test_claim_extractor_rejects_boilerplate_person_labels(self):
        self.assertFalse(claim_extractor._is_human_name_candidate("The Prime"))  # type: ignore[attr-defined]
        self.assertFalse(claim_extractor._is_human_name_candidate("Historical Overview Former Prime"))  # type: ignore[attr-defined]
        self.assertFalse(claim_extractor._is_human_name_candidate("Government Team Members"))  # type: ignore[attr-defined]
        self.assertTrue(claim_extractor._is_human_name_candidate("Arayik Harutyunyan"))  # type: ignore[attr-defined]

    def test_person_name_extraction_does_not_glue_navigation_fragments(self):
        text = """
        Eng
        Հայ
        Рус
        Fra
        The Prime Minister of the Republic of Armenia
        Arayik Harutyunyan
        Chief of Staff of the Prime Minister
        """
        names = claim_extractor._extract_person_names(text, "The Prime Minister of the Republic of Armenia")  # type: ignore[attr-defined]
        self.assertNotIn("Fra Prime", names)
        self.assertIn("Arayik Harutyunyan", names)

    def test_start_run_creates_government_discovery_item(self):
        started = runtime.start_run("Обнови данные по всем нынешним министрам в Армении", {"budget_pages": 20, "max_depth": 2})
        self.assertEqual(started["run_type"], "government_ministers_enrichment")
        trace = task_db.build_research_trace(started["run_id"])
        self.assertEqual(trace["work_items"][0]["item_type"], "discover_government_ministers")

    def test_government_discovery_creates_fetch_work_items(self):
        started = runtime.start_run("Обнови данные по всем нынешним министрам в Армении", {"budget_pages": 20, "max_depth": 2})

        def fake_fetch(run_id, item_id, url):
            return {"body": GOV_MEMBERS_HTML, "final_url": url}

        with patch.object(workers, "fetch_url_logged", side_effect=fake_fetch):
            trace = runtime.run_steps(started["run_id"], max_steps=1)

        item_types = [item["item_type"] for item in trace["work_items"]]
        self.assertEqual(item_types.count("fetch_minister_profile"), 2)
        self.assertIn("build_government_relations", item_types)
        self.assertIn("rebuild_profiles", item_types)

    def test_minister_workflow_creates_claims_and_link_item(self):
        started = runtime.start_run("Обнови данные по всем нынешним министрам в Армении", {"budget_pages": 20, "max_depth": 2})

        def fake_fetch(run_id, item_id, url):
            task_db.save_tool_call(run_id, item_id, "fetch_url", {"url": url}, {"url": url, "status": "visited"})
            if "gov-members/" in url and url.rstrip("/").endswith("gov-members"):
                return {"body": GOV_MEMBERS_HTML, "final_url": url}
            return {"body": MINISTER_PROFILE_HTML, "final_url": url}

        with patch.object(workers, "fetch_url_logged", side_effect=fake_fetch):
            runtime.run_steps(started["run_id"], max_steps=1)
            runtime.resume_run(started["run_id"], max_steps=1)
            trace = runtime.resume_run(started["run_id"], max_steps=1)

        item_types = [item["item_type"] for item in trace["work_items"]]
        self.assertIn("link_minister_to_ministry", item_types)
        self.assertGreaterEqual(len(trace["trace"]["extracted_claims"]), 1)

    def test_minister_workflow_records_search_and_model_calls(self):
        started = runtime.start_run("Обнови данные по всем нынешним министрам в Армении", {"budget_pages": 20, "max_depth": 2})

        def fake_fetch(run_id, item_id, url):
            task_db.save_tool_call(run_id, item_id, "fetch_url", {"url": url}, {"url": url, "status": "visited"})
            if "gov-members/" in url and url.rstrip("/").endswith("gov-members"):
                return {"body": GOV_MEMBERS_HTML, "final_url": url}
            return {"body": MINISTER_PROFILE_HTML, "final_url": url}

        fake_model = (
            {
                "claims": [
                    {
                        "claim_type": "role",
                        "subject_name": "Anahit Avanesyan",
                        "relation_type": "holds_office_in",
                        "statement": "Anahit Avanesyan is Minister of Health.",
                        "confidence": 0.81,
                        "evidence_quote": "Anahit Avanesyan serves as Minister of Health.",
                        "source_url": "https://www.gov.am/en/gov-members/1029/",
                    }
                ],
                "profile_updates": [
                    {
                        "entity_name": "Anahit Avanesyan",
                        "overview": "Anahit Avanesyan is Minister of Health.",
                        "biography_or_history": ["Minister of Health"],
                        "current_roles_or_functions": ["Minister of Health"],
                        "timeline_items": [{"date": "current", "title": "Minister of Health"}],
                    }
                ],
            },
            {"ok": True, "provider": "ollama", "model": "gemma4:e4b", "raw": "{\"ok\":true}"},
        )

        with patch.object(workers, "fetch_url_logged", side_effect=fake_fetch):
            with patch("scripts.living_graph.research_tools.claim_extractor.call_parser_model", return_value=fake_model):
                runtime.run_steps(started["run_id"], max_steps=4)
                trace = runtime.latest_trace()

        self.assertGreaterEqual(int(trace["run"].get("search_queries", 0)), 1)
        self.assertGreaterEqual(int(trace["run"].get("model_calls", 0)), 1)
        self.assertIn("brave_html", str(trace["run"].get("search_provider") or ""))
        self.assertIn("search_hits", trace["trace"])
        self.assertGreaterEqual(len(trace["trace"].get("search_hits", [])), 1)
        self.assertFalse(trace["run"].get("limited_search_mode"))
        self.assertGreaterEqual(int(trace["run"].get("event_count", 0)), 1)
        self.assertGreaterEqual(int(trace["run"].get("claims_logged", 0)), 1)
        self.assertTrue(self.claims_log.exists())
        self.assertGreaterEqual(len(self.claims_log.read_text(encoding="utf-8").strip().splitlines()), 1)

    def test_role_title_person_vertex_is_rejected(self):
        with patch.object(workers, "load_graph", return_value={"vertices": [], "edges": [], "claims": [], "sources": [], "evidence": []}):
            diff = workers.propose_graph_update(
                "run-1",
                "item-1",
                {
                    "entity": {
                        "id": "person-chief-of-staff-of-the-prime-minister",
                        "label": "Chief of Staff of the Prime Minister",
                        "name": "Chief of Staff of the Prime Minister",
                        "category": "person",
                        "summary": "Office title",
                    },
                    "claims": [],
                    "profile_update": {},
                    "source_url": "https://example.com",
                    "evidence_quote": "example",
                    "updated_at": "2026-05-06T00:00:00Z",
                },
            )
        self.assertEqual(diff["rejected"][0]["reason"], "office_title_person_label")

    def test_role_history_without_office_holder_claims_does_not_complete_normally(self):
        started = runtime.start_run("Найди всех руководителей аппарата премьер-министра Никола Пашиняна за период 2018-2026 и дай их биографии", {"budget_pages": 20, "max_depth": 2})
        task_db.update_run_status(
            started["run_id"],
            "running",
            summary_json={
                "role_history_record_count": 2,
                "profile_pages_fetched": 2,
                "claims_extracted": 2,
                "graph_updates": 1,
                "role_history_office_holder_claims": 0,
            },
        )
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute("UPDATE work_items SET status = 'done' WHERE run_id = ?", (started["run_id"],))
            conn.commit()
        runtime._finalize_run(started["run_id"])  # type: ignore[attr-defined]
        final = task_db.build_research_trace(started["run_id"])
        self.assertIn(final["status"], {"completed_no_changes", "failed_retryable"})
        self.assertNotEqual(final["status"], "completed")

    def test_canonical_person_resolution_merges_transliterations(self):
        alias_index = {"people": {"araik harutyunyan": "person-arayik-harutyunyan", "arayik harutyunyan": "person-arayik-harutyunyan"}}
        self.assertEqual(resolve_entity("Araik Harutyunyan", alias_index, bucket="people"), "person-arayik-harutyunyan")
        self.assertEqual(resolve_entity("Arayik Harutyunyan", alias_index, bucket="people"), "person-arayik-harutyunyan")
        self.assertNotEqual(canonical_person_key("Araik Harutyunyan"), "")

    def test_entity_resolution_refuses_person_office_merge(self):
        alias_index = {
            "people": {"prime minister of armenia": "office-prime-minister-armenia"},
            "orgs": {},
            "places": {},
            "_types": {"office-prime-minister-armenia": "OFFICE"},
        }
        self.assertIsNone(resolve_entity("Prime Minister of Armenia", alias_index, bucket="people", entity_type="PERSON"))
        self.assertEqual(resolve_entity("Prime Minister of Armenia", alias_index, bucket="people", entity_type="OFFICE"), "office-prime-minister-armenia")
        self.assertFalse(entity_types_compatible("PERSON", "OFFICE"))

    def test_entity_registry_records_typed_aliases(self):
        registry = build_entity_registry(
            {
                "entities": [
                    {
                        "id": "person-nikol-pashinyan",
                        "name": "Nikol Pashinyan",
                        "category": "person",
                        "aliases": ["Никол Пашинян"],
                    },
                    {
                        "id": "office-prime-minister-armenia",
                        "name": "Prime Minister of Armenia",
                        "category": "office",
                        "aliases": ["Премьер-министр Армении"],
                    },
                ]
            }
        )
        by_id = {item["id"]: item for item in registry["entities"]}
        self.assertEqual(by_id["person-nikol-pashinyan"]["entity_type"], "PERSON")
        self.assertEqual(by_id["office-prime-minister-armenia"]["entity_type"], "OFFICE")
        self.assertEqual(registry["indexes"]["alias_to_entity_id"]["nikol pashinyan"], "person-nikol-pashinyan")

    def test_entity_alias_index_uses_entity_registry(self):
        graph = {
            "entities": [],
            "vertices": [],
        }
        registry = build_entity_registry(
            {
                "entities": [
                    {
                        "id": "person-nikol-pashinyan",
                        "name": "Nikol Pashinyan",
                        "category": "person",
                        "aliases": ["Նիկոլ Փաշինյան", "Никол Пашинян"],
                    },
                    {
                        "id": "office-prime-minister-armenia",
                        "name": "Prime Minister of Armenia",
                        "category": "office",
                        "aliases": ["ՀՀ վարչապետ"],
                    },
                ]
            }
        )
        with patch("scripts.pipeline_common.load_entity_registry", return_value=registry):
            alias_index = load_entity_alias_index(graph)
        self.assertEqual(resolve_entity("Նիկոլ Փաշինյան", alias_index, bucket="people", entity_type="PERSON"), "person-nikol-pashinyan")
        self.assertEqual(resolve_entity("ՀՀ վարչապետ", alias_index, bucket="orgs", entity_type="OFFICE"), "office-prime-minister-armenia")
        self.assertIsNone(resolve_entity("ՀՀ վարչապետ", alias_index, bucket="people", entity_type="PERSON"))

    def test_claim_records_are_append_only_candidates(self):
        claim_path = Path(self.tempdir.name) / "claims.jsonl"
        first = append_claim_records(
            [
                {
                    "claim_type": "HOLDS_OFFICE",
                    "subject_vertex_id": "person-nikol-pashinyan",
                    "object_vertex_id": "office-prime-minister-armenia",
                    "source_url": "https://www.gov.am/",
                    "evidence_quote": "Prime Minister Nikol Pashinyan",
                }
            ],
            path=claim_path,
        )
        second = append_claim_records([{"claim_type": "MEMBER_OF", "subject_vertex_id": "person-a", "object_vertex_id": "party-b"}], path=claim_path)
        lines = claim_path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(first[0]["status"], "candidate")
        self.assertEqual(second[0]["claim_type"], "MEMBER_OF")
        loaded = load_claim_records(claim_path)
        index = claim_records_index(loaded)
        self.assertEqual(index["count"], 2)
        self.assertEqual(len(index["by_entity"]["person-a"]), 1)
        self.assertEqual(len(index["by_type"]["HOLDS_OFFICE"]), 1)

    def test_biography_fast_path_extracts_candidate_claim(self):
        result = claim_extractor.extract_claims_from_page(
            query="Complete a source-backed biography profile for Artur Hovsepyan.",
            target_name="Artur Hovsepyan",
            source_url="https://example.org/person-d",
            page_title="Artur Hovsepyan biography",
            page_text="Artur Hovsepyan was born in Yerevan and worked in public administration before joining a civic program.",
            source_type="media",
            context={"question_type": "biography_completion", "expected_claim_types": ["biography_fact"]},
        )
        self.assertTrue(result.fallback_used)
        self.assertEqual(result.claims[0]["claim_type"], "biography")
        self.assertEqual(result.claims[0]["subject_name"], "Artur Hovsepyan")
        self.assertEqual(result.model_meta["model"], "biography_fast_path")

    def test_backend_capability_catalog_exposes_long_context_contract(self):
        config = {
                "runtime": {
                    "default_backend_mode": "ollama-native",
                    "ollama_url": "http://127.0.0.1:11434",
                    "ollama_options": {"default_num_ctx": 8192, "long_num_ctx": 65536, "experimental_num_ctx": 131072},
                },
                "backends": {
                    "ollama-native": {"enabled": True, "backend_type": "ollama", "model": "gemma4:e4b"},
                    "longctx-backend": {
                        "enabled": False,
                        "backend_type": "openai-compatible",
                        "native_max_ctx": 131072,
                        "effective_max_ctx": 131072,
                        "supports_kv_compression": True,
                    },
                },
            }
        catalog = model_runtime.backend_capability_catalog(config)
        by_mode = {item["mode"]: item for item in catalog["backends"]}
        self.assertIn("ollama-native", by_mode)
        self.assertIn("longctx-backend", by_mode)
        self.assertFalse(by_mode["ollama-native"]["supports_kv_compression"])
        self.assertTrue(by_mode["longctx-backend"]["supports_kv_compression"])
        resolved = model_runtime.resolve_runtime_backend(required_context=131072, prefer_long_context=True, model_config=config)
        self.assertEqual(resolved["backend"]["mode"], "ollama-native")
        self.assertTrue(resolved["fallback_memory_required"])
        self.assertEqual(resolved["reason"], "long_context_backend_unavailable")

    def test_runtime_graph_path_is_isolated_for_tests(self):
        self.assertEqual(canonical_graph_path(), self.graph_path.resolve())

    def test_canonical_person_display_name_prefers_existing_graph_vertex(self):
        graph = {
            "entities": [
                {"id": "person-arayik-harutyunyan", "name": "Arayik Harutyunyan", "aliases": ["Araik Harutyunyan"]},
            ]
        }
        self.assertEqual(workers._canonical_person_display_name(graph, "Araik Harutyunyan"), "Arayik Harutyunyan")  # type: ignore[attr-defined]

    def test_role_history_trace_exposes_coverage_report(self):
        started = runtime.start_run("Найди всех руководителей аппарата премьер-министра Никола Пашиняна за период 2018-2026 и дай их биографии", {"budget_pages": 20, "max_depth": 2})
        task_db.update_run_status(
            started["run_id"],
            "running",
            summary_json={
                "coverage": {
                    "years_checked": [2018, 2019, 2020],
                    "roles_checked": ["Chief of Staff", "Adviser"],
                    "sources_checked": ["primeminister.am", "gov.am"],
                    "confirmed_claims": 3,
                    "rejected_claims": 1,
                    "unresolved_candidates": 2,
                }
            },
        )
        trace = task_db.build_research_trace(started["run_id"])
        self.assertEqual(trace["run"].get("coverage", {}).get("years_checked"), [2018, 2019, 2020])
        self.assertEqual(trace["run"].get("confirmed_claims"), 3)
        self.assertIn("coverage", trace["trace"])

    def test_role_history_staff_structure_page_produces_office_holder_claims(self):
        started = runtime.start_run("Найди всех руководителей аппарата премьер-министра Никола Пашиняна за период 2018-2026 и дай их биографии", {"budget_pages": 20, "max_depth": 2})

        def fake_search(run_id, item_id, query, *, domains=None, max_results=10):
            return [
                {
                    "url": "https://www.gov.am/en/staff-structure/",
                    "title": "Office of the Prime Minister staff structure",
                    "snippet": "Chief of Staff, advisers, assistants, and departments",
                    "source": "deterministic_official",
                }
            ]

        def fake_fetch(run_id, item_id, url):
            body = GOV_STAFF_STRUCTURE_HTML if "staff-structure" in url else MINISTER_PROFILE_HTML
            return {"body": body, "final_url": url}

        with patch.object(workers, "search_web_logged", side_effect=fake_search):
            with patch.object(workers, "fetch_url_logged", side_effect=fake_fetch):
                with patch("scripts.living_graph.research_tools.claim_extractor.call_parser_model", return_value=({}, {"ok": False, "provider": "deterministic", "model": "rules", "raw": "", "error": "mocked"})):
                    runtime.run_steps(started["run_id"], max_steps=5)
                    trace = runtime.latest_trace()

        self.assertGreaterEqual(int(trace["run"].get("role_history_office_holder_claims", 0)), 1)
        self.assertGreaterEqual(int(trace["run"].get("accepted_graph_changes", 0)), 1)
        processed = [item.get("name", "") for item in trace["trace"].get("processed_entities", [])]
        self.assertIn("Arayik Harutyunyan", processed)
        self.assertIn("Anahit Stephanyan", processed)

    def test_accepted_graph_changes_match_graph_diff(self):
        started = runtime.start_run("Обнови данные по всем нынешним министрам в Армении", {"budget_pages": 20, "max_depth": 2})

        def fake_fetch(run_id, item_id, url):
            if "gov-members" in url:
                return {"body": GOV_MEMBERS_HTML, "final_url": url}
            return {"body": MINISTER_PROFILE_HTML, "final_url": url}

        with patch.object(workers, "fetch_url_logged", side_effect=fake_fetch):
            runtime.run_steps(started["run_id"], max_steps=3)
        trace = task_db.build_research_trace(started["run_id"])
        diff = trace["trace"]["graph_diff"]
        actual = len(diff["new_nodes"]) + len(diff["updated_nodes"]) + len(diff["new_edges"]) + len(diff["updated_edges"])
        self.assertEqual(trace["run"]["accepted_graph_changes"], actual)

    def test_ui_payload_marks_limited_search_mode(self):
        started = runtime.start_run("Обнови данные по всем нынешним министрам в Армении", {"budget_pages": 20, "max_depth": 2})
        trace = task_db.build_research_trace(started["run_id"])
        self.assertIn("limited_search_mode", trace["run"])
        self.assertIn("limited_search_message", trace["run"])
        self.assertIsInstance(trace["run"]["limited_search_mode"], bool)

    def test_research_trace_includes_live_events(self):
        started = runtime.start_run("Обнови данные по всем нынешним министрам в Армении", {"budget_pages": 20, "max_depth": 2})

        def fake_fetch(run_id, item_id, url):
            if "gov-members" in url:
                return {"body": GOV_MEMBERS_HTML, "final_url": url}
            return {"body": MINISTER_PROFILE_HTML, "final_url": url}

        with patch.object(workers, "fetch_url_logged", side_effect=fake_fetch):
            runtime.run_steps(started["run_id"], max_steps=2)
            trace = task_db.build_research_trace(started["run_id"])

        self.assertGreaterEqual(len(trace["trace"].get("events", [])), 1)
        self.assertGreaterEqual(trace["run"].get("event_count", 0), 1)

    def test_resume_processes_extract_step_and_persists_trace(self):
        started = runtime.start_run("Изучи депутатов парламента Армении после 2021", {"budget_pages": 20, "max_depth": 2})

        def fake_fetch(run_id, item_id, url):
            task_db.save_tool_call(run_id, item_id, "fetch_url", {"url": url}, {"url": url, "status": "visited"})
            if "sel=factions" in url:
                return {"body": FACTIONS_HTML, "final_url": url}
            if "ID=1500" in url:
                return {"body": PROFILE_HTML, "final_url": url}
            return {"body": ROSTER_HTML, "final_url": url}

        fake_diff = {"new_node_ids": ["person-alen-simonyan"], "updated_node_ids": [], "new_edge_ids": ["edge-1"], "updated_edge_ids": [], "rejected": []}
        with patch.object(workers, "fetch_url_logged", side_effect=fake_fetch):
            runtime.run_steps(started["run_id"], max_steps=1)
            runtime.resume_run(started["run_id"], max_steps=1)
            with patch.object(workers, "propose_graph_update", return_value=fake_diff):
                with patch.object(workers, "get_entity_card", return_value={}):
                    with patch.object(workers, "resolve_entity_logged", return_value={}):
                        with patch.object(workers, "load_graph", return_value={"entities": [], "claims": [], "relations": []}):
                            trace = runtime.resume_run(started["run_id"], max_steps=1)

        self.assertTrue(trace["ok"])
        self.assertGreaterEqual(len(trace["trace"]["extracted_claims"]), 1)
        self.assertTrue(trace["trace"]["graph_diff"]["new_nodes"] or trace["trace"]["accepted_changes"])
        self.assertTrue(self.latest_path.exists())

    def test_question_generator_prioritizes_person_office_and_company_gaps(self):
        graph = {
            "entities": [
                {"id": "person-nikol-pashinyan", "name": "Nikol Pashinyan", "category": "person", "profile": {}},
                {"id": "office-prime-minister-armenia", "name": "Prime Minister of Armenia", "category": "office"},
                {"id": "company-x", "name": "Company X LLC", "category": "company"},
                {"id": "person-site-map", "name": "Site Map", "category": "person"},
            ],
            "relations": [],
            "claims": [],
        }
        questions = generate_research_questions(graph, limit=20)
        qtypes = {question["question_type"] for question in questions}
        self.assertIn("biography_completion", qtypes)
        self.assertIn("office_tenure_completion", qtypes)
        self.assertIn("company_ownership_control", qtypes)
        self.assertTrue(all(question["status"] == "queued" for question in questions))
        self.assertTrue(any("Prime Minister of Armenia" in question["question"] for question in questions))
        self.assertFalse(any("Site Map" in question["question"] for question in questions))

    def test_question_generator_rechecks_disputed_claims(self):
        graph = {
            "entities": [
                {"id": "person-a", "name": "Person A", "category": "person"},
                {"id": "party-b", "name": "Party B", "category": "party"},
            ],
            "claims": [
                {
                    "id": "claim-1",
                    "subject_vertex_id": "person-a",
                    "object_vertex_id": "party-b",
                    "claim_type": "MEMBER_OF",
                    "statement": "Person A is reportedly affiliated with Party B",
                    "status": "disputed",
                }
            ],
            "relations": [],
        }
        questions = generate_research_questions(graph, limit=20)
        disputed = [question for question in questions if question["question_type"] == "contradiction_resolution"]
        self.assertEqual(len(disputed), 1)
        self.assertEqual(disputed[0]["target_entities"], ["person-a", "party-b"])

    def test_subgraph_builder_includes_claims_evidence_and_questions(self):
        graph = {
            "entities": [
                {"id": "person-a", "name": "Person A", "category": "person", "profile": {}},
                {"id": "office-b", "name": "Office B", "category": "office"},
            ],
            "relations": [
                {
                    "id": "edge-1",
                    "from": "person-a",
                    "to": "office-b",
                    "type": "holds_office_in",
                    "layer": "canonical",
                    "status": "confirmed",
                    "claim_ids": ["claim-1"],
                    "evidence_ids": ["evidence-1"],
                    "source_ids": ["source-1"],
                }
            ],
            "claims": [
                {
                    "id": "claim-1",
                    "subject_vertex_id": "person-a",
                    "object_vertex_id": "office-b",
                    "claim_type": "HOLDS_OFFICE",
                    "statement": "Person A holds Office B",
                    "status": "confirmed",
                    "evidence_ids": ["evidence-1"],
                }
            ],
            "evidence": [{"id": "evidence-1", "quote": "Person A holds Office B"}],
        }
        subgraph = build_subgraph(graph, "person-a")
        self.assertEqual(subgraph["status"], "ready")
        self.assertEqual(len(subgraph["nodes"]), 2)
        self.assertEqual(len(subgraph["canonical_edges"]), 1)
        self.assertEqual(len(subgraph["active_claims"]), 1)
        self.assertEqual(len(subgraph["evidence"]), 1)
        self.assertIn("biography", subgraph["missing_fields"])

    def test_national_graph_cycle_report_has_operator_counters(self):
        graph = {
            "entities": [{"id": "person-a", "name": "Person A", "category": "person", "profile": {}}],
            "relations": [],
            "claims": [
                {"id": "claim-ok", "status": "confirmed"},
                {"id": "claim-bad", "status": "rejected"},
                {"id": "claim-disputed", "status": "disputed"},
                {"id": "claim-stale", "status": "stale"},
            ],
            "sources": [{"id": "source-1"}],
            "evidence": [{"id": "evidence-1"}],
        }
        questions = generate_research_questions(graph, limit=10)
        subgraphs = [build_subgraph(graph, "person-a")]
        report = national_graph_cycle.build_operator_report(graph, questions=questions, subgraphs=subgraphs, dry_run=True)
        self.assertEqual(report["sources_checked"], 1)
        self.assertEqual(report["claims_extracted"], 4)
        self.assertEqual(report["claims_admitted"], 1)
        self.assertEqual(report["claims_rejected"], 1)
        self.assertEqual(report["disputed_claims_stored"], 1)
        self.assertEqual(report["stale_claims_detected"], 1)
        self.assertGreaterEqual(report["questions_generated"], 1)
        self.assertEqual(report["subgraphs_updated"], 1)

    def test_national_graph_cycle_preserves_existing_queue_state(self):
        merged = national_graph_cycle.preserve_queue_state(
            [
                {
                    "id": "q-1",
                    "question": "Updated question text",
                    "status": "queued",
                    "priority_score": 0.9,
                }
            ],
            [
                {
                    "id": "q-1",
                    "status": "retryable_failed",
                    "run_id": "run-old",
                    "attempt_count": 2,
                    "max_attempts": 4,
                    "updated_at": "2026-05-30T00:00:00+00:00",
                }
            ],
        )
        self.assertEqual(merged[0]["question"], "Updated question text")
        self.assertEqual(merged[0]["status"], "retryable_failed")
        self.assertEqual(merged[0]["run_id"], "run-old")
        self.assertEqual(merged[0]["attempt_count"], 2)
        self.assertEqual(merged[0]["max_attempts"], 4)

    def test_research_queue_marks_question_running_and_builds_payload(self):
        queue_path = Path(self.tempdir.name) / "queue.jsonl"
        question = {
            "id": "q-1",
            "question": "Complete a source-backed biography profile for Person A.",
            "question_type": "biography_completion",
            "target_entities": ["person-a"],
            "expected_claim_types": ["biography_fact"],
            "suggested_source_types": ["official", "media"],
            "priority_score": 0.9,
            "budget_estimate": {"pages": 7, "max_depth": 2},
            "search_queries": {"en": ["Person A biography Armenia"], "ru": ["Person A биография Армения"]},
            "status": "queued",
            "created_at": "2026-05-30T00:00:00+00:00",
        }
        queue_path.write_text(json.dumps(question, ensure_ascii=False) + "\n", encoding="utf-8")
        loaded = load_question_queue(queue_path)
        self.assertEqual(next_queued_question(loaded)["id"], "q-1")
        query, payload = question_to_run_payload(question)
        self.assertIn("Person A", query)
        self.assertEqual(payload["question_id"], "q-1")
        self.assertEqual(payload["target_entities"], ["person-a"])
        self.assertEqual(payload["budget_pages"], 7)
        updated = mark_question_status("q-1", "running", run_id="run-1", path=queue_path)
        self.assertEqual(updated["status"], "running")
        self.assertEqual(updated["run_id"], "run-1")
        attempted = mark_question_attempt("q-1", run_id="run-2", path=queue_path)
        self.assertEqual(attempted["attempt_count"], 1)
        self.assertEqual(attempted["run_id"], "run-2")

    def test_research_queue_retries_retryable_until_attempt_limit(self):
        rows = [
            {
                "id": "q-retry",
                "question": "Retry me",
                "status": "retryable_failed",
                "priority_score": 0.9,
                "attempt_count": 1,
                "max_attempts": 3,
            },
            {
                "id": "q-terminal",
                "question": "Do not retry me",
                "status": "retryable_failed",
                "priority_score": 1.0,
                "attempt_count": 3,
                "max_attempts": 3,
            },
        ]
        self.assertEqual(next_queued_question(rows)["id"], "q-retry")

    def test_research_queue_can_advance_runtime_steps(self):
        queue_path = Path(self.tempdir.name) / "queue.jsonl"
        question = {
            "id": "q-2",
            "question": "Complete a source-backed biography profile for Person B.",
            "question_type": "biography_completion",
            "target_entities": ["person-b"],
            "priority_score": 0.8,
            "budget_estimate": {"pages": 3, "max_depth": 1},
            "status": "queued",
            "created_at": "2026-05-30T00:00:00+00:00",
        }
        queue_path.write_text(json.dumps(question, ensure_ascii=False) + "\n", encoding="utf-8")

        def fake_start_run(query, payload):
            self.assertEqual(payload["question_id"], "q-2")
            return {"run_id": "run-2", "run_type": "generic_topic_research"}

        with patch.object(runtime, "start_run", side_effect=fake_start_run):
            with patch.object(runtime, "run_steps", return_value={"status": "failed_retryable"}):
                receipt = start_next_question_run(queue_path=queue_path, run_steps=1)

        self.assertEqual(receipt["status"], "advanced")
        self.assertEqual(receipt["question_status"], "retryable_failed")
        loaded = load_question_queue(queue_path)
        self.assertEqual(loaded[0]["status"], "retryable_failed")
        self.assertEqual(loaded[0]["attempt_count"], 1)

    def test_research_queue_marks_failed_after_attempt_limit(self):
        queue_path = Path(self.tempdir.name) / "queue.jsonl"
        question = {
            "id": "q-3",
            "question": "Complete a source-backed biography profile for Person C.",
            "question_type": "biography_completion",
            "target_entities": ["person-c"],
            "priority_score": 0.8,
            "budget_estimate": {"pages": 3, "max_depth": 1},
            "status": "retryable_failed",
            "attempt_count": 2,
            "max_attempts": 3,
            "created_at": "2026-05-30T00:00:00+00:00",
        }
        queue_path.write_text(json.dumps(question, ensure_ascii=False) + "\n", encoding="utf-8")

        with patch.object(runtime, "start_run", return_value={"run_id": "run-3", "run_type": "generic_topic_research"}):
            with patch.object(runtime, "run_steps", return_value={"status": "failed_retryable"}):
                receipt = start_next_question_run(queue_path=queue_path, run_steps=1)

        self.assertEqual(receipt["question_status"], "failed")
        loaded = load_question_queue(queue_path)
        self.assertEqual(loaded[0]["attempt_count"], 3)
        self.assertEqual(loaded[0]["status"], "failed")

    def test_generic_research_uses_queue_seed_queries_and_budget(self):
        started = runtime.start_run(
            "Complete a source-backed biography profile for Person Doe.",
            {
                "budget_pages": 2,
                "max_depth": 1,
                "question_id": "q-seed",
                "question_type": "biography_completion",
                "target_entities": ["person-d"],
                "expected_claim_types": ["biography_fact"],
                "suggested_source_types": ["official", "media"],
                "seed_queries": ["Person Doe biography Armenia", "Person Doe պաշտոն կենսագրություն"],
            },
        )

        searched_queries: list[str] = []

        def fake_search(run_id, item_id, query, *, domains=None, max_results=10):
            searched_queries.append(query)
            if query.startswith("Complete a source-backed"):
                return []
            return [
                {"url": f"https://example.org/{len(searched_queries)}", "title": f"Source {len(searched_queries)}", "snippet": "Person Doe profile"},
                {"url": "https://example.org/duplicate", "title": "Duplicate", "snippet": "duplicate"},
            ]

        def fake_fetch(run_id, item_id, url):
            return {"body": "<html><title>Profile</title><body>Person Doe served in public office.</body></html>", "final_url": url, "content_type": "text/html"}

        def fake_extract(run_id, item_id, **kwargs):
            self.assertEqual(kwargs["context"]["question_id"], "q-seed")
            self.assertEqual(kwargs["context"]["expected_claim_types"], ["biography_fact"])
            self.assertIn(kwargs["context"]["planned_query"], searched_queries)
            self.assertEqual(kwargs["target_name"], "Person Doe")
            return {"claims": [{"statement": "Person Doe served in public office.", "source_url": kwargs["source_url"]}]}

        with patch.object(workers, "search_web_logged", side_effect=fake_search):
            with patch.object(workers, "fetch_url_logged", side_effect=fake_fetch):
                with patch.object(workers, "extract_claims_logged", side_effect=fake_extract):
                    trace = runtime.run_steps(started["run_id"], max_steps=1)

        self.assertTrue(trace["ok"])
        self.assertGreaterEqual(len(searched_queries), 1)
        self.assertIn("Person Doe biography Armenia", searched_queries)
        artifacts = task_db.list_artifacts(started["run_id"])
        plans = [row["payload_json"] for row in artifacts if row["artifact_type"] == "research_question_plan"]
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0]["question_id"], "q-seed")
        self.assertEqual(plans[0]["budget_pages"], 2)
        self.assertIn("Person Doe պաշտոն կենսագրություն", plans[0]["query_plan"])

    def test_generic_research_with_sources_but_no_claims_completes_no_changes(self):
        started = runtime.start_run(
            "Complete a source-backed biography profile for Person Empty.",
            {"budget_pages": 1, "max_depth": 1, "seed_queries": ["Person Empty biography Armenia"]},
        )

        with patch.object(workers, "search_web_logged", return_value=[{"url": "https://example.org/empty", "title": "Empty profile"}]):
            with patch.object(workers, "fetch_url_logged", return_value={"body": "<html><body>Navigation only</body></html>", "final_url": "https://example.org/empty", "content_type": "text/html"}):
                with patch.object(workers, "extract_claims_logged", return_value={"claims": []}):
                    trace = runtime.run_steps(started["run_id"], max_steps=1)

        self.assertEqual(trace["status"], "completed_no_changes")
        artifacts = task_db.list_artifacts(started["run_id"])
        rejected = [row["payload_json"] for row in artifacts if row["artifact_type"] == "rejected_change"]
        self.assertEqual(rejected[0]["reason"], "no_extractable_claims")
        self.assertEqual(rejected[0]["accepted_sources"], 1)
        self.assertEqual(rejected[0]["attempted_sources"][0]["url"], "https://example.org/empty")


class FrontendContractTests(unittest.TestCase):
    def test_minister_status_copy_does_not_default_to_completed(self):
        body = Path("web/graph-viewer/app.js").read_text(encoding="utf-8")
        self.assertIn('Research completed: no graph changes admitted.', body)
        self.assertIn('Research failed: retryable.', body)
        self.assertNotIn('response?.run?.failure_explanation || "Research run completed."', body)

    def test_3d_mode_not_forced_to_2d(self):
        body = Path("web/graph-viewer/app.js").read_text(encoding="utf-8")
        match = re.search(r"function setSceneMode\(mode\)\s*\{(?P<body>.*?)\n  \}", body, flags=re.S)
        self.assertIsNotNone(match)
        snippet = match.group("body")
        self.assertIn('mode === "3d" ? "3d" : "2d"', snippet)
        self.assertNotIn('state.sceneMode = "2d";', snippet)
        self.assertIn("initGraph();", snippet)

    def test_index_html_contains_visible_2d_and_3d_controls(self):
        body = Path("web/graph-viewer/index.html").read_text(encoding="utf-8")
        self.assertIn('data-view-mode="2d"', body)
        self.assertIn('data-view-mode="3d"', body)
        self.assertIn("2D Map", body)
        self.assertIn("3D Orbit", body)


if __name__ == "__main__":
    unittest.main()
