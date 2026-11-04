"""Explizit gewählter iCloud-Eingang, native Downloadanforderung ohne Inhalte."""
import os
from pathlib import Path
import stat
import subprocess
from .session import ROOT, select_local_xcode


def is_placeholder(path):
    return bool(getattr(Path(path).stat(), 'st_flags', 0) & getattr(stat, 'UF_DATALESS', 0x40000000))


def request_download(path):
    """Native API anstoßen; Erfolg bedeutet noch nicht heruntergeladen."""
    select_local_xcode()
    source = ROOT / 'scripts/request_icloud_download.swift'
    directory = ROOT / 'data/bin'
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    binary = directory / 'request-icloud-download'
    if not binary.exists() or binary.stat().st_mtime_ns < source.stat().st_mtime_ns:
        cache = ROOT / 'data/swift-module-cache'
        cache.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            result = subprocess.run(['xcrun', 'swiftc', '-module-cache-path', str(cache), str(source),
                                     '-o', str(binary)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45)
        except subprocess.TimeoutExpired:
            raise ValueError('Lokaler iCloud-Downloadhelfer konnte nicht rechtzeitig gebaut werden.') from None
        if result.returncode:
            raise ValueError('iCloud-Downloadhelfer nicht baubar; Xcode prüfen oder Datei im Finder vollständig laden.')
        os.chmod(binary, 0o700)
    result = subprocess.run([str(binary), str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    if result.returncode:
        raise ValueError('iCloud-Datei konnte nicht zum Download angefordert werden; im Finder Downloadstatus prüfen.')


def transport_settings(config, override=None):
    settings = config.get('transport', {})
    kind = override or settings.get('kind', 'airdrop')
    if kind == 'airdrop':
        return kind, Path.home() / 'Downloads', None
    if kind != 'icloud':
        raise ValueError('Transport muss airdrop oder icloud sein.')
    directory = Path(settings.get('directory', '')).expanduser()
    folder = settings.get('folder_name', '')
    if not directory.is_absolute() or not directory.is_dir() or not folder or directory.name != folder:
        raise ValueError('iCloud-Eingangsordner fehlt oder stimmt nicht mit folder_name überein. Lokale Konfiguration prüfen.')
    return kind, directory.resolve(), folder
