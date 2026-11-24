"""按目标环境、RECORD文件并集和运行容器测量真实依赖闭包；默认只读。"""
from __future__ import annotations
import argparse
import csv
from datetime import datetime, timezone
from dataclasses import dataclass, field
import hashlib
from email.parser import Parser
import io
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version


def safe_name(name: str) -> str:
    if not isinstance(name, str) or not name or '\\' in name or ':' in name or name.startswith('/'):
        raise ValueError('非法相对文件名：'+repr(name))
    if any(part in {'','.','..'} or part.endswith((' ','.')) for part in name.split('/')):
        raise ValueError('路径越界或别名：'+repr(name))
    return name


def plain(path: Path) -> Path:
    path=path.absolute()
    for part in (path,*path.parents):
        if part.is_symlink() or part.is_junction(): raise ValueError('拒绝链接或junction：'+str(part))
    return path


@dataclass(frozen=True)
class Entry:
    name: str
    bytes: int
    carrier: str
    compressed_bytes: int
    path: Path | None = None
    archive: Path | None = None


class FileIndex:
    """以导入根的相对文件名统一磁盘与ZIP成员，不重复累计同一文件。"""
    def __init__(self, root: Path, archives: list[Path] | None = None):
        self.root=plain(root);self.files:dict[str,Entry]={};self.carriers:dict[str,int]={};self._keys:set[str]=set()
        if not self.root.is_dir(): raise ValueError('导入根不存在：'+str(root))
        import os
        for folder,dirs,names in os.walk(self.root,followlinks=False):
            for name in dirs: plain(Path(folder)/name)
            for name in names:
                path=plain(Path(folder)/name)
                if not path.is_file(): raise ValueError('不是普通文件：'+str(path))
                rel=safe_name(path.relative_to(self.root).as_posix());size=path.stat().st_size
                self._add(Entry(rel,size,str(path),size,path=path));self.carriers[str(path)]=size
        for path in archives or []:
            path=plain(path);self.carriers[str(path)]=path.stat().st_size
            with zipfile.ZipFile(path) as archive:
                members=archive.infolist()
                if len(members)>100000: raise ValueError('ZIP成员数量超出预算')
                total=0
                for member in members:
                    if member.is_dir(): continue
                    rel=safe_name(member.filename)
                    if stat.S_ISLNK(member.external_attr>>16): raise ValueError('ZIP中含符号链接')
                    total+=member.file_size
                    if member.file_size>512*1024**2 or total>4*1024**3: raise ValueError('ZIP内容超出预算')
                    self._add(Entry(rel,member.file_size,str(path),member.compress_size,archive=path))

    def _add(self,entry:Entry):
        key=entry.name.casefold()
        if key in self._keys:
            raise ValueError('导入根存在重复或大小写别名：'+entry.name)
        if len(self.files)>=1000000: raise ValueError('导入根文件数量超出预算')
        self._keys.add(key);self.files[entry.name]=entry

    def read(self,name:str,limit:int=8*1024**2)->bytes:
        entry=self.files[safe_name(name)]
        if entry.bytes>limit: raise ValueError('元数据超出读取预算：'+name)
        if entry.path is not None: return entry.path.read_bytes()
        with zipfile.ZipFile(entry.archive) as archive:
            with archive.open(name) as source:
                data=source.read(limit+1)
        if len(data)>limit: raise ValueError('ZIP元数据超出读取预算')
        return data


@dataclass
class Distribution:
    name:str
    version:str
    metadata:str
    requirements:list[Requirement]=field(default_factory=list)
    files:set[str]=field(default_factory=set)
    missing_record_files:list[str]=field(default_factory=list)
    outside_record_files:list[str]=field(default_factory=list)


def distributions(index:FileIndex)->dict[str,Distribution]:
    result={}
    for name in sorted(index.files):
        # 仅导入根直接安装的发行版；setuptools等内部vendored元数据不是独立根发行版。
        if len(PurePosixPath(name).parts)!=2 or not name.endswith('.dist-info/METADATA'): continue
        prefix=name.rsplit('/',1)[0]
        metadata=Parser().parsestr(index.read(name).decode('utf-8','replace'),headersonly=True)
        original=metadata.get('Name');version=metadata.get('Version')
        if not original or not version: raise ValueError('发行版缺少名称或版本：'+name)
        key=canonicalize_name(original)
        if key in result: raise ValueError('发行版元数据重复：'+key)
        Version(version)
        dist=Distribution(key,version,name,[Requirement(value) for value in metadata.get_all('Requires-Dist',[])])
        record=prefix+'/RECORD'
        if record in index.files:
            for row in csv.reader(io.StringIO(index.read(record,32*1024**2).decode('utf-8','replace'))):
                if not row: continue
                rel=row[0]
                try: safe_name(rel)
                except ValueError:
                    dist.outside_record_files.append(rel);continue
                if rel in index.files: dist.files.add(rel)
                else: dist.missing_record_files.append(rel)
        # 某些旧裁切载荷缺少RECORD；只归属其自身元数据，不猜测整个顶层命名空间。
        dist.files.update(p for p in index.files if p.startswith(prefix+'/'))
        result[key]=dist
    return result


