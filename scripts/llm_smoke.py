import json
from pathlib import Path
from backend.app.llm import ask_json
result={}
for role in ['main','review']:
    answer,meta=ask_json('这是接口连通检查，请仅返回 {"ready":true}。',{'task':'连接检查'},role,max_tokens=300)
    result[role]={'success':bool(answer and answer.get('ready')),'meta':meta}
Path('artifacts/llm-smoke.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
