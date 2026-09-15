import os
import shutil
import subprocess

output = subprocess.check_output(['python', 'find_deps.py']).decode('utf-8')
live = []
orphans = []
for line in output.splitlines():
    if line.startswith('LIVE:'):
        live.append(line.replace('LIVE: ', '').strip())
    elif line.startswith('ORPHANED:'):
        orphans.append(line.replace('ORPHANED: ', '').strip())

with open('USAGE_MAP.md', 'w', encoding='utf-8') as f:
    f.write('# Usage Map\n\n')
    f.write('## LIVE — reachable from main.py\n')
    for l in sorted(live):
        rel = os.path.relpath(l, os.getcwd()).replace('\\', '/')
        f.write(f'- {rel}\n')
    f.write('\n## ORPHANED — not imported anywhere reachable from main.py\n')
    for o in sorted(orphans):
        rel = os.path.relpath(o, os.getcwd()).replace('\\', '/')
        f.write(f'- {rel} (Moved to app/_unused_pending_review/)\n')

os.makedirs('app/_unused_pending_review', exist_ok=True)
for o in orphans:
    # Use git mv to move the file
    rel_path = os.path.relpath(o, os.getcwd())
    dest = os.path.join('app', '_unused_pending_review', os.path.basename(o))
    # if duplicate basename, prefix it with directory name
    if os.path.exists(dest):
        dest = os.path.join('app', '_unused_pending_review', rel_path.replace('\\', '_').replace('/', '_'))
    
    print(f'git mv {rel_path} {dest}')
    try:
        subprocess.run(['git', 'mv', rel_path, dest], check=True)
    except subprocess.CalledProcessError:
        print(f"Failed to move {rel_path}")
