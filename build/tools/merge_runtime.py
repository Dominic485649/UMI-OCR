"""Merge compatible runtime modules into Stored ZIP and QML resources into RCC.
Native files and modules requiring a real __file__ remain on disk. No extractor.
"""
import argparse
import ast
import hashlib
import importlib._bootstrap_external as bytecode
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import zipfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def merge_modules(root, archive, whole=False, keep=()):
    root, archive = Path(root), Path(archive)
    if archive.exists():
        raise FileExistsError(archive)
    files = sorted(root.rglob("*.py"))
    # These packages explicitly enumerate disk files or load native modules.
    keep_packages = {"PySide6", "shiboken6", "cv2", "numpy", "PIL", "pymupdf", "fitz", "paddle", "onnxruntime", "scipy", "sklearn", "skimage", "pandas"}
    keep_packages.update(keep)
    records, moved, dirs = {}, [], set()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as z:
        for path in files:
            rel = path.relative_to(root)
            data = path.read_bytes()
            if not whole and (path.name == "__init__.py" or "__file__" in data.decode("utf-8", errors="ignore") or rel.parts[0] in keep_packages):
                continue
            try:
                code = compile(data, rel.as_posix(), "exec", dont_inherit=True)
            except (SyntaxError, ValueError):
                continue
            name = rel.as_posix()
            z.writestr(zipfile.ZipInfo(name, (1980,1,1,0,0,0)), data)
            z.writestr(zipfile.ZipInfo(name[:-3]+".pyc", (1980,1,1,0,0,0)), bytecode._code_to_hash_pyc(code, importlib.util.source_hash(data), checked=True))
            records[name] = digest(data)
            moved.append(path)
            dirs.update(parent.as_posix()+"/" for parent in rel.parents if str(parent) != ".")
        for directory in sorted(dirs):
            z.writestr(directory, b"")
    # Verify the exact original source bytes before removing individual files.
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for name, expected in records.items():
            assert digest(z.read(name)) == expected
    patched = {}
    original_initializers = {}
    if not whole:
        for path in files:
            if path.name != "__init__.py":
                continue
            rel = path.parent.relative_to(root)
            if rel.as_posix()+"/" not in dirs:
                continue
            original = path.read_bytes()
            text = original.decode("utf-8-sig")
            tree = ast.parse(text)
            insertion = 0
            for node in tree.body:
                if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value,str)) or (isinstance(node,ast.ImportFrom) and node.module == "__future__"):
                    insertion = node.end_lineno
                else:
                    break
            lines = text.splitlines(keepends=True)
            relative = os.path.relpath(archive, path.parent).replace("\\", "/")
            extension = relative + ("/"+rel.as_posix() if str(rel) != "." else "")
            lines.insert(insertion, "\n# Umi-OCR distribution: load compatible modules directly from Stored ZIP.\n__path__.append(__import__('os').path.abspath(__import__('os').path.join(__import__('os').path.dirname(__file__), "+repr(extension)+")))\n")
            original_initializers["__original__/"+path.relative_to(root).as_posix()] = original
            patched[path.relative_to(root).as_posix()] = {"original_sha256": digest(original)}
            path.write_text("".join(lines),encoding="utf-8")
    with zipfile.ZipFile(archive,"a") as originals:
        for name,data in original_initializers.items(): originals.writestr(name,data)
    for path in moved:
        path.unlink()
    for cache in root.rglob("__pycache__"):
        import shutil
        shutil.rmtree(cache)
    for directory in sorted(root.rglob("*"),key=lambda p:len(p.parts),reverse=True):
        if directory.is_dir() and not any(directory.iterdir()): directory.rmdir()
    return {"archive":str(archive.name), "python":sys.version.split()[0], "compression":"Stored", "source_hashes":records, "package_paths":patched, "merged_files":len(moved)}


def merge_resources(root, archive, prefix, rcc):
    from xml.etree import ElementTree as ET
    root, archive = Path(root), Path(archive)
    files = sorted(p for p in root.rglob("*") if p.is_file()) if root.is_dir() else [root]
    qrc = archive.with_suffix(".qrc")
    xml = ET.Element("RCC"); resource=ET.SubElement(xml,"qresource",prefix="/")
    hashes = {}
    for p in files:
        alias = prefix+"/"+(p.relative_to(root).as_posix() if root.is_dir() else p.name)
        ET.SubElement(resource,"file",alias=alias).text=str(p.resolve())
        hashes[alias]=digest(p.read_bytes())
    ET.ElementTree(xml).write(qrc,encoding="utf-8",xml_declaration=True)
    subprocess.run([str(rcc),"--binary","--no-compress",str(qrc),"-o",str(archive)],check=True)
    from PySide6.QtCore import QResource, QFile
    assert QResource.registerResource(str(archive.resolve()))
    for alias, expected in hashes.items():
        f=QFile(":"+"/"+alias); assert f.open(QFile.ReadOnly),alias
        assert digest(bytes(f.readAll())) == expected,alias
        f.close()
    QResource.unregisterResource(str(archive.resolve()))
    qrc.unlink()
    for p in files:p.unlink()
    if root.is_dir():
        import shutil
        shutil.rmtree(root)
    return {"archive":archive.name,"resource_hashes":hashes,"merged_files":len(files)}


def main():
    p=argparse.ArgumentParser();p.add_argument("root",type=Path);p.add_argument("--kind",choices=("host","plugin"),required=True);p.add_argument("--rcc",type=Path);p.add_argument("--keep-package",action="append",default=[]);args=p.parse_args()
    if args.rcc: sys.path.insert(0,str(args.rcc.resolve().parent.parent))
    root=args.root.resolve(); before=sum(p.is_file() for p in root.rglob("*"));records=[]
    if args.kind == "host":
        sys.path.insert(0,str(root/"site-packages"))
        records.append(merge_modules(root/"py_src",root/"app.zip",whole=True))
        # py_src was a namespace rooted one level higher.
        with zipfile.ZipFile(root/"app.zip") as old: entries=[(i,old.read(i.filename)) for i in old.infolist()]
        with zipfile.ZipFile(root/"app.zip","w",compression=zipfile.ZIP_STORED) as z:
            z.writestr("py_src/",b"")
            for info,data in entries:info.filename="py_src/"+info.filename;z.writestr(info,data)
        records[0]["source_hashes"]={"py_src/"+name:value for name,value in records[0]["source_hashes"].items()}
        records.append(merge_modules(root/"site-packages",root/"dependencies.zip"))
        if args.rcc: records.append(merge_resources(root/"qt_res",root/"ui.rcc","qt_res",args.rcc))
    else:
        records.append(merge_modules(root/"vendor",root/"vendor.zip",keep=args.keep_package))
        manifest=root/"umi-plugin.json";m=json.loads(manifest.read_text("utf-8-sig"))
        # ZIP is private to the worker; the host must never mount it.
        m["runtime"]["worker_archives"]=["vendor.zip"]
        if args.rcc and (root/"StructuredDocument.qml").exists():
            records.append(merge_resources(root/"StructuredDocument.qml",root/"resources.rcc","plugins/"+m["id"],args.rcc))
            m["runtime"]["resource_archives"]=["resources.rcc"]
        manifest.write_text(json.dumps(m,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    report={"before_files":before,"after_files":sum(p.is_file() for p in root.rglob("*"))+1,"records":records}
    (root/"archive-layout.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k != "records"}))

if __name__ == "__main__":main()
