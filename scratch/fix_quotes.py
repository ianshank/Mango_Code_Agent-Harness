import pathlib

for f in pathlib.Path('harness/shared/tests').glob('*.py'):
    content = f.read_text('utf-8')
    content = content.replace("patch(\\'harness.", "patch('harness.")
    content = content.replace("patch('harness.shared.governance.pretooluse_guard.destinations\",", "patch(\"harness.shared.governance.pretooluse_guard.destinations\",")
    content = content.replace("patch('harness.shared.governance.remotes.urlsplit\",", "patch(\"harness.shared.governance.remotes.urlsplit\",")
    
    # Just fix all mismatched quotes created by the bad regex:
    # If it sees patch('harness...xxx", it replaces it with patch("harness...xxx"
    import re
    content = re.compile(r"patch\('([^']*)\"").sub(r'patch("\1"', content)
    
    f.write_text(content, 'utf-8')
    print(f'Fixed {f.name}')
