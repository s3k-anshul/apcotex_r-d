import ast
from pathlib import Path
import sys

def get_deps(fpath):
    deps = set()
    try:
        content = fpath.read_text(encoding='utf-8')
        tree = ast.parse(content, filename=str(fpath))
    except Exception:
        return deps
        
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                deps.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                module = node.module
                if node.level > 0:
                    pass
                else:
                    deps.add(module)
                    for alias in node.names:
                        deps.add(f"{module}.{alias.name}")
                        
    # Also find any embedded imports inside functions using AST
    # Wait, ast.walk visits ALL nodes including those inside functions! So the above handles it!
    return deps

def main():
    app_dir = Path('app').resolve()
    all_files = list(app_dir.rglob('*.py'))
    
    valid_modules = {}
    for f in all_files:
        rel = f.relative_to(app_dir.parent)
        parts = list(rel.parts)
        parts[-1] = parts[-1].replace('.py', '')
        if parts[-1] == '__init__':
            parts = parts[:-1]
        
        mod_name = '.'.join(parts)
        valid_modules[mod_name] = f
        
    graph = {f: set() for f in all_files}
    
    for f in all_files:
        raw_deps = get_deps(f)
        for d in raw_deps:
            parts = d.split('.')
            for i in range(len(parts), 0, -1):
                sub = '.'.join(parts[:i])
                if sub in valid_modules:
                    graph[f].add(valid_modules[sub])
                    break

    main_file = app_dir / 'main.py'
    visited = set([main_file])
    queue = [main_file]
    
    while queue:
        curr = queue.pop(0)
        for nxt in graph[curr]:
            if nxt not in visited:
                visited.add(nxt)
                queue.append(nxt)
                
    # Add __init__.py if their module is visited
    for f in list(visited):
        init_file = f.parent / '__init__.py'
        if init_file.exists() and init_file not in visited:
            visited.add(init_file)
            queue.append(init_file)
            
    while queue:
        curr = queue.pop(0)
        for nxt in graph[curr]:
            if nxt not in visited:
                visited.add(nxt)
                queue.append(nxt)
                
    for f in sorted(all_files):
        if f in visited:
            print(f"LIVE: {f}")
        else:
            print(f"ORPHANED: {f}")

if __name__ == "__main__":
    main()
