"""Offline regression suite: no real HTTP, credentials, market data or messages."""
import base64
import importlib
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import morning_delivery as delivery


def response(status, body=None):
    return Mock(status_code=status, ok=200 <= status < 300,
                json=Mock(return_value=body))


class MorningTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"GITHUB_TOKEN": "fake",
                             "GITHUB_REPOSITORY": "test/repo"}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.network = patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden"))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.receipts = {}
        self.get = patch.object(delivery.requests, "get", side_effect=self.read).start()
        self.put = patch.object(delivery.requests, "put", side_effect=self.write).start()
        self.post = patch.object(delivery.requests, "post", side_effect=AssertionError("Unexpected send")).start()
        self.addCleanup(patch.stopall)
        self.send = Mock()

    def read(self, url, **kwargs):
        self.assertEqual(kwargs['params'], {'ref': 'main'})
        if url in self.receipts:
            return response(200, {'content': self.receipts[url]})
        return response(404)

    def write(self, url, **kwargs):
        self.receipts[url] = kwargs['json']['content']
        self.assertEqual(kwargs['json']['branch'], 'main')
        return response(201)

    def run_send(self, day='2026-10-02'):
        return delivery.send_morning('mock morning', self.send, day)

    def test_schedule_then_dispatch(self):
        self.assertTrue(self.run_send())
        self.assertFalse(self.run_send())
        self.send.assert_called_once()

    def test_dispatch_then_delayed_schedule(self):
        self.assertTrue(self.run_send())
        # New runner/stale checkout still reads the remote receipt.
        self.assertFalse(self.run_send())
        self.send.assert_called_once()

    def test_concurrent_triggers_with_workflow_serialization(self):
        lock = threading.Lock()
        def workflow(_):
            with lock:  # GitHub concurrency contract, verified below in YAML.
                return self.run_send()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(workflow, range(4)))
        self.assertEqual(sum(results), 1)
        self.send.assert_called_once()
        yaml = Path(__file__).with_name('tw-board.yml')
        if not yaml.exists():
            yaml = Path(__file__).parent / '.github/workflows/tw-board.yml'
        text = yaml.read_text(encoding='utf-8')
        self.assertIn('group: tw-board-morning-delivery\n  cancel-in-progress: false', text)
        self.assertIn('GITHUB_TOKEN: ${{ github.token }}', text)
        self.assertIn("cron: '19 0 * * 1-6'", text)

    def test_failure_retry(self):
        self.send.side_effect = RuntimeError('mock rejection')
        with self.assertRaises(RuntimeError):
            self.run_send()
        self.assertEqual(self.receipts, {})
        self.send.side_effect = None
        self.assertTrue(self.run_send())
        self.assertEqual(self.send.call_count, 2)

    def test_taiwan_midnight(self):
        before = delivery.taipei_day(datetime(2026, 10, 2, 15, 59, tzinfo=timezone.utc))
        after = delivery.taipei_day(datetime(2026, 10, 2, 16, 0, tzinfo=timezone.utc))
        self.assertEqual((before, after), ('2026-10-02', '2026-10-03'))
        self.assertTrue(self.run_send(before))
        self.assertTrue(self.run_send(after))

    def test_receipt_read_failure_blocks_send(self):
        self.get.side_effect = None
        self.get.return_value = response(403)
        with self.assertRaisesRegex(RuntimeError, 'not sent'):
            self.run_send()
        self.send.assert_not_called()

    def test_corrupt_receipt_blocks_send(self):
        self.get.side_effect = None
        self.get.return_value = response(200, {'content': 'bad'})
        with self.assertRaises(RuntimeError):
            self.run_send()
        self.send.assert_not_called()

    def test_missing_credentials_blocks_send(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                self.run_send()
        self.send.assert_not_called()

    def test_receipt_write_failure_is_explicit(self):
        self.put.side_effect = None
        self.put.return_value = response(500)
        with self.assertRaisesRegex(RuntimeError, 'inspect before rerun'):
            self.run_send()
        self.send.assert_called_once()

    def test_receipt_has_no_message_or_recipient(self):
        self.run_send()
        data = json.loads(base64.b64decode(next(iter(self.receipts.values()))))
        self.assertEqual(data, {'date': '2026-10-02', 'sent': True})

    def load_alert(self):
        board = types.ModuleType('board_html')
        for name, value in {'parse_report': Mock(), 'oneliner': Mock(), 'CHAIN_MAP': {},
                            'CHAIN_ICON': {}, 'CHAIN_ORDER': [], 'TW_NAME': {}}.items():
            setattr(board, name, value)
        tw = types.ModuleType('tw_report')
        tw.convert = Mock()
        with patch.dict(sys.modules, {'board_html': board, 'tw_report': tw}):
            sys.modules.pop('alert_telegram', None)
            return importlib.import_module('alert_telegram')

    def test_telegram_requires_explicit_success(self):
        alert = self.load_alert()
        for reply in [response(400, {'ok': False}), response(200, {'ok': False}), response(200, {})]:
            with self.subTest(reply=reply):
                self.post.side_effect = None
                self.post.return_value = reply
                with self.assertRaises(RuntimeError):
                    alert.send_text('test')
        self.post.return_value = response(200, {'ok': True})
        alert.send_text('test')

    def test_state_writes_and_close_reminder_survive_dedup_and_failure(self):
        alert = self.load_alert()
        flip = {'code': 'TEST', 'name': 'fixture', 'word': '翻空', 'sig': 'st', 'dir': -1}
        st = types.ModuleType('st_alert')
        st.detect_flips = Mock(return_value=([flip], [], {}))
        oldcwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                Path('state').mkdir()
                Path('state/close_alerts.json').write_text(json.dumps({'alerts': [
                    dict(flip, sent=datetime.now().isoformat())]}), encoding='utf-8')
                with patch.dict(sys.modules, {'st_alert': st}), \
                     patch.object(sys, 'argv', ['alert', 'mock.md', 'mock.html']), \
                     patch.object(alert, 'collect', return_value=[('test', 'TW', '🟢', 'TEST', '', '')]), \
                     patch.object(alert, '_send_priority_alert') as priority, \
                     patch.object(alert, 'send_text', self.send):
                    alert.main()
                    self.assertIn('收盤後已推過', self.send.call_args.args[0])
                    self.assertEqual(priority.call_args.args[0], [])
                    alert.main()
                    self.send.assert_called_once()
                    self.assertEqual(json.loads(Path('state/signals.json').read_text(encoding='utf-8')), {'TW:TEST': '🟢'})
                    self.assertEqual(json.loads(Path('state/st_flips_today.json').read_text(encoding='utf-8'))['flips_hold'], [flip])
                    with patch.object(alert, 'send_morning', side_effect=RuntimeError('mock failure')):
                        Path('state/st_flips_today.json').unlink()
                        with self.assertRaises(RuntimeError):
                            alert.main()
                        self.assertTrue(Path('state/st_flips_today.json').exists())
            finally:
                os.chdir(oldcwd)


if __name__ == '__main__':
    unittest.main()
