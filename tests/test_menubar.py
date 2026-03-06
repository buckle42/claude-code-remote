"""Tests for scripts/menubar.py — PR review fix verification."""

import json
import os
import plistlib
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

# Add scripts dir to path so we can import menubar
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

# Mock rumps before importing menubar — rumps requires macOS AppKit.
# We need a real App base class so RemoteCLIApp can be instantiated.
_mock_rumps = MagicMock()


class _FakeApp:
    def __init__(self, title=None, quit_button=None):
        self.title = title or ""


_mock_rumps.App = _FakeApp
# Make decorators pass through
_mock_rumps.clicked = lambda name: lambda fn: fn
_mock_rumps.timer = lambda interval: lambda fn: fn
_mock_rumps.MenuItem = MagicMock
sys.modules["rumps"] = _mock_rumps

import menubar


class TestPlistGeneration(unittest.TestCase):
    """Critical #2: plist must use plistlib, not string formatting."""

    def _make_app(self):
        app = menubar.RemoteCLIApp.__new__(menubar.RemoteCLIApp)
        return app

    def test_plist_escapes_special_characters(self):
        """Paths with &, <, > must produce valid XML."""
        app = self._make_app()
        with tempfile.NamedTemporaryFile(suffix=".plist", delete=False) as f:
            tmp_path = f.name
        try:
            with patch("menubar.MENUBAR_PLIST_PATH", tmp_path), \
                 patch("menubar.os.path.abspath", return_value="/Users/test/A&B<C>/menubar.py"), \
                 patch("menubar.os.makedirs"), \
                 patch("menubar.sys.executable", "/usr/bin/python3", create=True):
                app._install_login_plist()
            with open(tmp_path, "rb") as f:
                plist = plistlib.load(f)
            self.assertEqual(plist["Label"], menubar.MENUBAR_PLIST_LABEL)
            prog_args = plist["ProgramArguments"]
            self.assertIn("/Users/test/A&B<C>/menubar.py", prog_args)
        finally:
            os.unlink(tmp_path)

    def test_plist_is_valid_xml(self):
        """Generated plist must be parseable by plistlib."""
        app = self._make_app()
        with tempfile.NamedTemporaryFile(suffix=".plist", delete=False) as f:
            tmp_path = f.name
        try:
            with patch("menubar.MENUBAR_PLIST_PATH", tmp_path), \
                 patch("menubar.os.path.abspath", return_value="/normal/path/menubar.py"), \
                 patch("menubar.os.makedirs"), \
                 patch("menubar.sys.executable", "/usr/bin/python3", create=True):
                app._install_login_plist()
            with open(tmp_path, "rb") as f:
                plist = plistlib.load(f)
            self.assertTrue(plist["RunAtLoad"])
            self.assertIn("/usr/bin", plist["EnvironmentVariables"]["PATH"])
        finally:
            os.unlink(tmp_path)


class TestTCCProtection(unittest.TestCase):
    """Critical #1: warn when script is in a TCC-protected directory."""

    def test_detects_tcc_protected_paths(self):
        protected = [
            os.path.expanduser("~/Documents/project/menubar.py"),
            os.path.expanduser("~/Desktop/menubar.py"),
            os.path.expanduser("~/Downloads/menubar.py"),
        ]
        for path in protected:
            self.assertTrue(
                menubar._is_tcc_protected_path(path),
                f"Should detect {path} as TCC-protected",
            )

    def test_allows_safe_paths(self):
        safe = [
            os.path.expanduser("~/.local/bin/menubar.py"),
            "/usr/local/bin/menubar.py",
            os.path.expanduser("~/Developer/project/menubar.py"),
        ]
        for path in safe:
            self.assertFalse(
                menubar._is_tcc_protected_path(path),
                f"Should allow {path}",
            )

    def test_install_plist_warns_on_tcc_path(self):
        """Installing from a TCC path should show a rumps alert and not write plist."""
        app = menubar.RemoteCLIApp.__new__(menubar.RemoteCLIApp)
        with patch("menubar._is_tcc_protected_path", return_value=True), \
             patch("menubar.rumps") as mock_rumps, \
             patch("menubar.plistlib.dump") as mock_dump:
            mock_rumps.alert.return_value = 0
            app._install_login_plist()
            mock_rumps.alert.assert_called_once()
            mock_dump.assert_not_called()


