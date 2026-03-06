#!/usr/bin/env python3
"""Claude Code Remote — macOS menu bar app."""

import json
import os
import plistlib
import subprocess
import sys
import rumps

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
LOG_DIR = os.path.join(PROJECT_DIR, "logs")

CONFIG_DIR = os.path.expanduser("~/.config/claude-code-remote")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_CONFIG = {
    "auto_start_services": False,
}

MENUBAR_PLIST_LABEL = "com.user.claude-code-remote-menubar"
MENUBAR_PLIST_PATH = os.path.expanduser(
    f"~/Library/LaunchAgents/{MENUBAR_PLIST_LABEL}.plist"
)

# TCC-protected directories that launchd agents can't access without Full Disk Access
_TCC_PROTECTED_DIRS = ("Documents", "Desktop", "Downloads", "Library/Mobile Documents")


def _is_tcc_protected_path(path):
    """Check if path is inside a macOS TCC-protected directory."""
    home = os.path.expanduser("~")
    try:
        rel = os.path.relpath(path, home)
    except ValueError:
        return False
    return any(rel.startswith(d) for d in _TCC_PROTECTED_DIRS)


# Icon states
ICON_GREEN = "● CC"
ICON_GRAY = "○ CC"
ICON_RED = "◉ CC"


class RemoteCLIApp(rumps.App):
    def __init__(self):
        super().__init__(ICON_GRAY, quit_button=None)
        self._service_proc = None
        self._services_running = False
        self._poll_counter = 0
        self.tailscale_ip = self._get_tailscale_ip()
        self.tailscale_dns = self._get_tailscale_dns()

        self.status_item = rumps.MenuItem("Status: Stopped")
        self.status_item.set_callback(None)

        self.ip_item = rumps.MenuItem(
            f"Tailscale IP: {self.tailscale_ip or 'Not connected'}"
        )
        self.ip_item.set_callback(None)

        self.dns_item = rumps.MenuItem(
            f"MagicDNS: {self.tailscale_dns or 'Not available'}"
        )
        self.dns_item.set_callback(None)

        self.open_voice_item = rumps.MenuItem("Open Voice UI")
        self.open_terminal_item = rumps.MenuItem("Open Terminal")
        self.toggle_item = rumps.MenuItem("Start Services")

        log_menu = rumps.MenuItem("View Logs")
        log_menu.add(rumps.MenuItem("ttyd.log"))
        log_menu.add(rumps.MenuItem("voice-wrapper.log"))

        self.autostart_item = rumps.MenuItem("Auto-start on Login")

        quit_item = rumps.MenuItem("Quit")

        self.menu = [
            self.status_item,
            None,
            self.ip_item,
            self.dns_item,
            self.open_voice_item,
            self.open_terminal_item,
            None,
            self.toggle_item,
            None,
            log_menu,
            self.autostart_item,
            None,
            quit_item,
        ]

        self.config = self._load_config()
        if self.config["auto_start_services"]:
            self._start_services()

        self.autostart_item.state = self._is_login_plist_installed()

    def _load_config(self):
        try:
            with open(CONFIG_FILE) as f:
                return {**DEFAULT_CONFIG, **json.load(f)}
        except (FileNotFoundError, json.JSONDecodeError):
            return dict(DEFAULT_CONFIG)

    def _save_config(self, config):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)

    def _get_tailscale_ip(self):
        try:
            result = subprocess.run(
                ["tailscale", "ip", "-4"],
                capture_output=True, text=True, timeout=5,
            )
            return result.stdout.strip() if result.returncode == 0 else None
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

    def _get_tailscale_dns(self):
        try:
            result = subprocess.run(
                ["tailscale", "status", "--json"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                dns_name = data.get("Self", {}).get("DNSName", "")
                return dns_name.rstrip(".") if dns_name else None
        except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
            pass
        return None

    @rumps.timer(5)
    def health_check(self, _):
        """Poll PID files every 5s, Tailscale info every 60s."""
        # Tailscale info changes rarely — poll every 60s (12 ticks)
        if self._poll_counter % 12 == 0:
            self.tailscale_ip = self._get_tailscale_ip()
            self.tailscale_dns = self._get_tailscale_dns()
            self.ip_item.title = (
                f"Tailscale IP: {self.tailscale_ip or 'Not connected'}"
            )
            self.dns_item.title = (
                f"MagicDNS: {self.tailscale_dns or 'Not available'}"
            )
        self._poll_counter += 1

        # PID-based health checks every 5s (cheap file reads + signals)
        services = {"ttyd": False, "voice-wrapper": False, "caffeinate": False}
        for name in services:
            pid = self._read_pid(name)
            if pid and self._is_process_alive(pid):
                services[name] = True

        alive = sum(services.values())
        self._services_running = alive == 3 and self.tailscale_ip is not None
        if self._services_running:
            self.title = ICON_GREEN
            self.status_item.title = "Status: Running (all services healthy)"
            self.toggle_item.title = "Stop Services"
        elif alive == 0:
            self.title = ICON_GRAY
            self.status_item.title = "Status: Stopped"
            self.toggle_item.title = "Start Services"
        else:
            self._services_running = True  # partially running = treat as running for toggle
            self.title = ICON_RED
            down = [n for n, up in services.items() if not up]
            self.status_item.title = f"Status: Degraded ({', '.join(down)} down)"
            self.toggle_item.title = "Stop Services"

        # Update URL menu items availability
        has_ip = self.tailscale_ip is not None
        self.open_voice_item.set_callback(
            self.open_voice_ui if has_ip else None
        )
        self.open_terminal_item.set_callback(
            self.open_terminal if has_ip else None
        )

    def _read_pid(self, service_name):
        pid_file = os.path.join(LOG_DIR, f"{service_name}.pid")
        try:
            with open(pid_file) as f:
                return int(f.read().strip())
        except (FileNotFoundError, ValueError):
            return None

    def _is_process_alive(self, pid):
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False

    @rumps.clicked("Open Voice UI")
    def open_voice_ui(self, _):
        host = self.tailscale_dns or self.tailscale_ip
        if host:
            subprocess.run(["open", f"http://{host}:8080"])

    @rumps.clicked("Open Terminal")
    def open_terminal(self, _):
        host = self.tailscale_dns or self.tailscale_ip
        if host:
            subprocess.run(["open", f"http://{host}:7681"])

    @rumps.clicked("Start Services")
    def toggle_services(self, _):
        if self._services_running:
            self._stop_services()
        else:
            self._start_services()

    def _start_services(self):
        if self._services_running and self._service_proc and self._service_proc.poll() is None:
            return  # Already running — skip
        # Kill existing tracked process to prevent zombies
        if self._service_proc and self._service_proc.poll() is None:
            self._service_proc.terminate()
            self._service_proc.wait(timeout=10)
        start_script = os.path.join(SCRIPT_DIR, "start-remote-cli.sh")
        self._service_proc = subprocess.Popen(
            [start_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        self._services_running = True

    def _stop_services(self):
        if self._service_proc and self._service_proc.poll() is None:
            self._service_proc.terminate()
        self._service_proc = None
        self._services_running = False
        stop_script = os.path.join(SCRIPT_DIR, "stop-remote-cli.sh")
        subprocess.run(
            [stop_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @rumps.clicked("ttyd.log")
    def view_ttyd_log(self, _):
        log_path = os.path.join(LOG_DIR, "ttyd.log")
        if os.path.exists(log_path):
            subprocess.run(["open", "-a", "Console", log_path])

    @rumps.clicked("voice-wrapper.log")
    def view_voice_log(self, _):
        log_path = os.path.join(LOG_DIR, "voice-wrapper.log")
        if os.path.exists(log_path):
            subprocess.run(["open", "-a", "Console", log_path])

    @rumps.clicked("Auto-start on Login")
    def toggle_autostart(self, sender):
        if sender.state:
            self._uninstall_login_plist()
            sender.state = False
        else:
            self._install_login_plist()
            sender.state = True

    def _is_login_plist_installed(self):
        return os.path.exists(MENUBAR_PLIST_PATH)

    def _install_login_plist(self):
        script_path = os.path.abspath(__file__)
        if _is_tcc_protected_path(script_path):
            rumps.alert(
                title="Auto-start Warning",
                message=(
                    f"This script is inside a TCC-protected folder:\n"
                    f"{os.path.dirname(script_path)}\n\n"
                    "macOS will block launchd from accessing it after reboot. "
                    "Move the project to ~/Developer or ~/.local/bin first, "
                    "or grant Full Disk Access to the Terminal app."
                ),
                ok="Cancel",
            )
            return
        plist_data = {
            "Label": MENUBAR_PLIST_LABEL,
            "ProgramArguments": [
                sys.executable,
                script_path,
            ],
            "RunAtLoad": True,
            "EnvironmentVariables": {
                "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            },
        }
        os.makedirs(os.path.dirname(MENUBAR_PLIST_PATH), exist_ok=True)
        with open(MENUBAR_PLIST_PATH, "wb") as f:
            plistlib.dump(plist_data, f)

    def _uninstall_login_plist(self):
        if os.path.exists(MENUBAR_PLIST_PATH):
            os.remove(MENUBAR_PLIST_PATH)

    @rumps.clicked("Quit")
    def quit_app(self, _):
        if self._services_running:
            response = rumps.alert(
                title="Quit Claude Code Remote",
                message="Services are still running. Stop them before quitting?",
                ok="Stop & Quit",
                cancel="Quit (keep running)",
            )
            if response == 1:  # "Stop & Quit"
                self._stop_services()
        rumps.quit_application()


if __name__ == "__main__":
    RemoteCLIApp().run()
