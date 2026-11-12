"""Windows desktop entry point and frozen CLI-script dispatcher."""
from __future__ import annotations

import os
import runpy
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path


def bundle_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))


def configure_workspace(root: Path) -> Path:
    import shutil

    home = Path(os.environ.get("GO_FORWARD_HOME", Path.home() / "GO-Forward"))
    home.mkdir(parents=True, exist_ok=True)
    data = home / "data"
    # Seed only absent projects, never merge over a user's edited input files.
    for source in (root / "data").iterdir():
        if source.is_dir() and not (data / source.name).exists():
            shutil.copytree(source, data / source.name)
    os.environ["GO_FORWARD_DATA_ROOT"] = str(data)
    return home


def available_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def dispatch_script(root: Path, arguments: list[str]) -> int:
    script = Path(arguments[0])
    if not script.is_absolute():
        script = root / script
    script = script.resolve()
    if script.parent != (root / "scripts").resolve() or not script.is_file():
        raise ValueError("Only bundled workflow scripts can be executed.")
    sys.path.insert(0, str(script.parent))
    sys.argv = [str(script), *arguments[1:]]
    runpy.run_path(str(script), run_name="__main__")
    return 0


def serve(root: Path, port: str) -> int:
    from streamlit.web import cli

    sys.argv = [
        "streamlit", "run", str(root / "dashboard" / "streamlit_app.py"),
        "--server.address=127.0.0.1", f"--server.port={port}",
        "--server.headless=true", "--server.fileWatcherType=none",
        "--browser.gatherUsageStats=false", "--global.developmentMode=false",
    ]
    return cli.main()


def desktop(root: Path) -> int:
    import tkinter as tk
    from tkinter import messagebox, ttk

    window = tk.Tk()
    window.title("GO-Forward")
    window.geometry("470x220")
    window.resizable(False, False)
    process = None
    log_handle = None
    try:
        home = configure_workspace(root)
        port = available_port()
        url = f"http://127.0.0.1:{port}"
        log_handle = (home / "dashboard.log").open("w", encoding="utf-8")
        worker = Path(sys.executable).with_name("GO-Forward-worker.exe")
        process = subprocess.Popen(
            [str(worker), "--serve", str(port)], cwd=root,
            stdout=log_handle, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        status = tk.StringVar(value="Starting dashboard...")
        frame = ttk.Frame(window, padding=20)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, textvariable=status).pack(anchor="w", pady=8)
        ttk.Label(frame, text=f"Projects: {home / 'data'}", wraplength=420).pack(anchor="w")
        open_button = ttk.Button(frame, text="Open dashboard", command=lambda: webbrowser.open(url), state="disabled")
        open_button.pack(anchor="w", pady=12)
        started = time.monotonic()

        def stop() -> None:
            if process.poll() is None:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, check=False,
                )
            window.destroy()

        def poll() -> None:
            if process.poll() is not None:
                status.set("Dashboard stopped. See dashboard.log in your GO-Forward folder.")
                return
            try:
                with urllib.request.urlopen(url + "/_stcore/health", timeout=0.3) as response:
                    ready = response.status == 200
            except OSError:
                ready = False
            if ready:
                status.set("Dashboard is running. Close this window to stop it.")
                open_button.configure(state="normal")
                webbrowser.open(url)
            elif time.monotonic() - started > 120:
                status.set("Startup is taking longer than expected. See dashboard.log.")
            else:
                window.after(500, poll)

        ttk.Button(frame, text="Stop and close", command=stop).pack(anchor="w")
        window.protocol("WM_DELETE_WINDOW", stop)
        window.after(500, poll)
        window.mainloop()
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        messagebox.showerror("GO-Forward could not start", str(exc))
        return 1
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        if log_handle is not None:
            log_handle.close()


def main() -> int:
    root = bundle_root()
    if len(sys.argv) > 1:
        if sys.argv[1] == "--serve":
            return serve(root, sys.argv[2])
        return dispatch_script(root, sys.argv[1:])
    return desktop(root)


if __name__ == "__main__":
    raise SystemExit(main())
