import json

with open(r'C:\Users\Prabhav\.gemini\antigravity-ide\brain\b50d9c13-0bce-446e-b4a1-42cd8a9e8de8\.system_generated\logs\transcript_full.jsonl', encoding='utf-8-sig') as f:
    lines = f.readlines()

with open(r'scratch\user_prompts.md', 'w', encoding='utf-8') as out:
    for line in lines:
        if 'USER_INPUT' in line:
            d = json.loads(line)
            content = d.get('content', '')
            out.write(f"--- Step {d.get('step_index')} ---\n")
            out.write(content[:2000] + "\n\n")
