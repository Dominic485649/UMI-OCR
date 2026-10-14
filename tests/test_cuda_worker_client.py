"""A restarted worker must not consume responses from its predecessor."""

import argparse
import inspect
from pathlib import Path
import queue
import sys
import threading
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("data_root", nargs="?", type=Path, default=ROOT / "UmiOCR-data")
args = parser.parse_args()
sys.path.insert(0, str(args.data_root.resolve() / "plugins"))
from win32_PaddleOCRv6_CUDA.api import _WorkerClient


def main():
    ready = threading.Event()
    release = threading.Event()
    class OldStream:
        def __iter__(self):
            ready.set()
            assert release.wait(3)
            yield '{"ok":true,"old_worker":true}\n'
    client = _WorkerClient()
    client.process = SimpleNamespace(stdout=OldStream())
    old_responses = client.responses
    # Permit the regression to demonstrate the prior implementation's failure.
    args = (client.process.stdout, old_responses) if len(inspect.signature(client._read).parameters) else ()
    thread = threading.Thread(target=client._read, args=args)
    thread.start()
    try:
        assert ready.wait(1)
        client.responses = queue.Queue()
    finally:
        release.set()
        thread.join(3)
    assert not thread.is_alive()
    assert client.responses.empty(), "old worker response polluted the restarted worker queue"
    assert old_responses.get_nowait()["old_worker"] is True
    print("CUDA worker restart response-isolation regression passed.")


if __name__ == "__main__":
    main()
