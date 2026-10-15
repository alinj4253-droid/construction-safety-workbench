import json

from app.ingest import _sentences, chunk_documents, html_to_text


def test_html_to_text_removes_scripts():
    text = html_to_text("<h1>标题</h1><script>bad()</script><p>安全帽必须佩戴。</p>")
    assert "标题" in text
    assert "安全帽必须佩戴" in text
    assert "bad" not in text


def test_chunk_documents_keeps_source_metadata():
    docs = [{
        "doc_id": "d1", "title": "测试法规", "issuer": "测试部门", "document_no": "T-1",
        "status": "现行", "url": "https://example.com", "text": "安全帽必须佩戴。" * 80,
    }]
    chunks = chunk_documents(docs)
    assert chunks
    assert all(c["doc_id"] == "d1" for c in chunks)
    assert all(c["source_url"] == "https://example.com" for c in chunks)
    assert "安全帽" in chunks[0]["tags"]


def test_long_unpunctuated_text_is_split_by_chunk_size():
    pieces = _sentences("安全帽" * 400)
    assert len(pieces) > 1
    assert all(len(piece) <= 650 for piece in pieces)
