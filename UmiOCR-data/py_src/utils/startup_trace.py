"""Opt-in normal-startup observation. No Qt imports or default initialization.

The launcher imports this module only when UMI_STARTUP_TRACE is set. S6 describes
only the named startup work below, never every background task in the process.
Detail records are bounded synchronous observations, not readiness stages. A
missing end is not completion (startup may fail or reach the detail budget).
"""

import json
import os
from pathlib import Path
import re
import sys
import threading
import time


STAGES = tuple("S" + str(index) for index in range(7))
RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z")
CLOCK = "windows-perf-counter-ns" if os.name == "nt" else "perf-counter-ns"
DETAIL_NAMES = frozenset({
    "about-import", "about-json", "about-diagnostics-import", "about-platform", "about-hardware",
    "qt-application", "connectors-import", "connectors-register", "translation",
    "page-controller", "page-create-component", "page-create-object",
})
DETAIL_EVENT_LIMIT = 256
DETAIL_TEXT_LIMIT = 160


def readiness_blockers(state, *, frame_seen, cli_registered, pending_required=()):
    blockers = list(pending_required)
    for key, ready in (("first-frame", frame_seen), ("current-page", state.get("pageReady")),
                       ("connectors", state.get("connectorsReady")),
                       ("backend-apply", state.get("backendReady")),
                       ("cli-registration", cli_registered), ("http-listener", state.get("httpReady"))):
        if not ready:
            blockers.append(key)
    return blockers


def optional_blockers(state, *, native_timers, native_observer_available, pending=()):
    blockers = list(pending)
    if not native_observer_available:
        blockers.append("native-title-observer-unavailable")
    if native_timers:
        blockers.append("native-title-refresh")
    if state.get("cudaPending"):
        blockers.append("cuda-device-discovery")
    if state.get("pluginsBusy"):
        blockers.append("plugin-operations")
    # Delayed/model warmup is not falsely declared finished by observing an idle
    # timer before its deadline. This first baseline supports the lazy policy.
    if state.get("warmupMode") != "lazy" or state.get("modelState") == "warming":
        blockers.append("model-warmup-outside-lazy-baseline")
    return blockers


class StartupTrace:
    def __init__(self, path, run_id, s0_ns, *, clock=time.perf_counter_ns):
        path = Path(path)
        if not path.is_absolute() or not path.parent.is_dir():
            raise ValueError("Startup trace needs an existing absolute parent directory")
        if not RUN_ID.fullmatch(run_id):
            raise ValueError("Invalid startup run ID")
        now = clock()
        if not isinstance(s0_ns, int) or not 0 < s0_ns <= now:
            raise ValueError("S0 must use this machine's perf_counter_ns clock")
        self.path, self.run_id, self.s0_ns = path, run_id, s0_ns
        self._clock, self._lock = clock, threading.RLock()
        self._stages, self._stage_times, self._pending = set(), {}, {}
        self._detail_count, self._detail_limit_reported = 0, False
        self._stream = path.open("x", encoding="utf-8", buffering=1)
        self.mark("S0", at_ns=s0_ns, origin="external-before-CreateProcess")

    def _write(self, event, at_ns, details):
        self._stream.write(json.dumps({"format": "umi-startup-trace-v1", "runId": self.run_id,
            "pid": os.getpid(), "clock": CLOCK, "event": event, "t_ns": at_ns,
            "sinceS0Ms": round((at_ns - self.s0_ns) / 1_000_000, 4), "details": details},
            ensure_ascii=False, separators=(",", ":")) + "\n")

    def mark(self, event, *, at_ns=None, **details):
        with self._lock:
            if self._stream.closed or event in self._stages:
                return False
            at_ns = self._clock() if at_ns is None else at_ns
            if at_ns < self.s0_ns:
                raise ValueError("Startup event predates S0")
            if event in STAGES:
                previous = STAGES[:STAGES.index(event)]
                if any(stage not in self._stages for stage in previous):
                    raise ValueError("Out-of-order startup stage: " + event)
                if any(self._stage_times[stage] > at_ns for stage in previous):
                    raise ValueError("Startup stage clock moved backwards")
                self._stages.add(event)
                self._stage_times[event] = at_ns
            self._write(event, at_ns, details)
            return True

    def detail(self, name, phase, subject="", outcome=""):
        """Observe existing work only; never admit a stage/task via this API.

        At most 256 detail rows plus one explicit budget notice are written per
        process, before S6. Page keys/outcomes are short labels, not probe data.
        """
        if (not isinstance(name, str) or name not in DETAIL_NAMES or
                phase not in ("begin", "end") or
                not isinstance(subject, str) or not isinstance(outcome, str)):
            return False
        with self._lock:
            if self._stream.closed or "S6" in self._stages:
                return False
            if self._detail_count >= DETAIL_EVENT_LIMIT:
                if not self._detail_limit_reported:
                    self._detail_limit_reported = True
                    self.mark("detail-limit", limit=DETAIL_EVENT_LIMIT, scope="before-S6")
                return False
            self._detail_count += 1
            return self.mark("detail", name=name, phase=phase,
                subject=subject[:DETAIL_TEXT_LIMIT], outcome=outcome[:DETAIL_TEXT_LIMIT],
                sequence=self._detail_count)

    def scheduled(self, key, required):
        with self._lock:
            if key in self._pending:
                raise ValueError("Duplicate startup task: " + key)
            self._pending[key] = bool(required)
            self.mark("task-scheduled", task=key, required=bool(required))

    def completed(self, key):
        with self._lock:
            if key not in self._pending:
                raise ValueError("Unknown startup task: " + key)
            del self._pending[key]
            self.mark("task-completed", task=key)

    def pending(self, required):
        with self._lock:
            return [key for key, value in self._pending.items() if value is required]

    def close(self):
        with self._lock:
            if not self._stream.closed:
                self._stream.close()

    def attach_qt(self, application, engine):
        return _attach_qt(self, application, engine)


