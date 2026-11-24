"""Summarize the serial benchmark evidence without inventing missing measurements."""
import json,statistics
from pathlib import Path
root=Path(__file__).resolve().parents[2];audit=root/'build/audit'
def read(name):return json.loads((audit/name).read_text('utf-8-sig'))
def median(xs):return round(statistics.median(xs),4)
report={'version':'2.8.1','method':'Serial Windows trials; no OS cache flush; Working Set/PeakWorkingSet; whole-device VRAM includes other applications','ui':{},'inference':{},'copy':read('copy-times.json'),'fallbacks':{'CPU':'Private vendor remains loose after >5% initialization regression in two of three paired rounds','CUDA':'Private vendor remains loose after repeatable >5% latency regression','VL':'openai/paddleocr/paddlex stay loose; other compatible modules Stored ZIP'}}
for label in ('old-baseline','unmerged','merged'):
 rows=[read(f'performance-ui-{label}-{i}.json') for i in range(3)]
 report['ui'][label]={'first_interactive_seconds':rows[0]['interactive_seconds'],'subsequent_median_seconds':median(r['interactive_seconds'] for r in rows[1:]),'idle_rss_mb':median(r['idle']['working_set_mb'] for r in rows)}
for kind,files in {'cpu-old':'cpu-old','cpu-unmerged':'cpu-unmerged','cpu-final':'cpu-fallback','gpu-old':'gpu-old','gpu-unmerged':'gpu-unmerged-repeat','gpu-final':'gpu-final'}.items():
 j=read('performance-'+files+'.json');rows=j['trials']
 report['inference'][kind]={'evidence':'performance-'+files+'.json','initialize_first_seconds':rows[0]['initialize_seconds'],'initialize_median_seconds':median(r['initialize_seconds'] for r in rows),'warm_inference_median_seconds':median(t for r in rows for t in r['inference_seconds'][-2:]),'peak_rss_median_mb':median(r['worker_peak_rss_mb'] for r in rows),'device_total_peak_vram_mb':max(r['device_total_peak_vram_mb'] for r in rows)}
for label,name in [('old','old'),('unmerged','unmerged-repeat'),('final','selective')]:
 rows=[read(f'performance-vl-{name}-{i}.json') for i in range(3)]
 assert all(r['response']['ok'] and r['spottingResponse']['ok'] and r['sameServerPid'] and not r.get('runnerError') for r in rows)
 report['inference']['vl-'+label]={'service_ready_median_seconds':median(r['serviceReadySeconds'] for r in rows),'spotting_median_seconds':median(r['spottingResponse']['elapsed_seconds'] for r in rows),'document_median_seconds':median(r['response']['elapsed_seconds'] for r in rows),'worker_server_sum_peak_rss_median_mb':median(sum(r['peak_rss_mb'].values()) for r in rows),'device_total_peak_vram_mb':max(r['device_total_peak_vram_mb'] for r in rows)}
final=root/'build/artifacts/281-final/complete'
if final.exists():
 report['files']={name:sum(p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc' and not any(part in {'logs','temp','temp_doc'} for part in p.relative_to(path).parts) and p.name not in {'.settings','.pre_settings','.plugins_state','themes.json','startup_error.log'} for p in path.rglob('*')) for name,path in [('old',root/'build/artifacts/281-old-baseline/complete'),('unmerged',root/'build/artifacts/281-unmerged/complete'),('final',final)]}
report['file_count_scope']='Complete product; excludes runtime-generated caches, logs and user profiles; includes source/licence metadata'
report['cpu_paired_zip_rejection']={label:[read(f'performance-cpu-paired-{label}-{i}.json')['trials'][0] for i in range(3)] for label in ('unmerged','final')}
if (audit/'copy-final.json').exists():report['copy'].update(read('copy-final.json'))
(audit/'performance-summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n','utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
