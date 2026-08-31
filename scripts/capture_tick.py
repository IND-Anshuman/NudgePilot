import json, subprocess, os, re

os.chdir(r"C:\Users\HP\Desktop\NudgePilot-1")

out = subprocess.run(
    [r".venv\Scripts\python.exe", "nudgepilot_cli.py", "auto"],
    capture_output=True, text=True, encoding="utf-8"
)
stdout = out.stdout

# Parse the ACTION LOG
action_log_match = re.search(r"ACTION LOG\n=+\n(.*?)\n=+\nDIGEST", stdout, re.S)
action_log = []
if action_log_match:
    for line in action_log_match.group(1).strip().splitlines():
        line = line.strip()
        if line.startswith("*"):
            line = line[1:].strip()
        if line:
            action_log.append(line)

# Parse the DIGEST section
digest_match = re.search(r"DIGEST\n=+\n(.*?)\n=+\n\[done\]", stdout, re.S)
digest_text = digest_match.group(1).strip() if digest_match else ""

# Parse the summary
summary_match = re.search(r"\[done\] (.*)", stdout)
summary = summary_match.group(1) if summary_match else ""

# Parse drafted subjects and ghosted IDs from the digest text
drafted_subjects = re.findall(r"\* (.+)", digest_text.split("[NUDGES DRAFTED]")[1].split("[")[0]) if "[NUDGES DRAFTED]" in digest_text else []
ghosted_ids = re.findall(r"\* (app_\d+)", digest_text.split("[PIPELINES CLOSED AS GHOSTED]")[1].split("[")[0]) if "[PIPELINES CLOSED AS GHOSTED]" in digest_text else []
classified = re.findall(r"\* (.+): (.+)", digest_text.split("[REPLIES CLASSIFIED]")[1]) if "[REPLIES CLASSIFIED]" in digest_text else []

print(f"action_log: {len(action_log)} lines")
print(f"drafted: {len(drafted_subjects)}, ghosted: {len(ghosted_ids)}, classified: {len(classified)}")

data = {
    "captured_at": "2026-08-31T21:25:00Z",
    "summary": summary,
    "counts": {
        "drafted": len(drafted_subjects),
        "ghosted": len(ghosted_ids),
        "classified": len(classified),
        "errors": 0
    },
    "action_log": action_log,
    "drafted_subjects": drafted_subjects,
    "ghosted_ids": ghosted_ids,
    "classified": [{"kind": k, "subject": s} for k, s in classified],
    "digest_text": digest_text
}

os.makedirs(r"C:\Users\HP\Desktop\NudgePilot-1\frontend\data", exist_ok=True)
with open(r"C:\Users\HP\Desktop\NudgePilot-1\frontend\data\tick-run.json", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

size = os.path.getsize(r"C:\Users\HP\Desktop\NudgePilot-1\frontend\data\tick-run.json")
print(f"WROTE tick-run.json: {size} bytes")