"""Split freedm/gui.py into the freedm/gui/ package (Milestone 3, G3).

Like the engine split: the same code, moved into focused modules. The App
class becomes a set of mixins, one per concern, and freedm/gui/__init__.py
re-exports it, so ``from freedm.gui import run_gui`` keeps working.
"""
from __future__ import annotations

import ast
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "freedm", "gui.py")
TARGET = os.path.join(ROOT, "freedm", "gui")
HEADER = "# Required Notice: Copyright (c) 2026 outlawproductionstwo-hash\n"

MIXINS = {
    "dialogs": [
        "categories_dialog", "export_queue_dialog", "import_queue_dialog",
        "show_in_folder", "schedule_dialog", "about_dialog",
        "network_dialog", "mirrors_dialog", "checksum_dialog",
        "cleanup_dialog", "show_details", "_edit_headers", "_browser_dialog",
    ],
    "automation": [
        "_apply_window", "_toggle_shutdown", "_queue_is_empty",
        "_check_shutdown_when_done", "_apply_network_settings",
        "_check_connection", "_toggle_auto_sort", "_target_dir",
        "_dest_resolver", "_toggle_log", "_kb_to_bytes",
        "limit_selected", "global_limit_dialog",
    ],
    "browser": [
        "_start_control", "_toggle_control", "_copy_token",
        "_export_extension", "_install_native_host", "_uninstall_native_host",
        "_add_from_browser",
    ],
}

CORE = [
    "__init__", "_restore_window", "_build_toolbar", "_build_filterbar",
    "_build_tree", "_build_buttons", "_build_statusbar", "_browse_dir",
    "_toggle_auto_resume", "_change_max_active", "_change_threads",
    "_toggle_clipboard", "_read_clipboard", "_known_urls", "_check_clipboard",
    "_new_download", "_name_from_url", "_add_url", "_enqueue",
    "_status_filter", "_row_matches", "_apply_filter", "_refresh_visible",
    "_selected",
    "pause_selected", "resume_selected", "cancel_selected",
    "start_now_selected", "move_up_selected", "move_down_selected",
    "remove_selected", "clear_completed", "open_file", "open_folder", "_open",
    "_notify_status", "add_download", "_restore_jobs", "_on_close", "_poll",
]

DOCS = {
    "dialogs": ("The dialogs: the ones that act on a job and the ones that "
                "change the settings."),
    "automation": ("The automatic parts: the daily window, the shut-down when "
                   "the queue drains, the categories and the network "
                   "settings."),
    "browser": ("The browser handoff: the control server, the extension and "
                "the native messaging host."),
}

IMPORTS = {
    "dialogs": (
        "import datetime\nimport os\nimport subprocess\nimport sys\n"
        "import time\nimport tkinter as tk\n"
        "from tkinter import filedialog, messagebox, simpledialog, ttk\n\n"
        "from freedm.categories import (default_rules, export_queue,\n"
        "                             format_rules, import_queue, load_rules,\n"
        "                             parse_rules)\n"
        "from freedm.control_server import export_extension, token_path\n"
        "from freedm.engine import (Download, human_size, human_speed,\n"
        "                         human_time, global_speed_limit, QUEUED)\n"
        "from freedm.gui.constants import APP_NAME, EXECUTABLE_EXTENSIONS\n"
        "from freedm.network import PROXY\n"
        "from freedm.settings import save as save_settings\n"
        "from freedm.verify import (ALGORITHMS, cleanup_orphans,\n"
        "                         find_orphans, parse_checksum)\n"
        "from freedm import logsetup, native_host, update\n"),
    "automation": (
        "import os\nimport subprocess\nimport tkinter as tk\n"
        "from tkinter import messagebox, simpledialog, ttk\n\n"
        "from freedm.engine import (DOWNLOADING, PAUSED, PROBING, QUEUED,\n"
        "                         SCHEDULED, global_speed_limit,\n"
        "                         set_global_speed_limit)\n"
        "from freedm.settings import save as save_settings\n\n"
        "from freedm.automation import (describe_schedule, format_time,\n"
        "                           in_window, parse_time, shutdown_command,\n"
        "                           SHUTDOWN, SLEEP)\n"
        "from freedm.categories import (default_rules, destination_for,\n"
        "                             format_rules, load_rules, parse_rules)\n"
        "from freedm.engine import Download, human_speed\n"
        "from freedm.gui.constants import APP_NAME\n"
        "from freedm.network import PROXY, install_address_preference\n"
        "from freedm import logsetup, update\n"
        "from freedm.version import version_info\n"),
    "browser": (
        "import os\nimport subprocess\nimport tkinter as tk\n"
        "from tkinter import messagebox, ttk\n\n"
        "from freedm.settings import save as save_settings\n\n"
        "from freedm.control_server import (ControlServer, export_extension,\n"
        "                                  token_path)\n"
        "from freedm.engine import Download\n"
        "from freedm.gui.constants import APP_NAME\n"
        "from freedm import native_host\n"),
}


