"""封装明确标识的OpenCV图像派生wheel；不复用官方wheel摘要或冒充完整contrib。"""
from __future__ import annotations
import argparse
import base64
import csv
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[2]
VERSION = '4.10.0.84+umi.coreimg.1'
DIST = 'opencv_contrib_python-' + VERSION + '.dist-info'
WHEEL_NAME = 'opencv_contrib_python-' + VERSION + '-cp313-cp313-win_amd64.whl'


def tool(name):
    spec = importlib.util.spec_from_file_location('opencv_package_' + name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


L = tool('runtime_archive_layout')


def sha(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def package(build_record: Path, output: Path, receipt: Path) -> dict:
    build_record, output, receipt = map(L.plain_path, (build_record, output, receipt))
    if not output.is_relative_to(ROOT / 'build') or not receipt.is_relative_to(ROOT / 'build/audit'):
        raise ValueError('派生构件和审计仅写入本项目build')
    if output.exists() or receipt.exists():
        raise FileExistsError('只生成全新派生构件和记录')
    build = L.read_json(build_record)
    if build.get('status') != 'COMPILED_NOT_RUNTIME_ACCEPTED' or build.get('sourceChanged') is not False:
        raise ValueError('缺少真实、来源未变的编译结果')
    if build.get('sourceCommit') != '71d3237a093b60a27601c20e9ee6c3e52154e8b1':
        raise ValueError('OpenCV固定源码提交不符')
    options = build['options']
    required = {'BUILD_LIST': 'core,imgproc,imgcodecs,python3', 'BUILD_SHARED_LIBS': 'OFF',
                'WITH_FFMPEG': 'OFF', 'WITH_GSTREAMER': 'OFF', 'WITH_QT': 'OFF',
                'WITH_GTK': 'OFF', 'WITH_WIN32UI': 'OFF', 'WITH_CUDA': 'OFF',
                'WITH_OPENCL': 'OFF', 'ENABLE_LIBJPEG_TURBO_SIMD': 'ON'}
    if any(options.get(name) != value for name, value in required.items()):
        raise ValueError('派生构建功能白名单或JPEG SIMD请求不符')
    install, source = L.plain_path(Path(build['installRoot'])), L.plain_path(Path(build['sourceRoot']))
    cv2 = install / 'python/cv2'
    files = L.tree_files(cv2)
    natives = {name: path for name, path in files.items() if path.suffix.lower() == '.pyd'}
    if set(natives) != {'python-3.13/cv2.cp313-win_amd64.pyd'} or len(build.get('binaries', [])) != 1:
        raise ValueError('应有唯一cp313原生绑定')
    native = next(iter(natives.values()))
    if sha(native) != build['binaries'][0]['sha256']:
        raise ValueError('编译构件在封装前发生变化')
    licensing = L.tree_files(install / 'etc/licenses')
    if not licensing:
        raise ValueError('必须先导出CMake licenses组件；不跳过原始许可')
    for path in (source / 'LICENSE', source / '3rdparty/libwebp/COPYING'):
        if not path.is_file():
            raise ValueError('缺少实际来源许可：' + str(path))
    profile = {'format': 'umi-opencv-runtime-v1', 'version': VERSION,
               'distribution': 'opencv-contrib-python', 'upstreamLibraryVersion': '4.10.0',
               'scope': 'Umi-OCR派生图像运行子集，不是官方完整opencv-contrib-python；不提供contrib、视频、GUI或推理模块。',
               'compatibilityDistributionNameReason': '保留PaddleX发行版存在性/版本检查使用的名称；本地版本后缀及此清单明确区分派生实现。',
               'sourceCommit': build['sourceCommit'], 'buildRecord': str(build_record),
               'buildRecordSha256': sha(build_record), 'buildScriptSha256': build['buildScriptSha256'],
               'nativeSha256': sha(native), 'options': options,
               'pythonVersion': build['pythonVersion'], 'numpyRequirement': 'numpy==2.3.5',
               'compiler': build['compiler'], 'nasmSha256': build.get('nasmSha256'),
               'licenseScope': 'CMake导出的原文许可超集，加OpenCV主许可与未自动导出的WebP版权；超集不表示所有列名库均编入。',
               'acceptance': '此封装不代替各实际消费者、归档重装和最终组件验收。'}
    input_files = [*files.values(), *licensing.values(), source / 'LICENSE', source / '3rdparty/libwebp/COPYING']
    if len(input_files) > 20000 or any(path.stat().st_size > 64 * 1024**2 for path in input_files) or sum(path.stat().st_size for path in input_files) > 120 * 1024**2:
        raise ValueError('封装前检查发现输入超过大小/数量预算')
    payload = {'cv2/' + name: path.read_bytes() for name, path in files.items()}
    # 内部静态链接，无需从包外的bin加载原版OpenCV DLL。
    payload['cv2/config.py'] = '# Umi运行派生：内部静态链接，无额外BINARIES_PATHS。\n'.encode('utf-8')
    metadata = ('Metadata-Version: 2.4\nName: opencv-contrib-python\nVersion: ' + VERSION + '\n'
                'Summary: Umi-OCR派生core/imgproc/imgcodecs运行子集，非官方完整contrib\n'
                'Requires-Python: >=3.13.16,<3.14\nRequires-Dist: numpy==2.3.5\n'
                'License: OpenCV及实际静态编解码组件原始许可，见licenses和UMI_RUNTIME_PROFILE.json\n\n'
                '本派生构件不提供官方opencv-contrib-python的完整接口。仅供已验证的Umi-OCR图像消费者。\n')
    payload[DIST + '/METADATA'] = metadata.encode('utf-8')
    payload[DIST + '/WHEEL'] = b'Wheel-Version: 1.0\nGenerator: umi-runtime-builder-1\nRoot-Is-Purelib: false\nTag: cp313-cp313-win_amd64\n'
    payload[DIST + '/top_level.txt'] = b'cv2\n'
    runtime_profile = {key: profile[key] for key in ('format', 'version', 'distribution', 'upstreamLibraryVersion', 'scope', 'compatibilityDistributionNameReason', 'sourceCommit', 'nativeSha256', 'numpyRequirement')}
    runtime_profile['modules'] = ['core', 'imgproc', 'imgcodecs', 'python3']
    runtime_profile['sourceUrl'] = 'https://github.com/opencv/opencv/tree/' + build['sourceCommit']
    runtime_profile['sourceGuide'] = '完整对应源码和构建材料随Umi-OCR组件在运行包外独立提供；不把内部审计或本机构建路径放入运行wheel。'
    payload[DIST + '/UMI_RUNTIME_PROFILE.json'] = (json.dumps(runtime_profile, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')
    for name, path in licensing.items():
        payload[DIST + '/licenses/' + name] = path.read_bytes()
    payload[DIST + '/licenses/OpenCV-LICENSE'] = (source / 'LICENSE').read_bytes()
    payload[DIST + '/licenses/libwebp-COPYING'] = (source / '3rdparty/libwebp/COPYING').read_bytes()
    if len(payload) > 20000 or sum(map(len, payload.values())) > 128 * 1024**2:
        raise ValueError('派生wheel超过有限预算')
    rows = io.StringIO(newline=''); writer = csv.writer(rows, lineterminator='\n')
    binding = {}
    for name, data in sorted(payload.items()):
        L.canonical_relative(name)
        digest = hashlib.sha256(data).digest()
        binding[name] = digest.hex()
        writer.writerow([name, 'sha256=' + base64.urlsafe_b64encode(digest).rstrip(b'=').decode('ascii'), len(data)])
    writer.writerow([DIST + '/RECORD', '', ''])
    payload[DIST + '/RECORD'] = rows.getvalue().encode('utf-8')
    output.mkdir(parents=True, exist_ok=False)
    archive = output / WHEEL_NAME
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as wheel:
        for name, data in sorted(payload.items()):
            entry = zipfile.ZipInfo(name, date_time=(2024, 6, 2, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            wheel.writestr(entry, data, compresslevel=6)
    with zipfile.ZipFile(archive) as wheel:
        if set(wheel.namelist()) != set(payload):
            raise ValueError('构件成员集合不符')
        for name, data in payload.items():
            if wheel.read(name) != data:
                raise ValueError('构件封装字节不符：' + name)
    record = {'status': 'PACKAGED_NOT_FINAL_ACCEPTED', 'createdUtc': datetime.now(timezone.utc).isoformat(),
              'producerSha256': sha(Path(__file__)), 'wheel': str(archive), 'wheelSha256': sha(archive),
              'wheelBytes': archive.stat().st_size, 'payload': binding, 'profile': profile,
              'officialWheelHashReused': False, 'fixedInstallationChanged': False}
    with receipt.open('x', encoding='utf-8') as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-record', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args()
    record = package(args.build_record, args.output, args.receipt)
    print(json.dumps({key: value for key, value in record.items() if key not in {'payload', 'profile'}}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
