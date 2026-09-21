"""Start the local Paper Radar server and open it in the default browser."""
import json
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = 8765
URL = f"http://{HOST}:{PORT}"
LOG_PATH = ROOT / ".runtime" / "launcher-server.log"
HTTP = build_opener(ProxyHandler({}))


def is_ready():
    try:
        with HTTP.open(f"{URL}/api/health", timeout=1) as response:
            if not response.headers.get("Server", "").startswith("PaperRadar/"):
                return False
            health = json.loads(response.read(4096))
            return (isinstance(health, dict)
                    and health.get("status") == "ok"
                    and type(health.get("papers")) is int)
    except (OSError, URLError, ValueError):
        return False


def ensure_server():
    if is_ready():
        return
    try:
        with socket.create_connection((HOST, PORT), timeout=1):
            pass
    except OSError:
        pass
    else:
        raise RuntimeError(f"Port {PORT} is in use, but Paper Radar is not responding.")

    LOG_PATH.parent.mkdir(exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as log:
        log.write(f"\n--- Starting Paper Radar: {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        log.flush()
        process = subprocess.Popen(
            [sys.executable, str(ROOT / "server.py"), "--port", str(PORT)],
            cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if is_ready():
            return
        if process.poll() is not None:
            raise RuntimeError(f"The server exited with code {process.returncode}.")
        time.sleep(0.2)
    process.terminate()
    process.wait(timeout=5)
    raise RuntimeError("The server did not respond within 15 seconds.")


def main():
    if sys.version_info < (3, 10):
        print("Paper Radar requires Python 3.10 or newer.")
        return 1
    try:
        ensure_server()
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Paper Radar could not start: {error}")
        print(f"Server log: {LOG_PATH}")
        return 1
    if not webbrowser.open(URL):
        print(f"The server is ready. Open this address in your browser: {URL}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
