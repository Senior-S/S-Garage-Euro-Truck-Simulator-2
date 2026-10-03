"""Portable Windows launcher; the browser remains the garage interface."""
import json
from pathlib import Path
import sys
import threading
import tkinter as tk
from tkinter import messagebox
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
import webbrowser

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))
from server import APP, DATA, Garage, Handler, ThreadingHTTPServer


def main():
    garage = Garage()
    if "--check" in sys.argv:
        if not all((APP / path).is_file() for path in ("ui/dist/index.html", "tools/SII_Decrypt.exe", "tools/converter_pix.exe")):
            raise FileNotFoundError("The portable download is incomplete. Extract the entire ZIP again.")
        (DATA / "package-check.json").write_text(json.dumps(garage.status()), encoding="utf-8")
        return
    url = "http://127.0.0.1:8765"
    try:
        with urlopen(url + "/api/status", timeout=2) as response:
            existing = json.load(response)
    except HTTPError:
        raise
    except URLError:
        existing = None
    if existing:
        if existing.get("appId") != "ets2-local-garage":
            raise RuntimeError("Port 8765 is used by another application.")
        webbrowser.open(url)
        return
    server = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    server.daemon_threads = True
    server.garage = garage
    threading.Thread(target=server.serve_forever, daemon=True).start()
    window = tk.Tk()
    window.title("S Garage")
    window.geometry("420x215")
    window.resizable(False, False)
    tk.Label(window, text="S Garage", font=("Segoe UI", 22, "bold")).pack(pady=(20, 5))
    tk.Label(window, text="Your local ETS2 garage is running.", font=("Segoe UI", 11)).pack()
    tk.Label(window, text="Keep this window open while editing.\nSave your changes before stopping the garage.", font=("Segoe UI", 10)).pack(pady=10)
    def stop():
        with garage.lock:
            if garage.session and garage.session.state()["dirty"] and not messagebox.askyesno("Unsaved changes", "Stop the garage and discard unsaved truck edits?", parent=window):
                return
        garage.scene_cancel.set()
        with garage.model_request_lock:
            for event in garage.model_requests.values():
                event.set()
        server.shutdown()
        server.server_close()
        window.destroy()
    buttons = tk.Frame(window)
    buttons.pack(pady=4)
    tk.Button(buttons, text="Open garage", command=lambda: webbrowser.open(url), width=16).pack(side="left", padx=5)
    tk.Button(buttons, text="Stop garage", command=stop, width=16).pack(side="left", padx=5)
    window.protocol("WM_DELETE_WINDOW", stop)
    webbrowser.open(url)
    window.mainloop()


if __name__ == "__main__":
    DATA.mkdir(parents=True, exist_ok=True)
    with (DATA / "server.log").open("a", encoding="utf-8", buffering=1) as output, (DATA / "server-errors.log").open("a", encoding="utf-8", buffering=1) as errors:
        sys.stdout, sys.stderr = output, errors
        try:
            main()
        except Exception as error:
            import traceback
            traceback.print_exc()
            if "--check" in sys.argv:
                raise
            messagebox.showerror("S Garage could not start", f"{error}\n\nDetails: {DATA / 'server-errors.log'}")
            raise
