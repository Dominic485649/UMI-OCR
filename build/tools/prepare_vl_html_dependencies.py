"""补齐官方跨页表格重组的纯 Python 依赖；只下载已锁定 wheel，不触碰模型。"""
from __future__ import annotations
import argparse
from email.parser import BytesParser
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT.parent / 'Umi-OCR-Plugin'
PINS = [
    {'name': 'beautifulsoup4', 'version': '4.15.0', 'filename': 'beautifulsoup4-4.15.0-py3-none-any.whl',
     'size': 109924, 'sha256': 'd6f88de62e1d4e38ecb1077eb9724cd0eff29d2a08ca16a401e9b9e93f117cf9',
     'url': 'https://files.pythonhosted.org/packages/88/c6/92fcd42f1ba33e1184263f25bfabf3d27c383410470f169e4b8163bf9c17/beautifulsoup4-4.15.0-py3-none-any.whl'},
    {'name': 'soupsieve', 'version': '3.0.4', 'filename': 'soupsieve-3.0.4-py3-none-any.whl',
     'size': 42458, 'sha256': '8412826614f9c632227067d0985aeb9f584bd15efc852955430e097a9fe7afbf',
     'url': 'https://files.pythonhosted.org/packages/07/66/473f7ca0be0b06e38ee8c85ee2db184e3981bd769fac2e7c19c8a8865211/soupsieve-3.0.4-py3-none-any.whl'},
]


def safe(path, boundary):
    path = path.absolute()
    path.relative_to(boundary)
    if any(node.is_symlink() or node.is_junction() for node in (path, *path.parents)):
        raise ValueError('拒绝链接下载路径')
    if path.exists():
        raise FileExistsError(path)
    return path


def fetch(url, limit):
    with urlopen(Request(url, headers={'User-Agent': 'Umi-OCR-local-dependency-build'}), timeout=60) as response:
        target = urlparse(response.geturl())
        if target.scheme != 'https' or target.hostname not in {'pypi.org', 'files.pythonhosted.org'}:
            raise ValueError('依赖下载重定向到未授权来源')
        content = response.read(limit + 1)
        if len(content) > limit:
            raise ValueError('依赖输入超过有限下载预算')
        return content


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--audit', type=Path, required=True)
    args = parser.parse_args()
    output = safe(args.output, PLUGIN / 'build/cache')
    audit = safe(args.audit, ROOT / 'build/audit')
    output.mkdir()
    records = []
    for pin in PINS:
        directory = output / (pin['name'] + '-' + pin['version'])
        directory.mkdir()
        raw_metadata = fetch(f"https://pypi.org/pypi/{pin['name']}/{pin['version']}/json", 1024 * 1024)
        with (directory / 'pypi-metadata.json').open('xb') as stream:
            stream.write(raw_metadata)
        metadata = json.loads(raw_metadata)
        file = next(item for item in metadata['urls'] if item['filename'] == pin['filename'])
        if file['digests']['sha256'] != pin['sha256'] or file['size'] != pin['size'] or file['url'] != pin['url']:
            raise ValueError('PyPI 原始元数据与已审锁定输入不符')
        content = fetch(pin['url'], 2 * 1024 * 1024)
        if len(content) != pin['size'] or hashlib.sha256(content).hexdigest() != pin['sha256']:
            raise ValueError('wheel 内容校验失败')
        wheel = directory / pin['filename']
        with wheel.open('xb') as stream:
            stream.write(content)
        licenses = {}
        with zipfile.ZipFile(wheel) as archive:
            for info in archive.infolist():
                parts = info.filename.split('/')
                if info.filename.startswith('/') or any(part in {'.', '..'} or ':' in part or '\\' in part for part in parts):
                    raise ValueError('不安全 wheel 成员')
            if archive.testzip() is not None:
                raise ValueError('wheel CRC 验证失败')
            name = next(name for name in archive.namelist() if name.endswith('.dist-info/METADATA'))
            headers = BytesParser().parsebytes(archive.read(name))
            if headers['Version'] != pin['version'] or headers['Name'].lower() != pin['name']:
                raise ValueError('wheel 元数据身份不一致')
            for name in archive.namelist():
                if not name.endswith('/') and name.rsplit('/', 1)[-1].upper().startswith(('LICENSE', 'COPYING')):
                    data = archive.read(name)
                    target = directory / ('license-' + str(len(licenses)) + '.txt')
                    with target.open('xb') as stream:
                        stream.write(data)
                    licenses[name] = {'sha256': hashlib.sha256(data).hexdigest(), 'retainedAt': str(target)}
        if not licenses:
            raise ValueError('wheel 缺少原始许可材料')
        records.append({**pin, 'wheel': str(wheel), 'requiresPython': headers['Requires-Python'],
            'requiresDist': headers.get_all('Requires-Dist') or [], 'licenses': licenses})
    report = {'status': 'PASS', 'packages': records, 'modelsDownloaded': False, 'quantizationChanged': False,
        'scope': '仅新增公开纯 Python 依赖及原始元数据/许可；构建随后离线运行，不执行下载目录中的脚本。'}
    with audit.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps({'status': 'PASS', 'packages': [record['name'] for record in records], 'output': str(output)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
