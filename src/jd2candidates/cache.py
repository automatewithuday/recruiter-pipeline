"""Per-run JSON cache: runs/<slug>/<stage>.json."""
import json
from pathlib import Path


class RunDir:
    def __init__(self, slug: str, root: Path | str = "runs"):
        self.path = Path(root) / slug
        self.path.mkdir(parents=True, exist_ok=True)

    def _f(self, stage: str) -> Path:
        return self.path / f"{stage}.json"

    def read(self, stage: str):
        f = self._f(stage)
        return json.loads(f.read_text()) if f.exists() else None

    def write(self, stage: str, data) -> None:
        self._f(stage).write_text(json.dumps(data, indent=1, ensure_ascii=False))
