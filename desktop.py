import os
import socket
import sys
import threading
import time
import traceback

from app.config import APP_NAME, DATA_DIR, FROZEN

STARTUP_TIMEOUT_SECONDS = 30
LOG_PATH = DATA_DIR / "app.log"
LOCK_PATH = DATA_DIR / "app.lock"
WEBVIEW_STORAGE_PATH = DATA_DIR / "webview"

_lock_handle = None


def _redirect_output() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log = open(LOG_PATH, "a", encoding="utf-8", buffering=1)
    sys.stdout = log
    sys.stderr = log
    print(f"\n=== {APP_NAME} starting {time.strftime('%Y-%m-%d %H:%M:%S')} ===")


def _show_message(text: str) -> None:
    print(text)
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, text, APP_NAME, 0x40)


def _acquire_single_instance_lock() -> bool:
    global _lock_handle
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    handle = open(LOCK_PATH, "a+")
    try:
        if sys.platform == "win32":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return False
    _lock_handle = handle
    return True


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _start_server(port: int):
    import uvicorn

    from app.main import app

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, name="uvicorn", daemon=True)
    thread.start()
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError("The local server didn't start.")
        time.sleep(0.1)
    return server, thread


def _stop(server, thread) -> None:
    server.should_exit = True
    thread.join(timeout=10)
    try:
        from app.scheduler import scheduler

        if scheduler.running:
            scheduler.shutdown(wait=False)
    except Exception:
        traceback.print_exc()


def main() -> int:
    if FROZEN:
        _redirect_output()

    if not _acquire_single_instance_lock():
        _show_message(f"{APP_NAME} is already running.")
        return 0

    try:
        port = _free_port()
        server, thread = _start_server(port)
    except Exception:
        traceback.print_exc()
        _show_message(f"{APP_NAME} couldn't start. Details were saved to:\n{LOG_PATH}")
        return 1

    try:
        import webview

        webview.create_window(
            APP_NAME,
            f"http://127.0.0.1:{port}/",
            width=1440,
            height=900,
            min_size=(960, 640),
            background_color="#0a0f1d",
        )
        webview.start(private_mode=False, storage_path=str(WEBVIEW_STORAGE_PATH))
    except Exception:
        traceback.print_exc()
        _show_message(
            f"{APP_NAME} couldn't open its window. It needs Microsoft Edge WebView2, which comes with "
            f"Windows 10 and 11 updates.\n\nDetails were saved to:\n{LOG_PATH}"
        )
        return 1
    finally:
        _stop(server, thread)
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)
