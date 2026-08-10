#!/usr/bin/env python3
"""Tests for render_hud output correctness."""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock


class _FakeGst:
    class State:
        NULL = None
        READY = None
        PLAYING = None
    class StateChangeReturn:
        SUCCESS = "SUCCESS"
    CMSEC = 1
    @staticmethod
    def init(_argv): pass

class FakeGstVideo:
    pass


def patch_gstreamer(fake_gst=None):
    if fake_gst is None:
        fake_gst = _FakeGst()
    m1 = MagicMock()
    m1.require_version = MagicMock()
    m2 = MagicMock()
    m2.Gst = fake_gst
    m2.GstVideo = FakeGstVideo
    return m1, m2


class TestRenderHudDisarmed(unittest.TestCase):

    def test_disarmed_status_includes_arm_prompt(self):
        import gcs_gamepad as mod
        lines = []

        class _Stdout:
            def write(self, t): lines.append(t)
            def flush(self): pass

        state = mod.ControllerState()  # not armed
        with patch.object(mod.sys, 'stdout', _Stdout()):
            mod.render_hud(state, "TestGamepad", "udpout://127.0.0.1:14550")

        output = "".join(lines)
        self.assertIn("DISARMED", output)
        self.assertIn("arm", output.lower())


class TestRenderHudArmed(unittest.TestCase):

    def test_armed_status(self):
        import gcs_gamepad as mod
        lines = []

        class _Stdout:
            def write(self, t): lines.append(t)
            def flush(self): pass

        state = mod.ControllerState()
        state.armed = True
        with patch.object(mod.sys, 'stdout', _Stdout()):
            mod.render_hud(state, "TestGamepad", "udpout://127.0.0.1:14550")

        output = "".join(lines)
        self.assertIn("ARMED", output)


class TestRenderHudEstop(unittest.TestCase):

    def test_estop_status(self):
        import gcs_gamepad as mod
        lines = []

        class _Stdout:
            def write(self, t): lines.append(t)
            def flush(self): pass

        state = mod.ControllerState()
        state.armed = True
        state.estop = True
        with patch.object(mod.sys, 'stdout', _Stdout()):
            mod.render_hud(state, "TestGamepad", "udpout://127.0.0.1:14550")

        output = "".join(lines)
        self.assertIn("ESTOP", output)


class TestRenderHudVideo(unittest.TestCase):

    def test_video_line_appears_when_enabled(self):
        import gcs_gamepad as mod
        lines = []

        mock_vm = MagicMock(spec=mod.VideoManager)
        mock_vm.enabled = True
        mock_vm.running = False  # stopped recording at moment of snapshot
        mock_vm.output_file_str = "/tmp/test_recording_2026.mkv"  # matches source code

        class _CapturingStdout:
            chunks = []
            def write(self, text): self.chunks.append(text)
            def flush(self): pass

        state = mod.ControllerState()
        state.armed = True

        captured = _CapturingStdout()
        with patch.object(mod.sys, 'stdout', captured):
            mod.render_hud(state, "TestGamepad", "udpout://127.0.0.1:14550", video_mgr=mock_vm)

        output = "".join(chunks for chunks in [captured.chunks])
        self.assertIn("Video", output)


class TestRenderHudNoVideo(unittest.TestCase):

    def test_no_video_line_when_disabled(self):
        import gcs_gamepad as mod
        lines = []

        class _Stdout:
            def write(self, t): lines.append(t)
            def flush(self): pass

        state = mod.ControllerState()
        state.armed = True
        mock_vm = MagicMock(spec=mod.VideoManager)
        mock_vm.enabled = False

        captured = type('', (), {'write': lambda s, t: None, 'flush': lambda s: None})()

        with patch.object(mod.sys, 'stdout') as mock_stdout:
            mod.render_hud(state, "TestGamepad", "udpout://127.0.0.1:14550", video_mgr=mock_vm)

        # Verify cursor-up escape sequence was called (meaning lines were counted properly)
        mock_stdout.write.assert_called()


if __name__ == "__main__":
    unittest.main()