def from_environment(environ=None):
    environ = os.environ if environ is None else environ
    path = environ.get("UMI_STARTUP_TRACE", "")
    if not path:
        return None
    return StartupTrace(path, environ.get("UMI_STARTUP_RUN_ID", ""),
                        int(environ.get("UMI_STARTUP_S0_NS", "0")))


_STATE = """JSON.stringify((function(){
    const g=qmlapp.globalConfigs, t=qmlapp.tab;
    const entry=t.pageList[t.showPageIndex], page=entry && entry.obj;
    const conf=page && page.configsComp;
    const server=!!g.getValue('server.enable');
    return {pageKey:entry ? entry.info.key : '',
        pageReady:!!page && page.visible && page.enabled && (!conf || conf.isChangedInit!==false),
        connectorsReady:!!qmlapp.msnConnector && !!qmlapp.utilsConnector && !!t.bar,
        backendReady:g.applyPhase===0 && !g.backendApplyPending && !g.pluginRefreshPending &&
            !g.ocrManager.applying && !g.documentManager.applying && !qmlapp.msnConnector.isBusy(),
        httpEnabled:server, httpReady:!server || g.isPortInit,
        httpPort:Number(g.getValue('server.port')), cudaPending:g.cudaDiscoveryPending,
        warmupMode:g.getValue('ocr.lifecycle.warmupMode') || 'lazy', modelState:g.ocrManager.modelState};
})())"""


