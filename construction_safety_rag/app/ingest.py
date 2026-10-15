from __future__ import annotations

import hashlib
import html
import json
import re
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, List

from .config import CHUNK_OVERLAP, CHUNK_SIZE, CLEAN, RAW, SOURCE_CATALOG
from .models import Chunk


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self.skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self.skip:
            self.skip -= 1

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)


def html_to_text(raw: str) -> str:
    parser = _TextParser()
    parser.feed(raw)
    text = html.unescape("\n".join(parser.parts))
    text = re.sub(r"[ \t\r]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def fetch_sources() -> list[dict]:
    catalog = json.loads(SOURCE_CATALOG.read_text(encoding="utf-8"))
    results = []
    for item in catalog:
        target = RAW / item["filename"]
        url = item["url"]
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "construction-safety-rag/1.0"})
            with urllib.request.urlopen(request, timeout=45) as response:
                payload = response.read()
            if target.suffix.lower() == ".pdf" and not payload.startswith(b"%PDF"):
                if target.exists():
                    target.unlink()
                raise ValueError("响应不是有效 PDF，已保留来源记录并使用网页转载版本")
            target.write_bytes(payload)
            item = dict(item)
            item["downloaded"] = True
            item["local_path"] = str(target)
            print(f"已下载: {item['title']}")
        except Exception as exc:
            item = dict(item)
            item["downloaded"] = False
            item["error"] = str(exc)
            print(f"下载失败（可使用已有 raw 文件继续）: {item['title']} - {exc}")
        results.append(item)
    (RAW / "download_manifest.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return results


def _read_raw(item: dict) -> str:
    path = RAW / item["filename"]
    if not path.exists():
        return ""
    if path.suffix.lower() in {".html", ".htm"}:
        return html_to_text(path.read_text(encoding="utf-8", errors="ignore"))
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
            return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
        except Exception as exc:
            print(f"PDF 解析失败: {path.name} - {exc}")
            return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def clean_sources(catalog: list[dict] | None = None) -> list[dict]:
    catalog = catalog or json.loads(SOURCE_CATALOG.read_text(encoding="utf-8"))
    for old_file in CLEAN.glob("*.txt"):
        old_file.unlink()
    documents = []
    for item in catalog:
        text = _read_raw(item)
        if not text:
            continue
        text = re.sub(r"\s+", " ", text).strip()
        doc_id = hashlib.sha1(item["url"].encode("utf-8")).hexdigest()[:12]
        doc = dict(item)
        doc.update({"doc_id": doc_id, "text": text})
        (CLEAN / f"{doc_id}.txt").write_text(text, encoding="utf-8")
        documents.append(doc)
    (CLEAN / "documents.json").write_text(json.dumps(documents, ensure_ascii=False, indent=2), encoding="utf-8")
    return documents


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？；.!?;])", text)
    sentences: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # PDF/网页中偶尔会出现超长无标点段落，不能让它绕过 CHUNK_SIZE。
        # 先按目标长度拆开，chunk_documents 再统一添加重叠窗口。
        while len(part) > CHUNK_SIZE:
            sentences.append(part[:CHUNK_SIZE])
            part = part[CHUNK_SIZE:]
        if part:
            sentences.append(part)
    return sentences


def _tags(text: str) -> list[str]:
    terms = [
        "安全帽", "安全带", "安全网", "劳动防护用品", "安全防护用品",
        "施工现场人员", "高处作业", "脚手架", "基坑", "起重机械", "临时用电",
        "重大事故隐患", "一般安全隐患", "隐患排查", "整改复查", "专项施工方案",
        "智慧工地", "标准化评价",
    ]
    return [term for term in terms if term in text]


def chunk_documents(documents: list[dict] | None = None) -> list[dict]:
    documents = documents or json.loads((CLEAN / "documents.json").read_text(encoding="utf-8"))
    chunks: list[dict] = []
    for doc in documents:
        sentences = _sentences(doc["text"])
        current: list[str] = []
        size = 0
        index = 0
        for sentence in sentences:
            if current and size + len(sentence) > CHUNK_SIZE:
                text = "".join(current).strip()
                chunks.append(Chunk(
                    chunk_id=f"{doc['doc_id']}_{index:04d}", doc_id=doc["doc_id"],
                    title=doc["title"], issuer=doc["issuer"], document_no=doc.get("document_no", ""),
                    status=doc.get("status", "待核验"), source_url=doc["url"],
                    section=f"片段 {index + 1}", text=text, tags=_tags(text),
                ).to_dict())
                index += 1
                overlap = "".join(current)[-CHUNK_OVERLAP:]
                current = [overlap] if overlap else []
                size = len(overlap)
            current.append(sentence)
            size += len(sentence)
        if current:
            text = "".join(current).strip()
            if len(text) >= 30:
                chunks.append(Chunk(
                    chunk_id=f"{doc['doc_id']}_{index:04d}", doc_id=doc["doc_id"],
                    title=doc["title"], issuer=doc["issuer"], document_no=doc.get("document_no", ""),
                    status=doc.get("status", "待核验"), source_url=doc["url"],
                    section=f"片段 {index + 1}", text=text, tags=_tags(text),
                ).to_dict())
    return chunks
