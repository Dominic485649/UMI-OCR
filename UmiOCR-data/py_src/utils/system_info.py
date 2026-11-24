"""About-page diagnostics, collected once without blocking Qt or shutdown.

The daemon worker owns no QObject, callbacks to Qt, or executor. It only calls
our existing collector and deposits plain data in a queue. A child QTimer
commits on the GUI thread; destruction/quit only cancels polling, never joins.
"""

import json
from queue import Empty, SimpleQueue
from threading import Event, Thread

from PySide6.QtCore import QObject, Property, QThread, QTimer, Signal, Slot


OPTIONAL_TASK = "about-system-info"
DIAGNOSTIC_FIELDS = frozenset({"platform", "python", "cpu", "ram"})


def _collect(collector, trace, results, cancelled):
    # Deliberately no reference to the provider, QApplication, or another QObject.
    if cancelled.is_set():
        return
    try:
        values = collector(startupTrace=trace)
        result = (values, "")
    except Exception as exc:
        result = (None, (type(exc).__name__ + ": " + str(exc))[:240])
    if not cancelled.is_set():
        results.put(result)


class SystemInfo(QObject):
    infoChanged = Signal()
    stateChanged = Signal()

    def __init__(self, application, app_info, collector, startupTrace=None):
        super().__init__(application)
        self._app = app_info
        self._values = dict(app_info)
        self._collector, self._trace = collector, startupTrace
        self._state, self._error = "pending", ""
        self._started = False
        self._worker = None
        self._results, self._cancelled = SimpleQueue(), Event()
        self._timer = QTimer(self)
        self._timer.setInterval(25)
        self._timer.timeout.connect(self._poll)
        application.aboutToQuit.connect(self.stop)
        # The destruction callback captures only a Python Event, never self.
        cancelled = self._cancelled
        self.destroyed.connect(lambda *_: cancelled.set())
        self._refresh_json()
        if self._trace is not None:
            self._trace.scheduled(OPTIONAL_TASK, False)

    @Property(str, notify=stateChanged)
    def state(self):
        return self._state

    @Property(str, notify=stateChanged)
    def error(self):
        return self._error

    @Property(str, notify=infoChanged)
    def infoJson(self):
        return self._info_json

    def _refresh_json(self):
        values = dict(self._values)
        if self._state != "ready":
            values["diagnostics"] = {"state": self._state, "error": self._error}
        self._info_json = json.dumps(values, ensure_ascii=False, indent=2)

    def start(self):
        """Called once by the normal startup, never by opening the About page."""
        if self._started or self._cancelled.is_set() or self._state != "pending":
            return
        self._started = True
        try:
            self._worker = Thread(target=_collect,
                args=(self._collector, self._trace, self._results, self._cancelled),
                name="umi-about-system-info", daemon=True)
            self._worker.start()
        except Exception as exc:
            self._finish(None, (type(exc).__name__ + ": " + str(exc))[:240])
            return
        self._timer.start()

    @Slot()
    def _poll(self):
        if self._cancelled.is_set() or self._state != "pending":
            return
        try:
            values, error = self._results.get_nowait()
        except Empty:
            return
        self._finish(values, error)

    def _finish(self, values, error):
        if QThread.currentThread() != self.thread():
            raise RuntimeError("System information must be committed on its Qt thread")
        if self._cancelled.is_set() or self._state != "pending":
            return
        self._timer.stop()
        if not error and (not isinstance(values, dict) or set(values) != DIAGNOSTIC_FIELDS or
                          any(not isinstance(value, str) for value in values.values())):
            error = "Invalid system information result"
        if error:
            self._state, self._error = "failed", error
        else:
            # Preserve Python dictionary identity; the global QML context is a
            # separate startup snapshot and is never reset or notified here.
            self._app.update(values)
            self._values.update(values)
            self._state = "ready"
        self._refresh_json()
        if self._trace is not None:
            self._trace.mark("system-info-result", outcome=self._state)
            self._trace.completed(OPTIONAL_TASK)
        self.infoChanged.emit()
        self.stateChanged.emit()

    @Slot()
    def stop(self):
        if self._cancelled.is_set():
            return
        self._cancelled.set()
        self._timer.stop()
        if self._state == "pending":
            self._state = "cancelled"
            self._refresh_json()
            # Cancellation is not completion: keep the named optional task
            # pending so a trace cannot claim S6 on an unfinished collection.
            if self._trace is not None:
                self._trace.mark("system-info-cancelled", task=OPTIONAL_TASK)
            self.infoChanged.emit()
            self.stateChanged.emit()
