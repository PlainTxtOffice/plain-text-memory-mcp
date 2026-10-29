"""Regenerate the taxonomy and bump its version when content changed.

Run from the repo root:

    .venv/Scripts/python.exe scripts/build_taxonomy.py
"""

import json
import sys
from datetime import date
from pathlib import Path

import taxonomy

REPO_ROOT = Path(__file__).resolve().parents[1]
# Ships inside the package; the server's memory://taxonomy resource reads it.
TAXONOMY_PATH = REPO_ROOT / "src" / "plain_text_memory_mcp" / "taxonomy.json"


def main() -> int:
    """Write the taxonomy when it changed and report what happened."""
    document = None
    if TAXONOMY_PATH.exists():
        document = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    content = taxonomy.build_content()
    today = date.today().isoformat()
    updated = taxonomy.update_document(document, content, today)
    if updated is None:
        # update_document returns None only for an existing document.
        assert document is not None
        print(f"taxonomy is current (v{document['taxonomy_version']})")
        return 0
    text = json.dumps(updated, indent=2, ensure_ascii=False) + "\n"
    TAXONOMY_PATH.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote taxonomy v{updated['taxonomy_version']}:")
    for change in updated["changelog"][0]["changes"]:
        print(f"  {change}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
