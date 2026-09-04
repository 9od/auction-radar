"""Recover tracked listings from this repository's committed snapshots, oldest first."""
import json
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from auction_model import empty_archive, load_json, merge_archive, write_json


def restore():
    path = 'docs/auction_archive.json'
    archive = empty_archive()
    revisions = subprocess.check_output(['git', 'log', '--reverse', '--format=%H', '--', 'docs/auction_data.json'], text=True).splitlines()
    for rev in revisions:
        raw = subprocess.check_output(['git', 'show', f'{rev}:docs/auction_data.json'], text=True)
        try:
            snapshot = json.loads(raw)
        except json.JSONDecodeError:
            print(f'Skip invalid historical JSON: {rev}', file=sys.stderr)
            continue
        archive = merge_archive(archive, snapshot.get('items', []), snapshot.get('수집일시'))
    # Existing confirmed results take precedence over reconstructed listing history.
    existing = load_json(path, empty_archive())
    for record in existing.get('items', []):
        archive = merge_archive(archive, [record], record.get('최종확인'))
        restored = next(i for i in archive['items'] if i['id'] == record['id'])
        for event in record.get('이력', []):
            if event not in restored['이력']:
                restored['이력'].append(event)
    write_json(path, archive)
    print(f'Restored {len(archive["items"])} lots from {len(revisions)} snapshots')


if __name__ == '__main__':
    restore()
