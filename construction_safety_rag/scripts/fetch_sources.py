from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ingest import fetch_sources


if __name__ == "__main__":
    results = fetch_sources()
    print(f"抓取完成：{sum(1 for item in results if item.get('downloaded'))}/{len(results)} 个来源")
