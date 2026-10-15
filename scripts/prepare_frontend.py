import re
from pathlib import Path
root=Path(__file__).resolve().parents[1]
html=(root/'项目终案_系统原型.html').read_text(encoding='utf-8')
html=re.sub(r'<script>[\s\S]*?</script>','<script src="/static/app.js" defer></script>',html)
html=html.replace('</head>','<link rel="stylesheet" href="/static/app.css"></head>').replace('施工安全管理工作台 · 系统原型','施工安全管理工作台')
(root/'frontend/index.html').write_text(html,encoding='utf-8')
