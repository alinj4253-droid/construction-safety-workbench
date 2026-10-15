from app.graph import build_graph, extract_entities


def test_rule_graph_extracts_safety_entities():
    entities, relations = extract_entities("进入施工现场必须佩戴安全帽，重大事故隐患需要整改。")
    assert any(e["name"] == "安全帽" for e in entities)
    assert any(r["relation"] == "应佩戴" for r in relations)


def test_graph_keeps_source_chunk():
    graph = build_graph([{"chunk_id": "c1", "text": "施工现场应佩戴安全帽。"}])
    assert graph["entities"]
    assert all("c1" in e["source_chunks"] for e in graph["entities"])
