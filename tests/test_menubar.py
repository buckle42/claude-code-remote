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


if __name__ == "__main__":
    unittest.main()