class TestProcessManagement(unittest.TestCase):
    """Critical #3: Popen handles must be tracked and cleaned up."""

    def test_start_stores_process_handle(self):
        app = menubar.RemoteCLIApp.__new__(menubar.RemoteCLIApp)
        app._service_proc = None
        app._services_running = False
        mock_proc = MagicMock()
        with patch("menubar.subprocess.Popen", return_value=mock_proc):
            app._start_services()
        self.assertIs(app._service_proc, mock_proc)

    def test_stop_terminates_tracked_process(self):
        app = menubar.RemoteCLIApp.__new__(menubar.RemoteCLIApp)
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # still running
        app._service_proc = mock_proc
        app._services_running = True
        with patch("menubar.subprocess.run"):
            app._stop_services()
        mock_proc.terminate.assert_called_once()
        self.assertIsNone(app._service_proc)

    def test_start_kills_existing_before_starting_new(self):
        app = menubar.RemoteCLIApp.__new__(menubar.RemoteCLIApp)
        old_proc = MagicMock()
        old_proc.poll.return_value = None  # still running
        app._service_proc = old_proc
        app._services_running = False
        new_proc = MagicMock()
        with patch("menubar.subprocess.Popen", return_value=new_proc):
            app._start_services()
        old_proc.terminate.assert_called_once()
        self.assertIs(app._service_proc, new_proc)


class TestServiceState(unittest.TestCase):
    """Important #5 & #6: boolean flag and double-start guard."""

    def test_toggle_uses_running_flag_not_title(self):
        app = menubar.RemoteCLIApp.__new__(menubar.RemoteCLIApp)
        app._service_proc = None
        app._services_running = False
        app.toggle_item = MagicMock()
        with patch.object(app, "_start_services") as start:
            app.toggle_services(None)
            start.assert_called_once()

    def test_toggle_stops_when_running(self):
        app = menubar.RemoteCLIApp.__new__(menubar.RemoteCLIApp)
        app._service_proc = None
        app._services_running = True
        app.toggle_item = MagicMock()
        with patch.object(app, "_stop_services") as stop:
            app.toggle_services(None)
            stop.assert_called_once()

    def test_start_is_noop_when_already_running(self):
        """Double-start guard (Important #6)."""
        app = menubar.RemoteCLIApp.__new__(menubar.RemoteCLIApp)
        app._services_running = True
        app._service_proc = MagicMock()
        app._service_proc.poll.return_value = None
        with patch("menubar.subprocess.Popen") as popen:
            app._start_services()
            popen.assert_not_called()


class TestPollingCadence(unittest.TestCase):
    """Important #4: Tailscale info should poll less frequently than health."""

    def test_tailscale_only_polls_every_12th_tick(self):
        """5s * 12 = 60s cadence for Tailscale; every tick for PID checks."""
        app = menubar.RemoteCLIApp.__new__(menubar.RemoteCLIApp)
        app._poll_counter = 0
        app.tailscale_ip = "100.1.2.3"
        app.tailscale_dns = "mac.tail1234.ts.net"
        app.ip_item = MagicMock()
        app.dns_item = MagicMock()
        app.status_item = MagicMock()
        app.toggle_item = MagicMock()
        app.title = ""
        app.open_voice_item = MagicMock()
        app.open_terminal_item = MagicMock()
        app._services_running = False

        with patch.object(app, "_get_tailscale_ip") as ts_ip, \
             patch.object(app, "_get_tailscale_dns") as ts_dns, \
             patch.object(app, "_read_pid", return_value=None), \
             patch.object(app, "_is_process_alive", return_value=False):
            # First call (counter=0) should poll Tailscale
            app.health_check(None)
            self.assertEqual(ts_ip.call_count, 1)

            # Next 11 calls should NOT poll Tailscale
            for _ in range(11):
                app.health_check(None)
            self.assertEqual(ts_ip.call_count, 1)

            # 13th call (counter=12) should poll again
            app.health_check(None)
            self.assertEqual(ts_ip.call_count, 2)


if __name__ == "__main__":
    unittest.main()
