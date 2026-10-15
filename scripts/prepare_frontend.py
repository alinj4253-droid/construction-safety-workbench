import re
from pathlib import Path
root=Path(__file__).resolve().parents[1]
html=(root/'项目终案_系统原型.html').read_text(encoding='utf-8')
html=re.sub(r'<script>[\s\S]*?</script>','<script src="/static/app.js" defer></script>',html)
(root/'frontend/index.html').write_text(html,encoding='utf-8')
