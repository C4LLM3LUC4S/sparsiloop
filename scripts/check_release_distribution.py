"""Check the two files embedded into a curated release, without extraction."""
from email.parser import BytesParser
import gzip
import io
from pathlib import Path
import tarfile
import zipfile

from event_control_lab import __version__


def check(distributions, source):
    stem = f"sparsiloop-{__version__}"
    with zipfile.ZipFile(distributions / f"{stem}-py3-none-any.whl") as package:
        if package.testzip():
            raise ValueError("Wheel CRC mismatch")
        metadata = BytesParser().parsebytes(package.read(f"{stem}.dist-info/METADATA"))
        if metadata["Version"] != __version__ or metadata.get_all("Requires-Dist", []):
            raise ValueError("Unexpected version or core runtime dependency")
        for path in (source / "event_control_lab").rglob("*"):
            if path.is_file() and path.suffix in {".py", ".js", ".css", ".html"}:
                if package.read(path.relative_to(source).as_posix()) != path.read_bytes():
                    raise ValueError(f"Wheel source differs: {path.name}")
    payload = gzip.decompress((distributions / f"{stem}.tar.gz").read_bytes())
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as package:
        names = set(package.getnames())
        for name in ("LICENSE", "START_HERE.md", "quickstart.py", "docs/source-recovery.md", "pyproject.toml"):
            if f"{stem}/{name}" not in names:
                raise ValueError(f"Source archive missing {name}")
        for member in package.getmembers():
            path = Path(member.name)
            if path.is_absolute() or ".." in path.parts or not (member.isfile() or member.isdir()):
                raise ValueError("Unsafe source archive entry")
