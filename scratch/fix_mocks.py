import pathlib
import re

for f in pathlib.Path('harness/shared/tests').glob('*.py'):
    content = f.read_text('utf-8')
    new_content = re.sub(
        r'patch\([\"' + r"'" + r']harness\.shared\.(pretooluse_guard|remotes|verify_zero_skips|check_traceability)\.',
        r'patch(\'harness.shared.governance.\1.',
        content
    )
    if new_content != content:
        f.write_text(new_content, 'utf-8')
        print(f'Updated {f.name}')
