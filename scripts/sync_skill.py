"""Copy tools/*.py into skill/groundtruth/scripts/ so the skill also works on its own."""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = ("gt.py", "agent_trace.py", "viz.py")

if __name__ == "__main__":
    dst = ROOT / "skill" / "groundtruth" / "scripts"
    dst.mkdir(parents=True, exist_ok=True)
    for f in FILES:
        shutil.copy2(ROOT / "tools" / f, dst / f)
        print(f"synced {f}")
