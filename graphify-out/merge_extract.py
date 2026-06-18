import json
from pathlib import Path

ast = json.loads(Path('graphify-out/.graphify_ast.json').read_text(encoding='utf-8'))
Path('graphify-out/.graphify_extract.json').write_text(json.dumps(ast, indent=2, ensure_ascii=False), encoding='utf-8')
print(f"Created extract.json: {len(ast['nodes'])} nodes, {len(ast['edges'])} edges")
