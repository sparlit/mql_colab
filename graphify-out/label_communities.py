import json
from graphify.build import build_from_json
from graphify.cluster import score_all
from graphify.analyze import god_nodes, surprising_connections, suggest_questions
from graphify.report import generate
from pathlib import Path

extraction = json.loads(Path('graphify-out/.graphify_extract.json').read_text(encoding='utf-8'))
detection = json.loads(Path('graphify-out/.graphify_detect.json').read_text(encoding='utf-8'))
analysis = json.loads(Path('graphify-out/.graphify_analysis.json').read_text(encoding='utf-8'))

G = build_from_json(extraction)
communities = {int(k): v for k, v in analysis['communities'].items()}
cohesion = {int(k): v for k, v in analysis['cohesion'].items()}
tokens = {'input': extraction.get('input_tokens', 0), 'output': extraction.get('output_tokens', 0)}

# Community labels based on node content
labels = {}
for cid, nodes in communities.items():
    node_labels = [G.nodes[n].get('label', '') for n in nodes if n in G]
    label_str = ' '.join(node_labels[:5]).lower()
    if 'brain' in label_str:
        labels[cid] = 'Brain Modules'
    elif 'indicator' in label_str or 'ema' in label_str or 'rsi' in label_str:
        labels[cid] = 'Technical Indicators'
    elif 'trade' in label_str or 'order' in label_str:
        labels[cid] = 'Trade Execution'
    elif 'risk' in label_str or 'drawdown' in label_str:
        labels[cid] = 'Risk Management'
    elif 'config' in label_str or 'settings' in label_str:
        labels[cid] = 'Configuration'
    elif 'dashboard' in label_str or 'export' in label_str:
        labels[cid] = 'Dashboard & Export'
    elif 'test' in label_str:
        labels[cid] = 'Test Suite'
    else:
        labels[cid] = f'Community {cid}'

questions = suggest_questions(G, communities, labels)

report = generate(G, communities, cohesion, labels, analysis['gods'], analysis['surprises'], detection, tokens, '.', suggested_questions=questions)
Path('graphify-out/GRAPH_REPORT.md').write_text(report, encoding='utf-8')
Path('graphify-out/.graphify_labels.json').write_text(json.dumps({str(k): v for k, v in labels.items()}, ensure_ascii=False), encoding='utf-8')
print('Report updated with community labels')
print(f'Communities: {len(labels)}')
for cid, label in sorted(labels.items()):
    print(f'  {cid}: {label}')
