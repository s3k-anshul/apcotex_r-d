import os

target = r"d:\S3K Technology\Apcotex\R&D Backend\R&D Product Recipe Simulator (1)\backend\app\services\pipeline\search_service.py"

with open(target, 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if "logger.info" in line and (
        "Serper Query: " in line or 
        "Endpoint: https://google.serper.dev/patents" in line or 
        "Page: " in line or 
        "Serper API Request -> URL" in line or 
        "HTTP Status: " in line or 
        "Raw Results: " in line or 
        "[DIAGNOSTIC]" in line or 
        "SERPER REQUEST" in line or 
        "---" in line or 
        "Run ID: " in line or 
        "Stage: " in line or 
        "Query: " in line or 
        "Results Returned: " in line or 
        "Credits/Usage if available: " in line or 
        "Latency: " in line or 
        "Status: " in line or 
        "Error: " in line or
        "============================================================" in line
    ):
        new_lines.append(line.replace("logger.info", "logger.debug"))
    else:
        new_lines.append(line)

with open(target, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print("Done search_service.py")
