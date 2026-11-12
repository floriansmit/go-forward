"""Exercise the compiled worker, not the build machine's Python runtime."""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from streamlit.proto.BackMsg_pb2 import BackMsg
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from conftest import generate_mini_grdecl_text
from desktop_launcher import available_port


def check_dashboard(port):
    """Open a Streamlit session so the dashboard script actually executes."""
    with connect(
        f"ws://127.0.0.1:{port}/_stcore/stream", subprotocols=["streamlit"],
        origin=f"http://127.0.0.1:{port}", max_size=None,
    ) as connection:
        request = BackMsg()
        request.rerun_script.SetInParent()
        connection.send(request.SerializeToString())
        while True:
            message = ForwardMsg()
            message.ParseFromString(connection.recv(timeout=120))
            if message.HasField("delta") and message.delta.HasField("new_element"):
                element = message.delta.new_element
                assert not element.HasField("exception"), element.exception.message
            if message.HasField("script_finished"):
                break


def main():
    bundle = ROOT / "dist" / "GO-Forward"
    worker = bundle / "GO-Forward-worker.exe"
    resources = bundle / "_internal"
    runtime_env = dict(os.environ)
    runtime_env["PATH"] = str(Path(os.environ["SYSTEMROOT"]) / "System32")
    runtime_env.pop("PYTHONHOME", None)
    runtime_env.pop("PYTHONPATH", None)
    with tempfile.TemporaryDirectory(prefix="go forward smoke ") as temporary:
        workspace = Path(temporary)
        source = workspace / "source"
        source.mkdir()
        (source / "mini.grdecl").write_text(generate_mini_grdecl_text())

        def run(script, *args):
            result = subprocess.run(
                [str(worker), f"scripts/{script}.py", *map(str, args)],
                cwd=resources, env=runtime_env, capture_output=True, text=True, timeout=120, check=False,
            )
            assert result.returncode == 0, result.stdout + result.stderr
            print(result.stdout)

        points, tmap, augmented = [workspace / name for name in ("points", "tmap", "augmented")]
        run("build_best_fit_grdecl_to_pointset", "--grdecl-dir", source, "--output-dir", points, "--property", "FACIES")
        assert list(points.glob("*_3d_pointset"))
        run("generate_synthetic_tmap_data", "--source-dir", points, "--output-dir", tmap)
        run("append_best_fit_tmap_to_grdecls", "--grdecl-dir", source, "--pointset-dir", tmap, "--output-dir", augmented)
        results = list(augmented.glob("*.grdecl"))
        assert results and "PORO50" in results[0].read_text()

        port = available_port()
        project = workspace / "data" / "Smoke_mvp"
        original = project / "original_grdecl"
        original.mkdir(parents=True)
        shutil.copyfile(source / "mini.grdecl", original / "mini.grdecl")
        example = resources / "data" / "MVP_Gassum_mvp"
        shutil.copyfile(example / "project_config.json", project / "project_config.json")
        shutil.copyfile(example / "original_grdecl" / "facies_config.json", original / "facies_config.json")
        env = dict(runtime_env, GO_FORWARD_DATA_ROOT=str(workspace / "data"))
        with (workspace / "server.log").open("w+") as log:
            server = subprocess.Popen([str(worker), "--serve", str(port)], cwd=resources, env=env, stdout=log, stderr=log)
            try:
                for _ in range(120):
                    assert server.poll() is None, "Compiled server exited during startup"
                    try:
                        with urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=1) as response:
                            assert response.status == 200
                        break
                    except OSError:
                        time.sleep(0.5)
                else:
                    raise AssertionError("Compiled server did not become healthy")
                check_dashboard(port)
            finally:
                server.terminate()
                server.wait(timeout=20)
    print("Compiled workflow and Streamlit health checks passed.")


if __name__ == "__main__":
    main()