def read_lines() -> list[str]:
    with open(SOURCE, "r", encoding="utf-8", newline="") as fh:
        return fh.read().split("\n")


def block(lines: list[str], node) -> list[str]:
    start = node.lineno - 1
    for decorator in getattr(node, "decorator_list", []):
        start = min(start, decorator.lineno - 1)
    end = getattr(node, "end_lineno", node.lineno)
    return lines[start:end]


def main() -> int:
    lines = read_lines()
    tree = ast.parse("\n".join(lines))

    constants, imports, app_class, run_gui = [], [], None, None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "App":
            app_class = node
        elif isinstance(node, ast.FunctionDef) and node.name == "run_gui":
            run_gui = block(lines, node)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            constants.append(block(lines, node))
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.append(block(lines, node))

    methods = {n.name: block(lines, n) for n in app_class.body
               if isinstance(n, ast.FunctionDef)}
    missing = [m for m in CORE + sum(MIXINS.values(), [])
               if m not in methods]
    if missing:
        print("methods not found:", missing)
        return 1

    if os.path.isdir(TARGET):
        shutil.rmtree(TARGET)
    os.makedirs(TARGET)

    def write(name: str, text: str) -> None:
        with open(os.path.join(TARGET, name), "w", encoding="utf-8",
                  newline="\n") as fh:
            fh.write(text)

    # --- constants.py ----------------------------------------------------
    write("constants.py", HEADER
          + '"""The names the window shows."""\n'
          "from __future__ import annotations\n\n\n"
          + "\n\n\n".join("\n".join(b).rstrip() for b in constants) + "\n")

    # --- the mixins ------------------------------------------------------
    for name, names in MIXINS.items():
        body = "\n\n".join("\n".join(methods[m]).rstrip() for m in names)
        write(f"{name}.py", HEADER
              + f'"""Part of the App class: {DOCS[name]}"""\n'
              "from __future__ import annotations\n\n"
              + IMPORTS[name] + "\n\nclass "
              + name.capitalize() + "Mixin:\n    \"\"\""
              + DOCS[name] + "\"\"\"\n\n"
              + body + "\n")

    # --- app.py ----------------------------------------------------------
    core_body = "\n\n".join("\n".join(methods[m]).rstrip() for m in CORE)
    write("app.py", HEADER
          + '"""The FreeDM window."""\n'
          "from __future__ import annotations\n\n"
          + "\n".join("\n".join(b) for b in imports) + "\n"
          "from freedm.gui.automation import AutomationMixin\n"
          "from freedm.gui.browser import BrowserMixin\n"
          "from freedm.gui.constants import APP_NAME, EXECUTABLE_EXTENSIONS\n"
          "from freedm.gui.dialogs import DialogsMixin\n\n\n"
          "class App(AutomationMixin, BrowserMixin, DialogsMixin):\n"
          '    """The main window."""\n\n'
          + core_body + "\n")

    # --- __init__.py -----------------------------------------------------
    write("__init__.py", HEADER
          + '"""The FreeDM graphical interface."""\n'
          "from __future__ import annotations\n\n"
          "import tkinter as tk\n"
          "from tkinter import ttk\n\n"
          "from freedm.store import JobStore\n"
          "from freedm.gui.app import App\n"
          "from freedm.gui.constants import APP_NAME, EXECUTABLE_EXTENSIONS\n\n\n"
          + "\n".join(run_gui) + "\n\n\n"
          '__all__ = ["App", "run_gui", "APP_NAME", "EXECUTABLE_EXTENSIONS"]\n')

    print("the gui package is written")
    if os.path.exists(SOURCE):
        os.remove(SOURCE)
        print(f"removed {os.path.relpath(SOURCE, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
