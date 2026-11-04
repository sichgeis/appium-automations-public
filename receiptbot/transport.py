"""Persistenter Eingang von AirDrop/iCloud; Quellordner bleiben unverändert."""
from pathlib import Path
import time
from .archive import file_digest


def snapshot(directory):
    directory = Path(directory)
    if not directory.is_dir():
        raise ValueError('Transport-Eingangsordner fehlt. Lokalen Zugriff prüfen.')
    result = {}
    for path in directory.iterdir():
        if path.name.startswith('.') or path.is_symlink() or not path.is_file():
            continue
        stat = path.stat()
        result[path.name] = [stat.st_ino, stat.st_size, stat.st_mtime_ns]
    return result


def changed_files(directory, baseline):
    now = snapshot(directory)
    return [Path(directory) / name for name, stamp in now.items()
            if baseline.get(name) != stamp and not name.lower().endswith(('.download', '.part', '.crdownload', '.tmp'))]


def wait_for_file(directory, baseline, timeout=90, stable_seconds=3, expected_name=None, hydrate=False):
    """Mehrdeutigkeit stoppt. Inhalt und Bonzuordnung prüft erst der Validator.

    Baseline bleibt über Neustarts erhalten. Eine alte Datei aus Downloads ist kein
    neuer Eingang. Stabile Größe allein ist ausdrücklich kein Vollständigkeitsbeweis.
    """
    deadline = time.monotonic() + timeout
    if expected_name and (Path(expected_name).name != expected_name or expected_name in baseline):
        raise ValueError('Erwarteter Eingangsname ungültig oder bereits vor dem Speichern vorhanden.')
    requested = set()
    previous = None
    stable_since = time.monotonic()
    while time.monotonic() < deadline:
        candidates = changed_files(directory, baseline)
        if expected_name:
            candidates = [path for path in candidates if path.name == expected_name]
        if len(candidates) > 1:
            raise ValueError('Mehrere neue Dateien: Zuordnung unklar. Nichts archiviert; Eingang bleibt ausstehend.')
        if candidates:
            path = candidates[0]
            try:
                from .icloud import is_placeholder, request_download
                if is_placeholder(path):
                    previous = None
                    if hydrate and path.name not in requested:
                        request_download(path)
                        requested.add(path.name)
                    time.sleep(.25)
                    continue
                stat = path.stat()
                stamp = (path.name, stat.st_ino, stat.st_size, stat.st_mtime_ns)
                if stamp != previous:
                    previous, stable_since = stamp, time.monotonic()
                elif stat.st_size > 0 and time.monotonic() - stable_since >= stable_seconds:
                    size, digest = file_digest(path)
                    if snapshot(directory).get(path.name) == list(stamp[1:]):
                        return path, size, digest
            except FileNotFoundError:
                previous = None
        else:
            previous = None
        time.sleep(.25)
    raise ValueError('Noch keine eindeutige vollständige lokale Datei. Transfer bleibt ausstehend; nächster Lauf wartet weiter, ohne erneut zu senden/speichern.')
