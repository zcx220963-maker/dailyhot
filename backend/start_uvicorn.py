"""Helper to launch uvicorn as a detached subprocess.

Run with:
    python start_uvicorn.py
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(HERE, "uvicorn.log")

logf = open(LOG_PATH, "w", encoding="utf-8")

# Ensure child's sys.path can find the `backend` package.
# uvicorn imports server.app -> server.websocket_manager -> backend.report_type
# and the path-injection we added in websocket_manager.py handles it,
# but we also set PYTHONPATH as a belt-and-suspenders measure.
env = os.environ.copy()
env["PYTHONPATH"] = HERE + os.pathsep + env.get("PYTHONPATH", "")

# DETACHED_PROCESS so the child survives if the parent shell exits
CREATE_DETACHED = 0x00000008

proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "server.app:app",
     "--host", "0.0.0.0", "--port", "8000"],
    cwd=HERE,
    env=env,
    stdout=logf,
    stderr=subprocess.STDOUT,
    creationflags=CREATE_DETACHED,
)

print(f"uvicorn launched, PID={proc.pid}, log={LOG_PATH}")
logf.close()
