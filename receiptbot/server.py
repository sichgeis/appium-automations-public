"""Nur den eigenen kurzlebigen Appium-Prozess starten und beenden."""
from contextlib import contextmanager
import json
import os
import signal
import socket
import subprocess
import time
import urllib.request
from .session import ROOT


@contextmanager
def local_server():
    with socket.socket() as sock:
        if sock.connect_ex(('127.0.0.1', 4723)) == 0:
            raise ValueError('Port 4723 belegt. Fremden Server nicht übernommen; eigene Testsitzung zuerst beenden.')
    process = subprocess.Popen(['sh', str(ROOT / 'scripts/appium.sh'), '--address', '127.0.0.1',
        '--port', '4723', '--log-level', 'error', '--log-no-colors'], cwd=ROOT,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        for _ in range(60):
            if process.poll() is not None:
                raise ValueError('Projekt-Appium konnte nicht starten; npm-Abhängigkeiten und Doctor prüfen.')
            try:
                with urllib.request.urlopen('http://127.0.0.1:4723/status', timeout=1) as response:
                    if json.load(response)['value']['ready']:
                        break
            except (OSError, ValueError):
                time.sleep(.25)
        else:
            raise ValueError('Projekt-Appium ist nicht rechtzeitig bereit.')
        yield
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
