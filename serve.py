"""Serve the results pages and the scenario editor on this computer, and open the browser.

    python serve.py                 http://localhost:8000
    python serve.py --port 8010     another port, if 8000 is taken
    python serve.py --no-open       do not open the browser

The pages are the same files view.py opens; served, they also link to the scenario editor
(/editor/<city>), which saves scenarios and runs them. Stop the server with Ctrl+C. It listens on
this computer only: nobody else on the network can reach it.
"""
import argparse
import os
import sys
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.server import serve                      # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-open", action="store_true", help="do not open the browser")
    args = parser.parse_args()

    try:
        server = serve(args.port)
    except OSError as problem:
        parser.error(f"cannot listen on port {args.port} ({problem}): try --port 8010")
    url = f"http://localhost:{args.port}/"
    print(f"Serving the results and the scenario editor at {url}\nCtrl+C to stop.")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
