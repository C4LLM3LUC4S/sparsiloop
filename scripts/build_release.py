"""Build a curated offline release from committed SparsiLoop source only."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import zipfile

from check_release_distribution import check


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "C4LLM3LUC4S/sparsiloop"
ALLOWED_ROOT_FILES = {
    ".gitattributes", ".gitignore", "CHANGELOG.md", "CITATION.cff",
    "CONTRIBUTING.md", "LICENSE", "MANIFEST.in", "README.md", "README.en.md", "BRANDING.md",
    "README.zh-CN.md", "pyproject.toml", "START_HERE.md", "quickstart.py",
}
ALLOWED_DIRECTORIES = {".github", "docs", "examples", "scripts", "event_control_lab", "integration_tests", "tests"}
ALLOWED_SUFFIXES = {".md", ".py", ".txt", ".csv", ".jsonl", ".run", ".trec", ".qrels", ".tsv", ".yml", ".json", ".html", ".js", ".css"}


def git(*arguments):
    return subprocess.check_output(["git", *arguments], cwd=ROOT)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()


def committed_source():
    top = Path(git("rev-parse", "--show-toplevel").decode().strip()).resolve()
    prefix = ROOT.relative_to(top).as_posix()
    prefix = "" if prefix == "." else prefix + "/"
    scope = prefix.rstrip("/") or "."
    if git("status", "--porcelain", "--untracked-files=no", "--", ".").strip():
        raise ValueError("Commit tracked package changes before building a release")
    members = {}
    listing = git("ls-tree", "-rz", "--full-tree", "HEAD", "--", scope)
    for entry in listing.split(b"\0"):
        if not entry:
            continue
        header, raw_path = entry.split(b"\t", 1)
        mode, kind, sha = header.decode().split()
        name = raw_path.decode("utf-8")
        if not name.startswith(prefix):
            raise ValueError("Source is outside the package")
        relative = PurePosixPath(name[len(prefix):])
        if str(relative) in {"PROJECT_STATUS.md", "STATUS.json"}:
            continue
        if mode not in {"100644", "100755"} or kind != "blob":
            raise ValueError(f"Non-regular source entry: {relative}")
        if relative.is_absolute() or ".." in relative.parts or "\\" in str(relative):
            raise ValueError("Unsafe source path")
        if len(relative.parts) == 1:
            allowed = str(relative) in ALLOWED_ROOT_FILES
        else:
            allowed = relative.parts[0] in ALLOWED_DIRECTORIES and relative.suffix in ALLOWED_SUFFIXES
        if not allowed:
            raise ValueError(f"Review unapproved release source: {relative}")
        members["source/" + relative.as_posix()] = git("cat-file", "blob", sha)
    if "source/LICENSE" not in members or "source/event_control_lab/__main__.py" not in members:
        raise ValueError("Required source or license is absent")
    return members, prefix.rstrip("/"), git("rev-parse", "HEAD").decode().strip()


def build(distributions, output, ci_url=None):
    members, source_path, commit = committed_source()
    version = re.search(r'^version = "([^"]+)"$', members["source/pyproject.toml"].decode(), re.M)[1]
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:a\d+|b\d+|rc\d+)?", version):
        raise ValueError("Unsupported release version")
    if ci_url is not None and not re.fullmatch(
        rf"https://github.com/{re.escape(REPOSITORY)}/actions/runs/\d+", ci_url
    ):
        raise ValueError("Unexpected CI receipt URL")
    names = [f"sparsiloop-{version}-py3-none-any.whl", f"sparsiloop-{version}.tar.gz"]
    if {path.name for path in distributions.iterdir()} != set(names):
        raise ValueError("Distribution folder must contain exactly this version's wheel and sdist")
    check(distributions, ROOT)
    output.mkdir(parents=True, exist_ok=False)
    for name in names:
        payload = (distributions / name).read_bytes()
        members["dist/" + name] = payload
        shutil.copyfile(distributions / name, output / name)
    info = {
        "schema_version": 1, "project": "SparsiLoop", "version": version,
        "repository": REPOSITORY, "source_commit": commit, "source_path": source_path,
        "ci_url": ci_url,
        "scope": "Curated SparsiLoop source, original teaching examples and dependency-free core distributions; no user records, custom private models or third-party datasets",
    }
    members["BUILD_INFO.json"] = json_bytes(info)
    members["START_HERE.md"] = f"""# SparsiLoop {version} / 从这里开始

需要 Python 3.10+。完整解压到较短的新目录，在本文件所在目录打开终端。
Requires Python 3.10+. Extract the whole ZIP to a fresh folder.

