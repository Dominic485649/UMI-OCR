"""Real VL Spotting through the host task/postprocessing/result boundary."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'build/tools'))
from staging_smoke import configure_runtime
p=argparse.ArgumentParser();p.add_argument('data',type=Path);p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--check-benchmark-geometry',action='store_true');a=p.parse_args();a.input=a.input.resolve();a.output=a.output.resolve();handles=configure_runtime(a.data.resolve())
from PySide6.QtCore import QCoreApplication
app=QCoreApplication([])
from py_src.plugins_controller.plugins_controller import PluginsController
from py_src.plugins_controller.services import PluginServices
from py_src.mission.mission_ocr import MissionOCR
from py_src.ocr.tbpu import getParser
state=PluginsController.init();assert not state['errors'],state['errors']
key='win32_PaddleOCRVL_1_6'
config={'service.mode':'managed','service.serverExecutable':'D:/AI/llama.cpp/build/bin/llama-server.exe','service.mainModel':'D:/AI/models/PaddleOCR-VL-1.6-GGUF/PaddleOCR-VL-1.6-GGUF.gguf','service.mmprojModel':'D:/AI/models/PaddleOCR-VL-1.6-GGUF/PaddleOCR-VL-1.6-GGUF-mmproj.gguf','service.port':18872,'resources.gpuLayers':'all','resources.contextLength':8192,'resources.timeoutSeconds':120,'resources.startupTimeoutSeconds':120,'resources.imageMaxTokens':2048}
try:
 assert MissionOCR.setApi(key,config)=='[Success]'
 info={'argd':config,'tbpu':[getParser('multi_para')]}
 assert not MissionOCR.msnPreTask(info)
 result=MissionOCR.msnTask(info,{'path':str(a.input)})
 assert result['code']==100 and result['data'],result
 assert result['score'] is None and all(item.get('score') is None for item in result['data'])
 assert all(len(item['box'])>=4 and item['text'] for item in result['data'])
 assert result['execution']['pluginId']==key and result['execution']['model']=='Paddlevl1.6'
 if a.check_benchmark_geometry:
  from PySide6.QtGui import QImage
  ratio=QImage(str(a.input)).width()/960
  # Known ink positions in recognition-benchmark.png; an in-bounds check misses 2x shrinkage.
  for prefix, expected in [('Umi-OCR',(24,45,451,77)),('独立进程',(24,145,457,178)),('性能验证',(24,245,370,278))]:
   block=next(b for b in result['data'] if b['text'].startswith(prefix))
   xs,ys=zip(*block['box']); actual=(min(xs),min(ys),max(xs),max(ys))
   assert all(abs(x-y*ratio)<=12*ratio for x,y in zip(actual,expected)),(prefix,actual,expected)
 snapshot=json.loads(json.dumps(result,ensure_ascii=False));a.output.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),'utf-8')
 print('Real host VL Spotting passed:',len(result['data']),result['execution'])
finally:MissionOCR.shutdown();PluginServices.shutdownAll()
