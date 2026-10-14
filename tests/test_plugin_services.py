"""Deterministic checks for lazy shared-service initialization and failures."""

import argparse
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build/tools"))
from staging_smoke import configure_runtime


def check_lazy_initialization(registry_class):
    registry = registry_class()
    started = threading.Event()
    second_started = threading.Event()
    second_resolve = threading.Event()
    release = threading.Event()
    instances = []
    results = []
    errors = []

    def resolve():
        value = object()
        instances.append(value)
        if len(instances) > 1:
            second_resolve.set()
        started.set()
        assert release.wait(3), "service resolver release timed out"
        return value

    registry.register("custom", "shared", resolve)
    assert not instances, "discovery must remain lazy"

    def worker(second=False):
        if second:
            second_started.set()
        try:
            results.append(registry.get("custom", "shared"))
        except Exception as exc:
            errors.append(exc)

    first = threading.Thread(target=worker)
    second = threading.Thread(target=worker, kwargs={"second": True})
    first.start()
    try:
        assert started.wait(1), "first service initialization did not start"
        second.start()
        assert second_started.wait(1)
        # While the first resolver is blocked, concurrent discovery must wait
        # for its instance, not initialize a second model/service process.
        second_resolve.wait(0.3)
    finally:
        release.set()
        first.join(3)
        if second.ident is not None:
            second.join(3)
    assert not first.is_alive() and not second.is_alive()
    assert not errors, errors
    assert len(instances) == 1, "concurrent calls initialized duplicate shared services"
    assert len(results) == 2 and results[0] is results[1]


def check_resolver_failure_can_retry(registry_class):
    registry = registry_class()
    attempts = []
    expected = object()
    def resolve():
        attempts.append(True)
        if len(attempts) == 1:
            raise RuntimeError("forced resolver failure")
        return expected
    registry.register("custom", "shared", resolve)
    try:
        registry.get("custom", "shared")
    except RuntimeError:
        pass
    else:
        raise AssertionError("resolver failure was hidden")
    assert registry.get("custom", "shared") is expected
    assert len(attempts) == 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("data_root", type=Path)
    parser.add_argument("--source-root", type=Path)
    args = parser.parse_args()
    handles = configure_runtime(args.data_root.resolve())
    if args.source_root:
        root = args.source_root.resolve()
        sys.path[:0] = [str(root), str(root / "py_src/imports")]
    from py_src.plugins_controller.services import PluginServiceRegistry
    check_lazy_initialization(PluginServiceRegistry)
    check_resolver_failure_can_retry(PluginServiceRegistry)
    print("Shared service initialization regression passed.")
