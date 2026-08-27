import os

target = r"d:\S3K Technology\Apcotex\R&D Backend\R&D Product Recipe Simulator (1)\backend\app\services\pipeline\extractor_service.py"

with open(target, 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if "logger.info" in line and (
        "Patent:\\n" in line or 
        "Abstract:\\n" in line or 
        "Description:\\n" in line or 
        "Examples:\\n" in line or 
        "Polymerization evidence:\\n" in line or 
        "Structured fields populated:\\n" in line or 
        "Deterministic:\\n" in line or 
        "Missing Evidence:\\n" in line or 
        "LLM:\\n" in line or 
        "Final:\\n" in line or 
        "Reason: " in line or 
        "Selected Evidence:\\n" in line or 
        "LLM Input: " in line or 
        "--- Extraction Subsystem Started" in line
    ):
        new_lines.append(line.replace("logger.info", "logger.debug"))
    else:
        new_lines.append(line)

with open(target, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print("Done extractor_service.py")

target = r"d:\S3K Technology\Apcotex\R&D Backend\R&D Product Recipe Simulator (1)\backend\app\services\pipeline\report_service.py"
with open(target, 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if "logger.info" in line and (
        "REPORT STRUCTURED RESPONSE VALIDATION" in line or
        "Response received:" in line or
        "Title: " in line or
        "Abstract: " in line or
        "Primary patents:" in line or
        "REPORT LLM TELEMETRY" in line or
        "Actual Input Tokens:" in line
    ):
        new_lines.append(line.replace("logger.info", "logger.debug"))
    else:
        new_lines.append(line)

with open(target, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
print("Done report_service.py")
