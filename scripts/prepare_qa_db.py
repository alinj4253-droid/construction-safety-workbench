import sqlite3
from pathlib import Path
root=Path(__file__).resolve().parents[1]
with sqlite3.connect(root/'backend/data/app.db') as src,sqlite3.connect(root/'backend/data/qa.db') as dst:src.backup(dst)
print('isolated QA database prepared')
