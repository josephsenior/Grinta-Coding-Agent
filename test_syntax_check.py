"""Quick syntax/import check for listen_socket.py changes."""
import sys

try:
    import ast
    with open("backend/api/listen_socket.py", "r") as f:
        source = f.read()
    tree = ast.parse(source)
    sys.stderr.write("AST parse: OK\n")
    sys.stderr.write(f"Top-level statements: {len(tree.body)}\n")
    # Check imports
    imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
    missing_settings = any(
        (isinstance(n, ast.ImportFrom) and n.module == "backend.api.types" and
         any(alias.name == "MissingSettingsError" for alias in n.names))
        for n in imports
    )
    sys.stderr.write(f"MissingSettingsError import found: {missing_settings}\n")
except SyntaxError as e:
    sys.stderr.write(f"SYNTAX ERROR: {e}\n")
    sys.exit(1)
except Exception as e:
    sys.stderr.write(f"ERROR: {e}\n")
    sys.exit(1)
