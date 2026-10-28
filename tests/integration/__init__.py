import os
import sys
from pathlib import Path

# Automatically ensure the parent of `chess_analyzer` is on sys.path AND remove `chess_analyzer`
# itself from sys.path so `chess_analyzer/platform/` never shadows Python stdlib `platform`
# when running `python -m unittest discover -s tests -v` from inside `E:\chess_analyzer`.
_THIS_DIR = Path(__file__).resolve().parent
for _cand in (_THIS_DIR.parent, _THIS_DIR.parent.parent, _THIS_DIR.parent.parent.parent):
    _pkg = _cand / "chess_analyzer"
    if (_pkg / "__init__.py").exists() and (_pkg / "domain").exists():
        for _bad in ("", ".", str(_pkg), os.getcwd()):
            if Path(_bad or ".").resolve() == _pkg.resolve():
                while _bad in sys.path:
                    sys.path.remove(_bad)
        if str(_cand) not in sys.path:
            sys.path.insert(0, str(_cand))
        break