def _attach_qt(trace, application, engine):
    from PySide6.QtCore import QObject, QTimer, Qt, Slot
    from PySide6.QtQml import QQmlEngine, QQmlExpression

    class Observer(QObject):
        def __init__(self):
            super().__init__(application)
            self.window = None
            self.s5 = self.s6 = self.stopping = False
            self.last_optional_blockers = None
            self.last_tick = None
            self.max_gap_ns = self.ticks = 0
            self.native = []
            self.timer = QTimer(self)
            self.timer.setInterval(20)
            self.timer.timeout.connect(self.poll)
            application.aboutToQuit.connect(self.quitting)

        @Slot(str)
        def stage(self, name):
            if name != "S3":
                raise ValueError("QML may only mark S3 directly")
            trace.mark(name, origin="global-configs-metadata")

        @Slot(str, str, str, str)
        def detail(self, name, phase, subject, outcome):
            trace.detail(name, phase, subject, outcome)

        @Slot(str, bool)
        def scheduled(self, key, required):
            trace.scheduled(key, required)

        @Slot(str)
        def completed(self, key):
            trace.completed(key)

        def loaded(self, window):
            self.window = window
            module = sys.modules.get("py_src.utils.theme_connector")
            if module is not None:
                self.native = window.findChildren(module.ThemeConnector)
            window.frameSwapped.connect(self.first_frame, Qt.ConnectionType.DirectConnection)
            self.last_tick = time.perf_counter_ns()
            self.timer.start()

        @Slot()
        def first_frame(self):
            # Direct render-thread callback: timestamp only, no QML/GUI access.
            trace.mark("S4", origin="QQuickWindow.frameSwapped")

        def evaluate(self, obj, code):
            expression = QQmlExpression(QQmlEngine.contextForObject(obj), obj, code)
            value = expression.evaluate()
            if expression.hasError():
                raise RuntimeError(expression.error().toString())
            if isinstance(value, tuple):
                value = value[0]
            return value.toVariant() if hasattr(value, "toVariant") else value

        def state(self):
            state = json.loads(self.evaluate(self.window, _STATE))
            # contextForObject 返回组件的外层上下文，不能据此访问其私有 QML id。
            # 读取同一窗口内真实的 Python 连接器，并且只查找一次，不改变初始化。
            if not hasattr(self, "plugin_connector"):
                module = sys.modules.get("py_src.plugins_controller.plugins_connector")
                connectors = self.window.findChildren(module.PluginsConnector) if module else []
                if len(connectors) != 1:
                    raise RuntimeError("无法唯一观察本窗口的插件操作连接器")
                self.plugin_connector = connectors[0]
            state["pluginsBusy"] = bool(self.plugin_connector.isBusy())
            return state

        def poll(self):
            now = time.perf_counter_ns()
            self.max_gap_ns = max(self.max_gap_ns, now - self.last_tick)
            self.last_tick = now
            self.ticks += 1
            if self.s6:
                return
            try:
                state = self.state()
                module = sys.modules.get("py_src.server.cmd_server")
                actuator = getattr(module, "CmdActuator", None)
                cli = bool(actuator and actuator.tagPageConn is not None and
                           {"GlobalConfigs", "MainWindow", "TabViewManager"} <= actuator.qmlDict.keys())
                blockers = readiness_blockers(state, frame_seen="S4" in trace._stages,
                    cli_registered=cli, pending_required=trace.pending(True))
                if blockers:
                    return
                if not self.s5:
                    self.s5 = True
                    trace.mark("S5", origin="current-page-and-command-admissions", state=state,
                               pollIntervalMs=20, maxEventLoopGapMs=round(self.max_gap_ns / 1e6, 3))
                    # Recheck after the already queued UI callbacks, not a fixed sleep.
                    QTimer.singleShot(0, self.finish_optional)
            except Exception as exc:
                trace.mark("observer-error", error=str(exc))
                self.timer.stop()

        def finish_optional(self):
            if self.s6 or self.stopping:
                return
            try:
                state = self.state()
                blockers = optional_blockers(state,
                    native_timers=any(item._native_refresh.isActive() for item in self.native),
                    native_observer_available=bool(self.native), pending=trace.pending(False))
                if blockers:
                    if blockers != self.last_optional_blockers:
                        trace.mark("optional-pending", tasks=blockers)
                        self.last_optional_blockers = blockers
                    QTimer.singleShot(20, self.finish_optional)
                    return
                self.s6 = True
                trace.mark("S6", origin="named-startup-work-completed", state=state,
                    scope=["tracked-QML-callbacks", "native-title-refresh", "cuda-device-discovery", "plugin-operations", "about-system-info"],
                    limits="lazy warmup only; unregistered third-party background work is not observed")
            except Exception as exc:
                trace.mark("observer-error", error=str(exc))

        def quitting(self):
            self.stopping = True
            self.timer.stop()
            trace.mark("qt-about-to-quit", completedStages=sorted(trace._stages),
                pendingRequired=trace.pending(True), pendingOptional=trace.pending(False),
                heartbeatSamples=self.ticks, maxEventLoopGapMs=round(self.max_gap_ns / 1e6, 3))

    observer = Observer()
    engine.rootContext().setContextProperty("UmiStartupTrace", observer)
    return observer
