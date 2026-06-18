import sys
import json
from graphify.extract import collect_files, extract
from pathlib import Path
from multiprocessing import freeze_support

if __name__ == '__main__':
    freeze_support()
    detect = json.loads(Path('graphify-out/.graphify_detect.json').read_text(encoding='utf-8'))
    code_files = []
    for f in detect.get('files', {}).get('code', []):
        p = Path(f)
        if p.is_dir():
            code_files.extend(collect_files(p))
        else:
            code_files.append(p)

    if code_files:
        result = extract(code_files, cache_root=Path('.'), max_workers=1)
        Path('graphify-out/.graphify_ast.json').write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
        print(f"AST: {len(result['nodes'])} nodes, {len(result['edges'])} edges")
    else:
        Path('graphify-out/.graphify_ast.json').write_text(json.dumps({'nodes':[],'edges':[],'input_tokens':0,'output_tokens':0}, ensure_ascii=False), encoding='utf-8')
        print('No code files - skipping AST extraction')
