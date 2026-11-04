from contextlib import redirect_stdout
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from receiptbot.readiness import device_status, ready


class ReadinessTests(unittest.TestCase):
    def response(self, **kwargs):
        connection = dict(transportType='wired', pairingState='paired')
        connection.update(kwargs)
        return SimpleNamespace(returncode=0, stdout=json.dumps(dict(result=dict(
            connectionProperties=connection, deviceProperties=dict(developerModeStatus='enabled')))))

    def test_missing_phone_and_network_only_never_ready(self):
        for result in (SimpleNamespace(returncode=1), self.response(transportType='localNetwork')):
            with patch('receiptbot.readiness.subprocess.run', return_value=result):
                self.assertFalse(device_status({'udid':'SYNTHETIC'})[0])

    def test_locked_or_unknown_lock_shape_cannot_start(self):
        for state in ({'passcodeRequired':True}, {}, {'passcodeRequired':'false'}):
            lock = SimpleNamespace(returncode=0, stdout=json.dumps(dict(result=state)))
            with patch('receiptbot.readiness.subprocess.run', side_effect=[self.response(), lock]):
                self.assertFalse(device_status({'udid':'SYNTHETIC'})[0])

    def test_unlocked_usb_is_required_but_does_not_launch_wda(self):
        lock = SimpleNamespace(returncode=0, stdout=json.dumps(dict(result=dict(passcodeRequired=False))))
        with patch('receiptbot.readiness.subprocess.run', side_effect=[self.response(), lock]):
            passed, _ = device_status({'udid':'SYNTHETIC'})
        self.assertTrue(passed)

    def test_failed_local_check_prevents_device_poll(self):
        with patch('receiptbot.readiness.local_checks', return_value=[(False,'synthetic failure')]), \
             patch('receiptbot.readiness.device_status') as status, redirect_stdout(io.StringIO()):
            self.assertEqual(ready({}, 900), 2)
            status.assert_not_called()

    def test_no_wait_and_bounded_wait_until_unlocked(self):
        with patch('receiptbot.readiness.local_checks', return_value=[(True,'synthetic ready')]), \
             patch('receiptbot.readiness.device_status', return_value=(False,'not connected')), redirect_stdout(io.StringIO()):
            self.assertEqual(ready({}, 0), 2)
        with patch('receiptbot.readiness.local_checks', return_value=[(True,'synthetic ready')]), \
             patch('receiptbot.readiness.device_status', side_effect=[(False,'locked'),(True,'ready')]), \
             patch('receiptbot.readiness.time.sleep'), redirect_stdout(io.StringIO()):
            self.assertEqual(ready({}, 10), 0)

    def test_invalid_wait_does_not_check_or_change_state(self):
        for seconds in (-1, 3601):
            with self.assertRaises(ValueError):
                ready({}, seconds)

    def test_devicectl_timeout_meets_actual_cli_minimum(self):
        lock = SimpleNamespace(returncode=0, stdout=json.dumps(dict(result=dict(passcodeRequired=False))))
        with patch('receiptbot.readiness.subprocess.run', side_effect=[self.response(), lock]) as run:
            self.assertTrue(device_status({'udid':'SYNTHETIC'})[0])
        for call in run.call_args_list:
            args = call.args[0]
            seconds = int(args[args.index('--timeout') + 1])
            self.assertGreaterEqual(seconds, 5)
            self.assertGreater(call.kwargs['timeout'], seconds)
