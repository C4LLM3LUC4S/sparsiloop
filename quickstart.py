"""Open the local lab or generate learning-controller reports without installation."""

import argparse
from datetime import datetime
from pathlib import Path
import sys
import uuid
import webbrowser


def open_page(url, disabled):
    if not disabled:
        try:
            webbrowser.open(url)
        except (OSError, webbrowser.Error):
            print("浏览器没有自动打开。请复制上方网址，或手动打开报告文件。 / Open the printed URL or HTML file.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("web", "controllers"), default="web")
    parser.add_argument("--method", choices=("all", "mfac", "ilc", "rl"), default="all")
    parser.add_argument("--out", type=Path, help="new folder for controller reports")
    parser.add_argument("--port", type=int, default=0, help="web port; zero selects an unused local port")
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()
    if sys.version_info < (3, 10):
        parser.exit(2, "SparsiLoop needs Python 3.10 or newer.\n")
    root = Path(__file__).resolve().parent
    if not (root / "event_control_lab/__init__.py").is_file():
        parser.exit(2, "Extract the complete source ZIP before running quickstart.py.\n")
    sys.path.insert(0, str(root))
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    if args.mode == "web" and (args.out is not None or args.method != "all"):
        parser.error("--out and --method require --mode controllers")
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between zero and 65535")
    print("SparsiLoop：直接运行本地源码，不会安装软件或改动现有环境。 / Running local source; no installation.", flush=True)
    try:
        if args.mode == "controllers":
            from event_control_lab.controller_lab import controller_lab, export_controller_lab
            from event_control_lab.output_paths import check_new_output
            label = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
            output = args.out if args.out else root / "runs" / ("controllers-" + label)
            if output.exists():
                parser.error("输出文件夹已存在，请换一个新文件夹；旧报告会保留。 / Output already exists; choose a new folder")
            check_new_output(output)
            output = output.resolve()
            export_controller_lab(controller_lab(method=args.method), output)
            report = (output / "report.html").resolve()
            print("报告已保存，打开这个文件即可查看 / Report: " + str(report), flush=True)
            open_page(report.as_uri(), args.no_open)
        else:
            from event_control_lab.server import Handler, LocalServer
            with LocalServer(("127.0.0.1", args.port), Handler) as server:
                url = f"http://127.0.0.1:{server.server_port}"
                print("网页已启动，请在浏览器打开 / Local lab: " + url, flush=True)
                print("使用网页时请保持这个终端窗口打开；结束后按 Ctrl+C。 / Keep this terminal open; Ctrl+C stops it.", flush=True)
                # Bind first; never open a browser to a different service occupying the port.
                open_page(url, args.no_open)
                server.serve_forever()
    except KeyboardInterrupt:
        print("Stopped / 已停止。")
    except (OSError, ValueError) as exc:
        parser.exit(2, f"SparsiLoop: {exc}. 如果报告无法保存，请换一个有写入权限的新文件夹；如果端口被占用，请加 --port 0。 / Use a writable new folder or --port 0.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
