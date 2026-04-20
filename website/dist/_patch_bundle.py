"""One-shot patcher for the stale dist bundle (Node unavailable)."""
import json, sys, pathlib

sys.stdout.reconfigure(encoding='utf-8')

HERE = pathlib.Path(__file__).parent
BUNDLE = sorted((HERE / 'assets').glob('index-*.js'))[0]
print(f'Patching {BUNDLE.name}')

src = BUNDLE.read_text(encoding='utf-8')
orig = src

patches = json.loads((HERE / '_patches.json').read_text(encoding='utf-8'))

for old, new in patches:
    count = src.count(old)
    if count == 0:
        print(f'[SKIP] no match: {old[:70]!r}')
        continue
    src = src.replace(old, new)
    print(f'[OK]   ({count}x) {old[:60]!r}')

BAD = [
    'engineered preset', 'Engineered preset', 'adversarial', 'Adversarial',
    'home turf', 'tuned to favor', 'Favors:', 'heuristic-favoring',
    'composition bias', ' specialist"', 'specialist!', 'vs specialist',
    '"Specialist"', '"Adversarial',
]
left = []
for pat in BAD:
    if pat in src:
        left.append((pat, src.count(pat)))

if left:
    print('\n[AUDIT] remaining stale terms:')
    for p, c in left:
        print(f'   {c:3d}x  {p!r}')
else:
    print('\n[AUDIT] CLEAN - no stale terms remain')

if src == orig:
    print('\nNo changes written.')
else:
    BUNDLE.write_text(src, encoding='utf-8')
    print(f'\nWrote {len(src)} chars -> {BUNDLE.name}  (was {len(orig)})')
