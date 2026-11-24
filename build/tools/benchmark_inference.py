"""Serial real CPU/GPU inference with worker peak RSS and device-memory sampling."""
import argparse, ctypes, importlib, json, os, sys, threading, time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from staging_smoke import configure_runtime
p=argparse.ArgumentParser();p.add_argument("data",type=Path);p.add_argument("device",choices=("cpu","gpu"));p.add_argument("--input",type=Path,required=True);p.add_argument("--output",type=Path,required=True);p.add_argument("--trials",type=int,default=3);a=p.parse_args();a.data=a.data.resolve();a.input=a.input.resolve();a.output=a.output.resolve();handles=configure_runtime(a.data)
key="win32_PaddleOCRv6_CPU" if a.device=="cpu" else "win32_PaddleOCRv6_CUDA"
Api=importlib.import_module(key+".api").Api
class Counters(ctypes.Structure):
 _fields_=[("cb",ctypes.c_uint32),("faults",ctypes.c_uint32)]+[(n,ctypes.c_size_t) for n in ("peak","working","peak_paged","paged","peak_unpaged","unpaged","private","peak_private")]
class Memory(ctypes.Structure): _fields_=[("total",ctypes.c_uint64),("free",ctypes.c_uint64),("used",ctypes.c_uint64)]
gpu_handle=ctypes.c_void_p();nvml=None
try:
 nvml=ctypes.WinDLL("nvml.dll");assert nvml.nvmlInit_v2()==0;assert nvml.nvmlDeviceGetHandleByIndex_v2(0,ctypes.byref(gpu_handle))==0
except Exception:nvml=None
ctypes.windll.kernel32.OpenProcess.restype=ctypes.c_void_p
records=[]
for trial in range(a.trials):
 api=Api({"device":"gpu:0","preprocessThreads":1});peak_gpu=[0];stop=threading.Event()
 def sample():
  while not stop.wait(.02):
   if nvml:
    value=Memory()
    if nvml.nvmlDeviceGetMemoryInfo(gpu_handle,ctypes.byref(value))==0:peak_gpu[0]=max(peak_gpu[0],value.used)
 monitor=threading.Thread(target=sample,daemon=True);monitor.start()
 try:
  begin=time.perf_counter();error=api.start({"taskType":"screenshot","docOrientation":False,"undistort":"off","textlineOrientation":"off","longSide":1600,"recBatchSize":1,"scoreThreshold":.45})
  assert not error,error
  initialized=time.perf_counter();times=[];text=[]
  for _ in range(3):
   begin_ocr=time.perf_counter();result=api.runPath(str(a.input));times.append(time.perf_counter()-begin_ocr)
   assert result["code"]==100 and result["data"],result
   text=[x["text"] for x in result["data"]]
  pid=api._worker.process.pid if hasattr(api,"_worker") else os.getpid();process=ctypes.windll.kernel32.OpenProcess(0x410,False,pid);counter=Counters();counter.cb=ctypes.sizeof(counter)
  assert ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(process),ctypes.byref(counter),counter.cb)
  ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(process))
  records.append({"trial":trial,"initialize_seconds":initialized-begin,"inference_seconds":times,"worker_peak_rss_mb":counter.peak/1048576,"device_total_peak_vram_mb":peak_gpu[0]/1048576 if nvml else None,"execution":api.get_execution_info(),"text":text})
 finally:
  stop.set();monitor.join(2);api.stop()
report={"device":a.device,"python":sys.version.split()[0],"memory_scope":"inference worker, or full host process for the legacy in-process CPU backend","trials":records,"vram_scope":"entire device, includes desktop/browser allocations; serial OCR"}
a.output.parent.mkdir(exist_ok=True,parents=True);a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8");print(json.dumps(report,ensure_ascii=False))
