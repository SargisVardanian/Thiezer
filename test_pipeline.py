import sys
from scripts.run_graph_web import prompt_command
from scripts.graph import load_graph
import json

graph = load_graph()

def test(prompt):
    print(f"=== TESTING: {prompt} ===")
    res = prompt_command(graph, prompt)
    print("Workflow:", res.get("selected_workflow") or res.get("workflow"))
    print("Accepted sources:", len(res.get("accepted_sources", [])))
    print("Graph Diff Nodes:", len(res.get("graph_diff", {}).get("new_nodes", [])) + len(res.get("graph_diff", {}).get("updated_nodes", [])))
    print("Graph Diff Links:", len(res.get("graph_diff", {}).get("new_links", [])) + len(res.get("graph_diff", {}).get("updated_links", [])))
    print("UI Edge Payloads:", len(res.get("ui_edge_payloads", [])))
    print("UI Highlights Nodes:", len(res.get("ui_highlights", {}).get("node_ids", [])))

test("Найди какие сейчас есть министры у нас и какие были в целом за период Пашиняна как премьера. И разбери их по всей глубине.")
test("Найди кто сейчас начальник Генштаба Армении, кто были начальники Генштаба за период Пашиняна как премьера, какие были назначения, снятия и ключевые изменения. Разбери по всей глубине.")