Windows PowerShell，无需激活或联网 / no activation or network:

```powershell
python -m venv .venv
.\\.venv\\Scripts\\python.exe -m pip install --no-index --no-deps .\\dist\\{names[0]}
.\\.venv\\Scripts\\python.exe -I -m event_control_lab --version
.\\.venv\\Scripts\\python.exe -I -m event_control_lab serve --port 0
```

macOS / Linux:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --no-index --no-deps dist/{names[0]}
.venv/bin/python -I -m event_control_lab serve --port 0
```

打开终端打印的本地网址，保持终端运行，按 Ctrl+C 停止。只在本机运行。
Open the printed loopback URL; keep the terminal open and stop with Ctrl+C.

想先看静态控制案例 / Generate a static controller report:

```powershell
.\\.venv\\Scripts\\python.exe -I -m event_control_lab controller-lab --method ilc --out reports/first-ilc
Start-Process .\\reports\\first-ilc\\report.html
```

已有固定目标位置？使用内置位置—速度模型的本地任务 / Try a fixed position target:

```powershell
.\\.venv\\Scripts\\python.exe -I -m event_control_lab.constant_target run --spec source/examples/constant-target.json --out reports/constant-target
```

先核目标和实际初态，再看误差与消息账本。保留完整 `target-task.json` 及匹配源码；
只重绘时用 `constant_target render`，不会重新训练或仿真。
Check the target and initial state before reading error and message counts. Keep
the complete task record and matching source; redraw does not rerun computation.
[常值目标任务 / Constant-target guide](source/docs/constant-target.md)

源码免安装入口也在这里：进入 `source/`，运行 `python quickstart.py`。
The source preview is `cd source` then `python quickstart.py`.
Source-relative example paths start in that directory; the installed interpreter
is one directory above. The optional simple-pid recipe needs its separately
declared dependency; the core and web lab do not.

[第一次使用 / Tasks and saved files](source/START_HERE.md) ·
[中文](source/README.md) · [English](source/README.en.md) ·
[旧文件与源码恢复 / Recovery](source/docs/source-recovery.md) · [MIT](source/LICENSE)

离开页面前保存完整报告、原选择和最新历史；报告已生成不代表任务达标。
Save the report ZIP, original choice and latest history before leaving the page.
A common cap is not equal actual traffic; generated reports do not certify
stability, hardware effects or independent adoption. This is an alpha.

`BUILD_INFO.json` names the exact public commit. `MANIFEST.json` hashes every
other ZIP member; `SHA256SUMS` checks the downloaded assets. These are consistency
records, not authenticated provenance. Keep the complete bundle with old results.
""".encode("utf-8")
    members["MANIFEST.json"] = json_bytes({
        "schema_version": 1, "source_commit": commit,
        "files": {name: {"sha256": digest(data), "bytes": len(data)}
                  for name, data in sorted(members.items())},
    })
    bundle = output / f"SparsiLoop-{version}.zip"
    with zipfile.ZipFile(bundle, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(members.items()):
            entry = zipfile.ZipInfo(name, date_time=(2026, 10, 24, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, data)
    with zipfile.ZipFile(bundle) as archive:
        if archive.testzip() or len(archive.namelist()) != len(set(archive.namelist())):
            raise ValueError("Invalid bundle")
        manifest = json.loads(archive.read("MANIFEST.json"))
        if set(archive.namelist()) != set(manifest["files"]) | {"MANIFEST.json"}:
            raise ValueError("Manifest does not cover the bundle")
        for name, expected in manifest["files"].items():
            data = archive.read(name)
            if len(data) != expected["bytes"] or digest(data) != expected["sha256"]:
                raise ValueError(f"Bundle identity mismatch: {name}")
    info["assets"] = {path.name: {"bytes": path.stat().st_size, "sha256": digest(path.read_bytes())}
                      for path in sorted(output.iterdir())}
    (output / "RELEASE_INFO.json").write_bytes(json_bytes(info))
    sums = "".join(f"{digest(path.read_bytes())}  {path.name}\n" for path in sorted(output.iterdir()))
    (output / "SHA256SUMS").write_text(sums, encoding="utf-8", newline="\n")
    print(json.dumps({"version": version, "source_commit": commit,
                      "source_files": len([name for name in members if name.startswith('source/')]),
                      "bundle_members": len(members), "release_assets": len(list(output.iterdir()))}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=ROOT / "dist")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--ci-url")
    arguments = parser.parse_args()
    build(arguments.dist.resolve(), arguments.out.resolve(), arguments.ci_url)


if __name__ == "__main__":
    main()
