"""The version of FreeDM, in one place (Milestone 3, goal G2).

Everything that shows or compares the version - the command line, the About
dialog, the update check - reads it from here, so there is only ever one
answer.
"""
from __future__ import annotations

import os

from freedm import __version__

#: The name the application is known by.
APP_NAME = "FreeDM"

#: The licence the project is published under.
LICENSE_NAME = "PolyForm Noncommercial 1.0.0"
LICENSE_URL = "https://polyformproject.org/licenses/noncommercial/1.0.0"

#: Where the project lives.
PROJECT_URL = "https://github.com/EddyGameDev/FreeDM"

#: The name of the file the update check reads.
VERSION_FILE = "VERSION.json"


def settings_folder() -> str:
    """Where FreeDM keeps the queue and the settings on this machine."""
    from freedm.store import app_data_dir
    return app_data_dir()


def version_info() -> dict:
    """Everything that describes this build."""
    return {
        "app": APP_NAME,
        "version": __version__,
        "license": LICENSE_NAME,
        "license_url": LICENSE_URL,
        "url": PROJECT_URL,
        "settings": settings_folder(),
    }


def version_text() -> str:
    """A short, human readable version banner."""
    info = version_info()
    return (f"{info['app']} {info['version']}\n"
            f"Licence: {info['license']} ({info['license_url']})\n"
            f"Source:  {info['url']}\n"
            f"Settings and queue: {info['settings']}")


def read_version_file(path: str | None = None) -> dict:
    """Read the ``VERSION.json`` the update check compares against."""
    import json
    path = path or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        VERSION_FILE)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
