from pathlib import Path
import shutil,sys,json,zipfile,importlib.util,argparse
repo=Path(__file__).resolve().parents[2];pr=repo.parent/'Umi-OCR-Plugin'
parser=argparse.ArgumentParser();parser.add_argument('--merged-root',type=Path,default=repo/'build/artifacts/281-merged/complete');args=parser.parse_args()
u=repo/'build/artifacts/281-unmerged/complete/UmiOCR-data';m=args.merged_root.resolve()/'UmiOCR-data'
assert m.is_relative_to(repo/'build/artifacts')

for name in ('py_src','qt_res'):
 target=u/name;assert target.is_relative_to(repo/'build');shutil.rmtree(target);shutil.copytree(repo/'UmiOCR-data'/name,target,ignore=shutil.ignore_patterns('__pycache__'))
for name in ('main.py','about.json'):shutil.copy2(repo/'UmiOCR-data'/name,u/name);shutil.copy2(u/name,m/name)
for name,source in [('win32_PaddleOCRv6_CPU',pr/'win32_PaddleOCRv6_CPU'),('win32_PaddleOCRv6_CUDA',repo/'UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA'),('win32_PaddleOCRVL_1_6',pr/'win32_PaddleOCRVL_1_6')]:
 for f in source.rglob('*'):
  if not f.is_file() or {'vendor','models','__pycache__','temp_doc'} & set(f.relative_to(source).parts):continue
  rel=f.relative_to(source)
  for data in (u,m):
   if data==m and f.name=='umi-plugin.json':continue
   dest=data/'plugins'/name/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(f,dest)
sys.path.insert(0,str(m/'site-packages'));sys.path.insert(0,str(repo/'build/tools'));from merge_runtime import merge_modules,merge_resources
scratch=repo/'build/staging/281-source-refresh';scratch.mkdir(exist_ok=True)
for name in ('app.zip','ui.rcc'):
 p=m/name
 if p.exists():p.unlink()
shutil.copytree(u/'py_src',scratch/'py_src',dirs_exist_ok=True)
record=merge_modules(scratch/'py_src',m/'app.zip',whole=True)
with zipfile.ZipFile(m/'app.zip') as z:entries=[(i,z.read(i.filename)) for i in z.infolist()]
with zipfile.ZipFile(m/'app.zip','w',compression=zipfile.ZIP_STORED) as z:
 z.writestr('py_src/',b'')
 for i,data in entries:i.filename='py_src/'+i.filename;z.writestr(i,data)
record['source_hashes']={'py_src/'+k:v for k,v in record['source_hashes'].items()}
shutil.copytree(u/'qt_res',scratch/'qt_res',dirs_exist_ok=True)
rcc=repo/'build/staging/281-base-current/UmiOCR-data/site-packages/PySide6/rcc.exe';resource=merge_resources(scratch/'qt_res',m/'ui.rcc','qt_res',rcc)
report=json.loads((m/'archive-layout.json').read_text('utf-8'));report['records'][0]=record;report['records'][2]=resource;(m/'archive-layout.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
p=m/'plugins/win32_PaddleOCRVL_1_6';(p/'resources.rcc').unlink();resource=merge_resources(p/'StructuredDocument.qml',p/'resources.rcc','plugins/'+p.name,rcc)
report=json.loads((p/'archive-layout.json').read_text('utf-8'))
if len(report['records']) > 1: report['records'][1]=resource
else: report['records'].append(resource)
(p/'archive-layout.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
print('Both candidates now use the same current first-party source snapshot.')
