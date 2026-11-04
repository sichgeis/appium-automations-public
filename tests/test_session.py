import tempfile
import unittest
from receiptbot.session import capabilities, device_lock


class SafetyTests(unittest.TestCase):
    def config(self):
        return {"server_url": "http://127.0.0.1:4723", "udid": "SYNTHETIC",
                "apps": {"kaufland": {"bundle_id": "test.synthetic"}}}

    def test_existing_apps_are_preserved(self):
        caps = capabilities(self.config(), "kaufland")
        self.assertTrue(caps["appium:noReset"])
        self.assertFalse(caps["appium:fullReset"])
        self.assertFalse(caps["appium:autoAcceptAlerts"])
        self.assertFalse(caps["appium:autoDismissAlerts"])
        self.assertFalse(caps["appium:shouldTerminateApp"])
        self.assertNotIn("appium:app", caps)
        self.assertEqual(caps['appium:wdaBindingIP'], '127.0.0.1')

    def test_remote_server_rejected(self):
        for url in ["http://0.0.0.0:4723", "http://example.org", "http://secret@127.0.0.1:4723"]:
            config = self.config()
            config["server_url"] = url
            with self.assertRaises(ValueError):
                capabilities(config, "kaufland")

    def test_missing_observed_identity_rejected(self):
        config = self.config()
        config["apps"]["kaufland"]["bundle_id"] = ""
        with self.assertRaises(ValueError):
            capabilities(config, "kaufland")

    def test_parallel_session_rejected_and_lock_resumes(self):
        with tempfile.TemporaryDirectory() as directory:
            with device_lock(directory):
                with self.assertRaises(ValueError):
                    with device_lock(directory):
                        self.fail("parallel lock acquired")
            with device_lock(directory):
                pass


if __name__ == "__main__":
    unittest.main()
