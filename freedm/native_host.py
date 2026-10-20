"""Native messaging host: lets the browser extension start FreeDM (N8).

The browser extension can only talk to the app over the loopback control
server. When the app is closed there is nobody to answer, so the extension
asks the browser's *native messaging* host - a small program the browser
starts on request - to launch FreeDM.

How it works:

1. The app registers itself with the browser by writing a native messaging
   manifest and a registry entry (Windows) for ``org.freedm.app``.
2. The extension calls ``chrome.runtime.sendNativeMessage("org.freedm.app",
   {...})``; the browser starts the registered program and talks to it over
   stdin/stdout.
3. The host answers with JSON. For ``{"action": "launch"}`` it starts the GUI
   in the background and tells the extension to retry.

The wire format is the one the browsers use: a 4-byte little-endian length
followed by a UTF-8 JSON message.
"""
from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import time

from freedm.store import app_data_dir

#: The name the browser knows the host by.
HOST_NAME = "org.freedm.app"

#: Where the native messaging manifest is written.
MANIFEST_NAME = "native-host.json"

#: How long the extension should wait for the app to come up.
LAUNCH_WAIT_SECONDS = 12.0


def manifest_path() -> str:
    """The path of the native messaging manifest."""
    return os.path.join(app_data_dir(), MANIFEST_NAME)


def app_executable() -> str:
    """The program the browser should start for the native host.

    A frozen build is its own executable; a source checkout is run through
    the interpreter."""
    if getattr(sys, "frozen", False):
        return os.path.abspath(sys.executable)
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "main.py"))


def build_manifest(origins: list[str] | None = None) -> dict:
    """The native messaging manifest for this installation.

    ``origins`` names the extensions that may call the host. When the
    extension's id is known it is listed exactly; otherwise the wildcard is
    used, which means *any* installed extension could call the host - that
    is only acceptable because the host can do no more than start FreeDM."""
    program = app_executable()
    if not getattr(sys, "frozen", False):
        # A source checkout: the browser must start the interpreter.
        program = f'{sys.executable} "{program}" --native-host'
    if origins:
        allowed = list(origins)
        note = "Only the listed extension may call this host."
    else:
        allowed = ["chrome-extension://*", "moz-extension://*"]
        note = ("The extension id is not known yet, so ANY installed "
                "extension may call this host. The host can only start "
                "FreeDM. Reinstall the native host after the extension has "
                "talked to FreeDM once, to narrow this down.")
    return {
        "name": HOST_NAME,
        "description": "Starts FreeDM so the browser can hand over downloads.",
        "path": program,
        "type": "stdio",
        "allowed_origins": allowed,
        "_note": note,
    }


def extension_origins(extension_id: str | None) -> list[str] | None:
    """The origins that may call the host, for a known extension id.

    Chrome and Edge use ``chrome-extension://<id>`` and Firefox uses
    ``moz-extension://<uuid>``; a Chrome/Edge extension id also works in
    Firefox, so both spellings are listed."""
    if not extension_id:
        return None
    extension_id = str(extension_id).strip()
    if not extension_id:
        return None
    return [f"chrome-extension://{extension_id}",
            f"moz-extension://{extension_id}"]


def write_manifest(origins: list[str] | None = None) -> str:
    """Write the native messaging manifest and return its path."""
    path = manifest_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(build_manifest(origins), fh, indent=2)
    return path


def _registry_key(browser: str) -> str:
    if browser == "firefox":
        return r"Software\Mozilla\NativeMessagingHosts\{0}".format(HOST_NAME)
    return r"Software\Google\Chrome\NativeMessagingHosts\{0}".format(HOST_NAME)


