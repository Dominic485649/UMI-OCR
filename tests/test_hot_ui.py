"""Actual Windows QML window, event-loop timing and hot configuration checks."""
import argparse, ctypes, json, os, runpy, sys, time
from pathlib import Path

started=time.perf_counter()
p=argparse.ArgumentParser()
p.add_argument("root",type=Path)
p.add_argument("--output",type=Path,required=True)
p.add_argument("--hot",action="store_true")
p.add_argument("--profile",choices=("cuda-only","all-plugins"),default="all-plugins")
args=p.parse_args();root=args.root.resolve();args.output=args.output.resolve()
args.output.parent.mkdir(parents=True,exist_ok=True)
namespace=runpy.run_path(str(root/"UmiOCR-data/main.py"),run_name="runtime_test");namespace["initRuntimeEnvironment"]();os.MessageBox=lambda message,*args:print(message)
from PySide6 import QtQml
from PySide6.QtCore import QTimer, QCoreApplication
from PySide6.QtQml import QQmlExpression, QQmlEngine
from PySide6.QtWidgets import QApplication

report={"python":sys.version.split()[0],"profile":args.profile,"errors":[]}
class Counters(ctypes.Structure):
    _fields_=[("cb",ctypes.c_uint32),("PageFaultCount",ctypes.c_uint32)]+[(name,ctypes.c_size_t) for name in ("PeakWorkingSetSize","WorkingSetSize","QuotaPeakPagedPoolUsage","QuotaPagedPoolUsage","QuotaPeakNonPagedPoolUsage","QuotaNonPagedPoolUsage","PagefileUsage","PeakPagefileUsage","PrivateUsage")]
def memory():
    value=Counters();value.cb=ctypes.sizeof(value);ctypes.windll.kernel32.GetCurrentProcess.restype=ctypes.c_void_p
    assert ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(ctypes.windll.kernel32.GetCurrentProcess()),ctypes.byref(value),value.cb)
    return {"working_set_mb":value.WorkingSetSize/1048576,"peak_working_set_mb":value.PeakWorkingSetSize/1048576,"private_mb":value.PrivateUsage/1048576}
def wait(predicate,timeout=12):
    end=time.perf_counter()+timeout
    while not predicate():
        assert time.perf_counter()<end,"UI transition timed out"
        QCoreApplication.processEvents();time.sleep(.01)
def evaluate(engine,window,expression):
    expr=QQmlExpression(QQmlEngine.contextForObject(window),window,expression)
    value=expr.evaluate()
    assert not expr.hasError(),expr.error().toString()
    if isinstance(value,tuple):value=value[0]
    return value.toVariant() if hasattr(value,"toVariant") else value
