import runpy
from pathlib import Path


if __name__ == "__main__":
    script = Path(__file__).resolve().parents[2] / "scripts" / "live_checklist.py"
    runpy.run_path(str(script), run_name="__main__")
