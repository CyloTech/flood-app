#!/usr/bin/env python3
"""Check both deployed callback contracts without network or filesystem writes."""
import contextlib
import io
import os
from pathlib import Path
import runpy
import sys
import types
import unittest
from unittest.mock import Mock, patch
from urllib.error import URLError

SCRIPT = Path(__file__).with_name('callback.py')


class CallbackTests(unittest.TestCase):
    def run_callback(self, env, replies=None, configured=False):
        marker = Mock()
        marker.exists.return_value = configured
        response = Mock(status=200)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        opened = Mock(side_effect=replies) if replies else Mock(return_value=response)
        health = Mock()
        result = None
        with patch.dict(os.environ, env, clear=True), \
             patch.dict(sys.modules, {'healthcheck': types.SimpleNamespace(healthy=health)}), \
             patch('pathlib.Path', return_value=marker), \
             patch('urllib.request.urlopen', opened), patch('time.sleep'), \
             contextlib.redirect_stdout(io.StringIO()):
            try:
                runpy.run_path(str(SCRIPT), run_name='__main__')
            except SystemExit as error:
                result = error.code
        return result, opened, marker, health

    def assert_callback(self, env, expected_token):
        result, opened, marker, _ = self.run_callback(env)
        self.assertIsNone(result)
        opened.assert_called_once()
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, 'https://api.cylo.net/v1/apps/installed/262912')
        self.assertEqual(request.get_method(), 'POST')
        self.assertEqual(request.get_header('X-cylo-callback-token'), expected_token)
        self.assertEqual(request.get_header('User-agent'), 'Appbox-Flood/4.16.1')
        marker.touch.assert_called_once()

    def test_catalogue_format(self):
        self.assert_callback({'INSTANCE_ID': '262912?callback_token=fixture-token'}, 'fixture-token')

    def test_separate_token(self):
        self.assert_callback({'INSTANCE_ID': '262912', 'CALLBACK_TOKEN': 'fixture-token'}, 'fixture-token')

    def test_encoded_token(self):
        self.assert_callback({'INSTANCE_ID': '262912?callback_token=a%2Bb%2Fc%3D'}, 'a+b/c=')

    def test_matching_formats(self):
        self.assert_callback({'INSTANCE_ID': '262912?callback_token=fixture-token', 'CALLBACK_TOKEN': 'fixture-token'}, 'fixture-token')

    def test_invalid_configuration_never_sends(self):
        invalid = [
            {}, {'INSTANCE_ID': '262912'}, {'INSTANCE_ID': 'bad', 'CALLBACK_TOKEN': 'fixture-token'},
            {'INSTANCE_ID': '٢٦٢٩١٢', 'CALLBACK_TOKEN': 'fixture-token'},
            {'INSTANCE_ID': '262912?callback_token='},
            {'INSTANCE_ID': '262912?callback_token=one&callback_token=two'},
            {'INSTANCE_ID': '262912?other=fixture-token'},
            {'INSTANCE_ID': '262912?callback_token=one', 'CALLBACK_TOKEN': 'two'},
        ]
        for env in invalid:
            with self.subTest(case=invalid.index(env)):
                result, opened, marker, _ = self.run_callback(env)
                self.assertIsInstance(result, str)
                opened.assert_not_called()
                marker.touch.assert_not_called()

    def test_failed_callback_does_not_mark_installed(self):
        result, opened, marker, _ = self.run_callback(
            {'INSTANCE_ID': '262912?callback_token=fixture-token'},
            replies=[URLError('fixture unavailable')] * 120)
        self.assertEqual(result, 'Install callback timed out')
        self.assertEqual(opened.call_count, 120)
        marker.touch.assert_not_called()

    def test_restart_does_not_repeat_callback(self):
        result, opened, marker, health = self.run_callback({}, configured=True)
        self.assertEqual(result, 0)
        opened.assert_not_called()
        health.assert_not_called()
        marker.touch.assert_not_called()

    def test_explicit_test_bypass(self):
        result, opened, marker, _ = self.run_callback({'SKIP_APPBOX_CALLBACK': '1'})
        self.assertIsNone(result)
        opened.assert_not_called()
        marker.touch.assert_called_once()


if __name__ == '__main__':
    unittest.main()
