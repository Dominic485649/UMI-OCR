"""Create and verify real two-layer ``tar.xz`` archives.

The helper deliberately keeps archive policy in one place.  The input root is
never emitted as a leading directory: extracting an archive recreates the
contents of ``--root`` directly.  The inner layer is POSIX tar and the outer
layer is an xz stream using the standard LZMA2 method.  7-Zip is used for the
outer layer because it is the tool used by the Windows release environment;
its LZMA2 support is probed on a tiny temporary file before a real archive is
written.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import tempfile
from typing import Iterable


class ArchiveError(RuntimeError):
    """Raised when an archive cannot be created or verified."""


def _resolve(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _safe_relative(path: str) -> str:
    """Return a validated POSIX member name."""
    value = path.replace("\\", "/")
    pure = PurePosixPath(value)
    if not value or value == "." or value.startswith("/") or ".." in pure.parts or any(":" in part for part in pure.parts):
        raise ArchiveError(f"unsafe archive member path: {path!r}")
    return pure.as_posix()


def _iter_children(root: Path) -> Iterable[Path]:
    # Sorting at each level gives stable member ordering without following
    # symlinked directories.  Symlinks are represented as symlinks in tar.
    return sorted(root.iterdir(), key=lambda item: item.name.casefold())


def _tar_filter(info: tarfile.TarInfo) -> tarfile.TarInfo:
    # Do not retain host-specific ownership in a portable release archive.
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    return info


def _write_tar(root: Path, target: Path) -> int:
    members = 0
    with tarfile.open(target, mode="w", format=tarfile.PAX_FORMAT) as archive:
        def add(path: Path, relative: str) -> None:
            nonlocal members
            # tarfile.add does not follow symlinks by default.  The explicit
            # arcname is what prevents a staging-directory prefix.
            archive.add(path, arcname=relative, recursive=False, filter=_tar_filter)
            members += 1
            if path.is_dir() and not path.is_symlink():
                for child in _iter_children(path):
                    child_name = f"{relative}/{child.name}" if relative else child.name
                    add(child, _safe_relative(child_name))

        for child in _iter_children(root):
            add(child, _safe_relative(child.name))
    return members


def _run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, check=False)


def _find_sevenzip(requested: str | None) -> str:
    if requested:
        candidate = requested
    else:
        candidate = shutil.which("7z.exe") or shutil.which("7z")
    if not candidate:
        raise ArchiveError("7z.exe/7z is required for the xz outer layer")
    return candidate


def _probe_lzma2(sevenzip: str, directory: Path) -> None:
    """Probe the exact method before using it for a release archive."""
    source = directory / "xz-method-probe.txt"
    output = directory / "xz-method-probe.xz"
    source.write_bytes(b"Umi-OCR tar.xz method probe\n")
    result = _run([sevenzip, "a", "-y", "-txz", "-m0=lzma2", str(output), str(source)])
    if result.returncode != 0:
        raise ArchiveError("7z did not accept the probed xz LZMA2 method:\n" + result.stdout)
    result = _run([sevenzip, "t", str(output)])
    if result.returncode != 0:
        raise ArchiveError("7z LZMA2 probe did not round-trip:\n" + result.stdout)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_tar_members(archive_path: Path) -> list[tarfile.TarInfo]:
    try:
        # lzma.open reads the xz outer layer; tarfile then sees the raw inner
        # tar stream.  This also proves the archive is not merely renamed 7z.
        with lzma.open(archive_path, mode="rb") as stream:
            with tarfile.open(fileobj=stream, mode="r:") as archive:
                members = archive.getmembers()
    except (OSError, EOFError, tarfile.TarError, lzma.LZMAError) as exc:
        raise ArchiveError(f"not a readable tar.xz archive: {archive_path}: {exc}") from exc
    names: set[str] = set()
    for member in members:
        name = _safe_relative(member.name)
        if name in names:
            raise ArchiveError(f"duplicate archive member: {name}")
        names.add(name)
        if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
            raise ArchiveError(f"unsupported archive member type: {name}")
        if member.linkname and member.issym():
            # A symlink target may be relative, but must not escape the root.
            target = PurePosixPath(name).parent / member.linkname.replace("\\", "/")
            if target.is_absolute() or ".." in target.parts or any(":" in part for part in target.parts):
                raise ArchiveError(f"unsafe symlink target: {member.name} -> {member.linkname}")
        if member.islnk():
            _safe_relative(member.linkname)
    return members


def verify_archive(archive_path: Path, sevenzip: str | None = None) -> dict[str, object]:
    archive_path = _resolve(archive_path)
    if not archive_path.is_file():
        raise ArchiveError(f"archive does not exist: {archive_path}")
    if sevenzip:
        result = _run([sevenzip, "t", str(archive_path)])
        if result.returncode != 0:
            raise ArchiveError("7z archive integrity test failed:\n" + result.stdout)
    members = _read_tar_members(archive_path)
    return {
        "archive": str(archive_path),
        "format": "tar.xz",
        "outer_method": "LZMA2",
        "member_count": len(members),
        "bytes": archive_path.stat().st_size,
        "sha256": _sha256(archive_path),
    }


def create_archive(root: Path, output: Path, sevenzip: str | None = None) -> dict[str, object]:
    if output.exists() or output.is_symlink():
        raise ArchiveError(f"refusing to overwrite existing archive: {output}")
    root = _resolve(root)
    output = _resolve(output)
    if not root.is_dir():
        raise ArchiveError(f"archive root is not a directory: {root}")
    if output.exists():
        raise ArchiveError(f"refusing to overwrite existing archive: {output}")
    if output == root or root in output.parents:
        raise ArchiveError("archive output must not be inside its input root")
    output.parent.mkdir(parents=True, exist_ok=True)
    candidates = [sevenzip] if sevenzip else list(dict.fromkeys(filter(None, [
        shutil.which("7z.exe"), shutil.which("7z"),
        *[str(Path(part) / "7z.exe") for part in os.environ.get("PATH", "").split(os.pathsep) if part],
        str(Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "7-Zip/7z.exe"),
        str(Path.home() / "scoop/apps/7zip/current/7z.exe"),
    ])))
    with tempfile.TemporaryDirectory(prefix="umi-ocr-tar-xz-") as temporary:
        temporary_path = Path(temporary)
        failures = []
        sevenzip_path = None
        for index, candidate in enumerate(candidates):
            if not candidate or not (Path(candidate).is_file() or shutil.which(candidate)):
                continue
            probe_dir = temporary_path / f"probe-{index}"
            probe_dir.mkdir()
            try:
                _probe_lzma2(candidate, probe_dir)
            except ArchiveError as exc:
                failures.append(str(exc))
            else:
                sevenzip_path = candidate
                break
        if not sevenzip_path:
            print("Installed 7-Zip cannot write standard xz/LZMA2; using Python's existing standard LZMA2 implementation (no download).", file=sys.stderr)
        inner_tar = temporary_path / "payload.tar"
        member_count = _write_tar(root, inner_tar)
        temporary_archive = temporary_path / "payload.tar.xz"
        if sevenzip_path:
            command = _run([sevenzip_path, "a", "-y", "-txz", "-m0=lzma2", str(temporary_archive), str(inner_tar)])
            if command.returncode != 0:
                raise ArchiveError("7z tar.xz creation failed:\n" + command.stdout)
        else:
            with inner_tar.open("rb") as source, lzma.open(temporary_archive, "xb", format=lzma.FORMAT_XZ) as destination:
                shutil.copyfileobj(source, destination, length=1024 * 1024)
        result = verify_archive(temporary_archive, sevenzip_path)
        with temporary_archive.open("rb") as source, output.open("xb") as destination:
            shutil.copyfileobj(source, destination, length=1024 * 1024)
        if _sha256(output) != result["sha256"]:
            raise ArchiveError("archive changed while copying to its new output")
    result["archive"] = str(output)
    result["compressor"] = "sevenzip-standard-lzma2" if sevenzip_path else "python-stdlib-standard-lzma2"
    result["root"] = str(root)
    result["member_count"] = member_count
    return result


def _write_integrity(path: Path, result: dict[str, object]) -> None:
    if path.exists() or path.is_symlink():
        raise ArchiveError(f"refusing to overwrite integrity report: {path}")
    path = _resolve(path)
    if path.exists():
        raise ArchiveError(f"refusing to overwrite integrity report: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create", help="create and verify a tar.xz archive")
    create.add_argument("--root", required=True, type=Path)
    create.add_argument("--output", required=True, type=Path)
    create.add_argument("--sevenzip", default=None)
    create.add_argument("--integrity-output", type=Path, default=None)
    test = subparsers.add_parser("test", help="verify a tar.xz archive")
    test.add_argument("--archive", required=True, type=Path)
    test.add_argument("--sevenzip", default=None)
    test.add_argument("--integrity-output", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        if args.integrity_output and (args.integrity_output.exists() or args.integrity_output.is_symlink()):
            raise ArchiveError(f"refusing to overwrite integrity report: {args.integrity_output}")
        if args.command == "create":
            result = create_archive(args.root, args.output, args.sevenzip)
        else:
            result = verify_archive(args.archive, _find_sevenzip(args.sevenzip))
        if args.integrity_output:
            _write_integrity(args.integrity_output, result)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (ArchiveError, OSError, tarfile.TarError) as exc:
        print(f"archive error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