def target_environment(python_version='3.13.16',system='Windows',machine='AMD64')->dict[str,str]:
    parts=python_version.split('.')
    if len(parts)!=3 or not all(part.isdigit() for part in parts): raise ValueError('必须指定完整目标Python版本')
    environment=default_environment()
    environment.update(python_version='.'.join(parts[:2]),python_full_version=python_version,
        implementation_version=python_version,implementation_name='cpython',platform_python_implementation='CPython',
        platform_system=system,platform_machine=machine,sys_platform='win32' if system=='Windows' else 'linux' if system=='Linux' else 'darwin',
        os_name='nt' if system=='Windows' else 'posix')
    return environment


def resolve(dists:dict[str,Distribution],roots:list[str],environment:dict[str,str]):
    requested:dict[str,set[str]]={};pending=[Requirement(root) for root in roots]
    processed:dict[str,frozenset[str]]={};edges=[];issues=[]
    while pending:
        requirement=pending.pop(0);name=canonicalize_name(requirement.name)
        if requirement.marker and not requirement.marker.evaluate({**environment,'extra':''}): continue
        if name not in dists:
            issue={'type':'missing-distribution','requirement':str(requirement)}
            if issue not in issues: issues.append(issue)
            continue
        dist=dists[name]
        if requirement.specifier and Version(dist.version) not in requirement.specifier:
            issue={'type':'version-mismatch','requirement':str(requirement),'installed':dist.version}
            if issue not in issues: issues.append(issue)
        extras=requested.setdefault(name,set());extras.update(canonicalize_name(x) for x in requirement.extras)
        frozen=frozenset(extras)
        if processed.get(name)==frozen: continue
        processed[name]=frozen
        for child in dist.requirements:
            if child.marker and not any(child.marker.evaluate({**environment,'extra':extra}) for extra in {''}|extras): continue
            edge={'from':name,'to':canonicalize_name(child.name),'requirement':str(child)}
            if edge not in edges: edges.append(edge)
            # marker已经在父发行版extra上下文判定，不能在子上下文再次误判。
            bare=Requirement(str(child).split(';',1)[0].strip());pending.append(bare)
    return set(processed),requested,edges,issues


def report(index:FileIndex,roots:list[str],environment:dict[str,str]):
    dists=distributions(index);selected,extras,edges,issues=resolve(dists,roots,environment)
    owners:dict[str,set[str]]={}
    for name,dist in dists.items():
        for path in dist.files: owners.setdefault(path,set()).add(name)
    selected_files=set().union(*(dists[name].files for name in selected)) if selected else set()
    other_files=set(index.files)-selected_files
    candidates=other_files & set(owners)
    # 共享文件只要被任何必要发行版拥有，就不归入删除候选。
    orphan_distributions=[]
    for name,dist in sorted(dists.items()):
        if name not in selected:
            exclusive=dist.files-selected_files
            orphan_distributions.append({'name':name,'version':dist.version,'recordFiles':len(dist.files),
                'exclusiveFiles':len(exclusive),'exclusiveLogicalBytes':sum(index.files[p].bytes for p in exclusive)})
    selected_records=[{'name':name,'version':dists[name].version,'extras':sorted(extras[name]),
        'recordFiles':len(dists[name].files),'missingRecordFiles':len(dists[name].missing_record_files),
        'outsideRecordFiles':len(dists[name].outside_record_files)} for name in sorted(selected)]
    with Path(__file__).open('rb') as source: producer_sha=hashlib.file_digest(source,'sha256').hexdigest()
    return {'schemaVersion':1,'createdUtc':datetime.now(timezone.utc).isoformat(),'producerSha256':producer_sha,'root':str(index.root),'roots':roots,'targetEnvironment':environment,
        'selectedDistributions':selected_records,'metadataOrphans':orphan_distributions,'edges':edges,'issues':issues,
        'allFiles':len(index.files),'allLogicalBytes':sum(e.bytes for e in index.files.values()),
        'selectedFiles':len(selected_files),'selectedLogicalBytes':sum(index.files[p].bytes for p in selected_files),
        'carrierBytes':sum(index.carriers.values()),'unownedFiles':sorted(set(index.files)-set(owners)),
        'metadataCandidateFiles':sorted(candidates),'metadataCandidateLogicalBytes':sum(index.files[p].bytes for p in candidates),
        'boundary':'元数据闭包不是最终删除依据；还须结合Python/QML实际调用、普通/延迟导入、动态DLL/插件与资源、模型配置及运行证据。ZIP成员逻辑字节与物理载体字节分列，不把ZIP聚合当作回收。RECORD缺失项不自动补回或静默忽略。'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--archive',type=Path,action='append',default=[])
    parser.add_argument('--require',action='append',required=True);parser.add_argument('--python-version',default='3.13.16')
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    output=plain(args.output)
    if output.exists() or not output.parent.is_dir(): raise ValueError('输出须为已有父目录下的新文件')
    result=report(FileIndex(args.root,args.archive),args.require,target_environment(args.python_version))
    with output.open('x',encoding='utf-8') as stream: json.dump(result,stream,ensure_ascii=False,indent=2)
    print(json.dumps({k:result[k] for k in ('root','allFiles','allLogicalBytes','selectedFiles','selectedLogicalBytes','metadataCandidateLogicalBytes','issues')},ensure_ascii=False,indent=2))

if __name__=='__main__': main()
