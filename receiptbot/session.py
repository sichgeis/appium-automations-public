"""Sitzung ohne Rücksetzen und mit exklusiver lokaler Gerätesperre."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent


def select_local_xcode():
    developer = Path('/Applications/Xcode.app/Contents/Developer')
    if developer.is_dir():
        os.environ.setdefault('DEVELOPER_DIR', str(developer))


def load_config(path=None):
    path = Path(path) if path else ROOT / "config.local.json"
    if not path.is_file():
        raise ValueError("config.local.json fehlt; Vorlage kopieren und lokal ausfüllen.")
    return json.loads(path.read_text())


def capabilities(config, app):
    url = urlparse(config.get("server_url", ""))
    if (url.scheme != "http" or url.hostname != "127.0.0.1"
            or url.username or url.password or url.query or url.fragment):
        raise ValueError("Nur ein lokaler HTTP-Appium-Server unter 127.0.0.1 ist erlaubt.")
    bundle = config.get("apps", {}).get(app, {}).get("bundle_id", "")
    if not bundle or not config.get("udid"):
        raise ValueError("Echte Gerätekennung und beobachtete App-Bundle-ID fehlen in der lokalen Konfiguration.")
    caps = {
        "platformName": "iOS", "appium:automationName": "XCUITest",
        "appium:udid": config["udid"], "appium:bundleId": bundle,
        "appium:noReset": True, "appium:fullReset": False,
        "appium:forceAppLaunch": False, "appium:shouldTerminateApp": False,
        "appium:autoAcceptAlerts": False, "appium:autoDismissAlerts": False,
        "appium:newCommandTimeout": config.get('new_command_timeout', 120), "appium:useNewWDA": False,
        "appium:wdaLocalPort": 8100,
        "appium:wdaBindingIP": "127.0.0.1",
        "appium:wdaStartupRetries": 1, "appium:wdaLaunchTimeout": 60000,
    }
    if config.get("team_id"):
        caps["appium:xcodeOrgId"] = config["team_id"]
        caps["appium:xcodeSigningId"] = "Apple Development"
    if config.get("wda_bundle_id"):
        caps["appium:updatedWDABundleId"] = config["wda_bundle_id"]
    if config.get('use_prebuilt_wda'):
        derived = ROOT / 'data/wda/DerivedData'
        if not derived.is_dir():
            raise ValueError('Vorbereiteter WDA-Build fehlt; scripts/build_wda.py zuerst ausführen.')
        caps['appium:usePrebuiltWDA'] = True
        caps['appium:derivedDataPath'] = str(derived)
    return caps


@contextmanager
def device_lock(directory=None):
    directory = Path(directory) if directory else ROOT / "data"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (directory / "device.lock").open("a") as lock:
        os.chmod(lock.name, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Eine receiptbot-Sitzung steuert das Gerät bereits.") from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


@contextmanager
def session(config, app):
    from appium import webdriver
    from appium.options.ios import XCUITestOptions
    select_local_xcode()
    caps = capabilities(config, app)
    with device_lock():
        driver = None
        try:
            driver = webdriver.Remote(config["server_url"], options=XCUITestOptions().load_capabilities(caps))
            driver.activate_app(config["apps"][app]["bundle_id"])
            yield driver
        finally:
            if driver is not None:
                driver.quit()
