import os
import ast
from pathlib import Path

def get_imports(filepath):
    imports = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            tree = ast.parse(f.read(), filename=filepath)
    except Exception as e:
        return []
    
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                module = node.module
                # Handle relative imports
                if node.level > 0:
                    # We will approximate this later or just handle absolute imports for app.
                    pass
                else:
                    imports.append(module)
    return imports

def main():
    app_dir = Path('app')
    all_files = list(app_dir.rglob('*.py'))
    
    # Map module path to file path
    module_to_file = {}
    file_to_module = {}
    
    for f in all_files:
        rel_path = f.relative_to(app_dir.parent)
        # convert path to module string
        parts = list(rel_path.parts)
        parts[-1] = parts[-1].replace('.py', '')
        if parts[-1] == '__init__':
            parts = parts[:-1]
        
        module_name = '.'.join(parts)
        module_to_file[module_name] = f
        file_to_module[f] = module_name

    graph = {f: set() for f in all_files}
    
    for f in all_files:
        imps = get_imports(f)
        for imp in imps:
            # We are looking for things in app.
            if imp.startswith('app.'):
                # Try to resolve to a file
                # It could be app.models.user -> app/models/user.py
                # or app.models -> app/models/__init__.py
                # We also need to handle 'from app.models.user import User' where the module is app.models.user
                
                parts = imp.split('.')
                for i in range(len(parts), 0, -1):
                    sub_imp = '.'.join(parts[:i])
                    if sub_imp in module_to_file:
                        graph[f].add(module_to_file[sub_imp])
                        break
                        
    # BFS from app.main
    main_file = Path('app/main.py')
    visited = set()
    queue = [main_file]
    
    # Additional entry points if any? The prompt says "Starting from backend/app/main.py as the entry point".
    
    while queue:
        curr = queue.pop(0)
        if curr not in visited:
            visited.add(curr)
            queue.extend(graph.get(curr, []))
            
    # Include __init__.py files if their directory is reached?
    # Python executes __init__.py when a submodule is imported.
    # We will refine if needed.
    
    for f in all_files:
        if f in visited:
            print(f"LIVE: {f}")
        else:
            print(f"ORPHANED: {f}")

if __name__ == "__main__":
    main()