def install_host(origins: list[str] | None = None) -> tuple[bool, str]:
    """Register the host with the browsers.

    Returns ``(ok, message)``. Registration needs the registry (Windows) or
    the equivalent file (Linux/macOS); when it is not possible the manifest
    is still written so the user can register it by hand.

    ``origins`` should name the extension that may call the host (see
    :func:`extension_origins`)."""
    path = write_manifest(origins)
    message = f"Native host manifest written to:\n{path}"
    if origins:
        message += "\nOnly these extensions may call it:\n  " + ", ".join(origins)
    else:
        message += ("\nThe extension id is not known, so any installed "
                    "extension may call the host. The extension tells "
                    "FreeDM its id the first time it hands a download over.")
    if sys.platform.startswith("win"):
        try:
            import winreg
        except ImportError:                      # pragma: no cover
            return False, message + "\n(winreg is not available)"
        for browser in ("chrome", "firefox"):
            try:
                key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, _registry_key(browser))
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, path)
                winreg.CloseKey(key)
            except OSError as exc:
                message += f"\n{_registry_key(browser)}: {exc}"
    else:
        message += ("\nRegister it by hand for your browser - see "
                    "docs/SECURITY.md.")
    return True, message


def uninstall_host() -> tuple[bool, str]:
    """Remove the registration (the manifest file is kept)."""
    if not sys.platform.startswith("win"):
        return False, "Only the Windows registry is handled automatically."
    try:
        import winreg
    except ImportError:                          # pragma: no cover
        return False, "winreg is not available"
    removed = []
    for browser in ("chrome", "firefox"):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, _registry_key(browser))
            removed.append(browser)
        except OSError:
            pass
    if removed:
        return True, "Removed the registration for: " + ", ".join(removed)
    return False, "Nothing was registered."


def is_installed() -> bool:
    """True when a browser knows about the host."""
    if not sys.platform.startswith("win"):
        return os.path.exists(manifest_path())
    try:
        import winreg
    except ImportError:                          # pragma: no cover
        return False
    for browser in ("chrome", "firefox"):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 _registry_key(browser))
            winreg.CloseKey(key)
            return True
        except OSError:
            continue
    return False


def launch_app() -> bool:
    """Start the GUI in the background and return True when it was started."""
    if getattr(sys, "frozen", False):
        command = [sys.executable]
    else:
        command = [sys.executable, os.path.abspath(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py"))]
    try:
        subprocess.Popen(command, creationflags=getattr(
            subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    except OSError:
        return False
    return True


def handle_message(payload: dict) -> dict:
    """Answer one native message."""
    action = str((payload or {}).get("action") or "").lower()
    if action == "ping":
        return {"ok": True, "app": "FreeDM", "version": "1.0"}
    if action == "launch":
        started = launch_app()
        return {"ok": started, "launched": started,
                "wait": LAUNCH_WAIT_SECONDS}
    return {"ok": False, "error": "unknown action"}


def read_message(stream) -> dict | None:
    """Read one length-prefixed JSON message from a binary stream."""
    raw = stream.read(4)
    if not raw or len(raw) < 4:
        return None
    (length,) = struct.unpack("<I", raw)
    if length > 4 * 1024 * 1024:
        return None
    body = stream.read(length)
    if not body:
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None


def write_message(stream, payload: dict) -> None:
    """Write one length-prefixed JSON message to a binary stream."""
    body = json.dumps(payload).encode("utf-8")
    stream.write(struct.pack("<I", len(body)))
    stream.write(body)
    stream.flush()


def main() -> int:
    """The native host entry point (stdin/stdout)."""
    try:
        payload = read_message(sys.stdin.buffer)
    except Exception:                             # noqa: BLE001
        payload = None
    if payload is None:
        payload = {"action": "ping"}
    try:
        response = handle_message(payload)
    except Exception as exc:                      # noqa: BLE001
        response = {"ok": False, "error": str(exc)}
    try:
        write_message(sys.stdout.buffer, response)
    except Exception:                             # noqa: BLE001
        return 1
    # The browser closes the pipe; give the launched app a moment to start.
    if payload.get("action") == "launch":
        time.sleep(0.2)
    return 0
