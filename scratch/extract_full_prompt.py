import json

with open(r'C:\Users\Prabhav\.gemini\antigravity-ide\brain\b50d9c13-0bce-446e-b4a1-42cd8a9e8de8\.system_generated\logs\transcript_full.jsonl', encoding='utf-8-sig') as f:
    lines = f.readlines()

with open(r'scratch\full_prompt_0.md', 'w', encoding='utf-8') as out:
    for line in lines:
        if 'USER_INPUT' in line:
            d = json.loads(line)
            if d.get('step_index') == 0:
                out.write(d.get('content', ''))
                break