Original=QtQml.QQmlApplicationEngine
class Engine(Original):
    def load(self,*values):
        super().load(*values)
        assert self.rootObjects(),"No QML root"
        window=self.rootObjects()[0]
        def first_frame():
            if "interactive_seconds" not in report:
                QTimer.singleShot(0,ready)
                report["interactive_seconds"]=time.perf_counter()-started
        def ready():
            report["idle"]=memory()
            try:
                if args.hot:
                    def js(code):return evaluate(self,window,code)
                    report["plugins"]=js("JSON.stringify(qmlapp.globalConfigs.pluginStates)")
                    assert js("qmlapp.tab.savedPageIndex('file:///D:/old/UmiOCR-data/plugins/win32_PaddleOCRVL_1_6/StructuredDocument.qml')") == js("qmlapp.tab.savedPageIndex('StructuredDocument')")
                    # Capability discovery must not load native inference into the host.
                    assert not any(name in sys.modules for name in ("paddle","paddlex","paddleocr","onnxruntime","fitz","pymupdf"))
                    assert not js("qmlapp.globalConfigs.panelBuilt")
                    js("qmlapp.globalConfigs.initPanelComponent()")
                    assert js("qmlapp.globalConfigs.panelBuilt")
                    selected = "win32_PaddleOCRv6_CUDA" if args.profile == "cuda-only" else "win32_PaddleOCRv6_CPU"
                    js("qmlapp.globalConfigs.setValue('ocr.api',"+json.dumps(selected)+",true)")
                    wait(lambda:js("qmlapp.globalConfigs.applyPhase === 0 && !qmlapp.globalConfigs.backendApplyPending && !qmlapp.globalConfigs.ocrManager.applying"))
                    from py_src.mission.mission_ocr import MissionOCR
                    assert MissionOCR._apiKey==selected
                    assert MissionOCR._api.get_status()["state"]=="unloaded"
                    from py_src.plugins_controller.services import PluginServices
                    assert all(not entry["instance"] or not entry["instance"].get_status().get("pid") for entry in PluginServices._entries.values())
                    from py_src.plugins_controller.plugins_controller import PluginsController
                    ready_plugins={x["id"] for x in PluginsController.getPlugins() if x["state"] == "ready"}
                    if args.profile == "cuda-only":
                        assert ready_plugins == {"win32_PaddleOCRv6_CUDA"}, ready_plugins
                        assert {x["id"] for x in PluginsController.getPlugins()} == ready_plugins
                    else:
                        js("qmlapp.globalConfigs.setValue('document.win32_PaddleOCRVL_1_6.pipeline.layoutModelDir','D:/AI/models/PP-DocLayoutV3',true)")
                        wait(lambda:js("qmlapp.globalConfigs.applyPhase === 0 && !qmlapp.globalConfigs.backendApplyPending"))
                        assert js("qmlapp.globalConfigs.getValue('document.win32_PaddleOCRVL_1_6.pipeline.layoutModelDir')") == "D:/AI/models/PP-DocLayoutV3"
                        assert ready_plugins == {"win32_PaddleOCRv6_CPU","win32_PaddleOCRv6_CUDA","win32_PaddleOCRVL_1_6"}, ready_plugins
                    # Toggle a backend through the same UI function as the plugin switch.
                    js("qmlapp.globalConfigs.setPluginEnabled('win32_PaddleOCRv6_CUDA', false)")
                    wait(lambda:not js("qmlapp.globalConfigs.pluginRefreshPending || qmlapp.globalConfigs.applyPhase !== 0"))
                    assert not PluginsController.isEnabled("win32_PaddleOCRv6_CUDA")
                    js("qmlapp.globalConfigs.setPluginEnabled('win32_PaddleOCRv6_CUDA', true)")
                    wait(lambda:not js("qmlapp.globalConfigs.pluginRefreshPending || qmlapp.globalConfigs.applyPhase !== 0"))
                    assert PluginsController.isEnabled("win32_PaddleOCRv6_CUDA")
                    js("qmlapp.globalConfigs.setValue('ui.i18n','en_US',true)")
                    wait(lambda:not js("qmlapp.globalConfigs.pluginRefreshPending || qmlapp.globalConfigs.applyPhase !== 0"))
                    from py_src.utils.i18n_configs import I18n
                    assert I18n.langCode=="en_US"
                    assert js("qmlapp.globalConfigs.getOriginDict()['shortcut'].title") == "Shortcut"
                    js("qmlapp.globalConfigs.setValue('ui.i18n','zh_CN',true)")
                    wait(lambda:not js("qmlapp.globalConfigs.pluginRefreshPending || qmlapp.globalConfigs.applyPhase !== 0"))
                    assert js("qmlapp.globalConfigs.getOriginDict()['shortcut'].title") == "快捷方式"
                    import socket, urllib.request
                    with socket.socket() as sock:
                        sock.bind(("127.0.0.1",0));port=sock.getsockname()[1]
                    js("qmlapp.globalConfigs.setValue('server.port',"+str(port)+",true)")
                    def responds():
                        try:
                            with urllib.request.urlopen("http://127.0.0.1:"+str(port)+"/",timeout=.2) as response:return response.status==200
                        except OSError:return False
                    wait(responds)
                    js("qmlapp.globalConfigs.setValue('server.enable',false,true)")
                    wait(lambda:not responds())
                    js("qmlapp.globalConfigs.setValue('server.enable',true,true)")
                    wait(responds)
                    js("qmlapp.globalConfigs.setValue('window.messageMemory',['globalConfigsKey'],true)")
                    js("qmlapp.globalConfigs.setValue('window.simpleNotificationType','none',true)")
                    js("qmlapp.tab.openTabPageByKey('GlobalConfigsPage')")
                    QCoreApplication.processEvents()
                    window.setWidth(640);window.setHeight(540)
                    js("qmlapp.globalConfigs.setValue('ui.theme','Neutral Dark',true)")
                    until=time.perf_counter()+.3
                    while time.perf_counter()<until: QCoreApplication.processEvents(); time.sleep(.01)
                    window.grabWindow().save(str(args.output.with_name(args.output.stem+"-dark-narrow.png")))
                    js("qmlapp.globalConfigs.setValue('ui.theme','Default Light',true)")
                    wait(lambda:js("theme.bgColor.toString() !== '#181818'"))
                    QCoreApplication.processEvents()
                    window.grabWindow().save(str(args.output.with_name(args.output.stem+"-settings-light.png")))
                    assert js("UmiAbout.url.home") == "https://github.com/Dominic485649/UMI-OCR"
                    assert js("UmiAbout.url.plugins") == "https://github.com/Dominic485649/UMI-OCR_plugins"
                    expected_version=json.loads((root/"UmiOCR-data/about.json").read_text(encoding="utf-8"))["version"]
                    version_string=".".join(str(expected_version[k]) for k in ("major","minor","patch"))
                    assert js("UmiAbout.version.string") == version_string
                    assert js("!!qmlapp.tab.openTabPageByKey('About')"), "About page failed to instantiate"
                    until=time.perf_counter()+.3
                    while time.perf_counter()<until: QCoreApplication.processEvents(); time.sleep(.01)
                    window.grabWindow().save(str(args.output.with_name(args.output.stem+"-about.png")))
                    if args.profile == "all-plugins":
                        assert js("!!qmlapp.tab.openTabPageByKey('StructuredDocument')"), "Document page failed to instantiate"
                        until=time.perf_counter()+.3
                        while time.perf_counter()<until: QCoreApplication.processEvents(); time.sleep(.01)
                        window.grabWindow().save(str(args.output.with_name(args.output.stem+"-document.png")))
                    report["hot"]=True
                window.grabWindow().save(str(args.output.with_suffix(".png")))
                report["end"]=memory()
            except Exception as exc:
                import traceback
                report["errors"].append(traceback.format_exc());print(traceback.format_exc())
            finally:
                args.output.parent.mkdir(exist_ok=True,parents=True)
                args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
                QApplication.instance().quit()
        window.frameSwapped.connect(first_frame)
        QTimer.singleShot(12000,lambda: QApplication.instance().quit() if "interactive_seconds" not in report else None)
QtQml.QQmlApplicationEngine=Engine
from py_src.run import main
sys.argv=[str(root/"Umi-OCR.exe"),"--force"]
try:main(str(root/"Umi-OCR.exe"),"./site-packages/PySide6/qml")
except SystemExit as exc:
    if exc.code not in (0,None):raise
assert args.output.exists(),"No interactive frame observed"
assert not report["errors"],report["errors"]
print(json.dumps(report,ensure_ascii=False))
