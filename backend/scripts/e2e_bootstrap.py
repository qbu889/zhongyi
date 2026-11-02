import os
import sys
from pathlib import Path

# 以 `python scripts/e2e_bootstrap.py` 直接运行时，sys.path[0] 是 scripts/，需补上 backend/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.dev.bootstrap import bootstrap

url = os.environ.get("DATABASE_URL", settings.database_url)
result = bootstrap(url)
print(f"e2e db ready: version={result['version_id']} chunks={result['chunks']}")
