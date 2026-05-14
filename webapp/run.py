"""Start the RedPipeline webapp.

    python webapp/run.py               # default: http://localhost:8000
    python webapp/run.py --port 5000
"""
import argparse
import subprocess
import sys
from pathlib import Path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", default=False)
    args = parser.parse_args()

    api_path = str(Path(__file__).parent / "api.py")
    cmd = [
        sys.executable, "-m", "uvicorn",
        "webapp.api:app",
        "--host", args.host,
        "--port", str(args.port),
    ]
    if args.reload:
        cmd.append("--reload")

    print(f"\n🔴  RedPipeline starting → http://localhost:{args.port}\n")
    subprocess.run(cmd, cwd=str(Path(__file__).resolve().parents[1]))

if __name__ == "__main__":
    main()
