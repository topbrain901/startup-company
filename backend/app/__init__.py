"""Application module."""

import importlib.util
import sys
from pathlib import Path

# The collector package (startup_scraper) lives at the repository root. Make it importable when
# the API is started from inside backend/ (e.g. `uvicorn app.main:app`), not only from the root.
if importlib.util.find_spec("startup_scraper") is None:
    sys.path.append(str(Path(__file__).resolve().parents[2]))
