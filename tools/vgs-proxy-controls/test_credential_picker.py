"""File chooser lifecycle without opening desktop dialogs or reading credentials."""
import sys
import time
import unittest
from unittest.mock import patch

from account_files import AccountFileError
from credential_picker import CredentialFilePicker


class PickerTests(unittest.TestCase):
    def setUp(self):
        self.picker = CredentialFilePicker()
        self.addCleanup(self.picker.close)

    def start(self, script):
        with patch('credential_picker.picker_command', return_value=([sys.executable, '-c', script], {1})):
            return self.picker.start('dev')

    def finish(self, job):
        for _ in range(100):
            result = self.picker.status('dev', job['requestId'])
            if result['status'] != 'pending':
                return result
            time.sleep(.01)
        self.fail('Fixture process did not finish')

    def test_selected_path_only_and_cancellation(self):
        for script, expected in [("print('/tmp/Service Account ü.json')", 'selected'), ('pass', 'cancelled'), ('raise SystemExit(1)', 'cancelled')]:
            result = self.finish(self.start(script))
            self.assertEqual(result['status'], expected)
            if expected == 'selected':
                self.assertEqual(result['credentialsFile'], '/tmp/Service Account ü.json')
            else:
                self.assertNotIn('credentialsFile', result)

    def test_failure_does_not_echo_process_output(self):
        result = self.finish(self.start("print('private fixture error'); raise SystemExit(2)"))
        self.assertEqual(result['status'], 'failed')
        self.assertNotIn('private fixture', str(result))

    def test_single_dialog_environment_isolation_and_shutdown(self):
        job = self.start('import time; time.sleep(60)')
        process = self.picker.process
        self.assertEqual(self.picker.start('dev'), job)
        with self.assertRaises(AccountFileError): self.picker.start('sandbox')
        with self.assertRaises(AccountFileError): self.picker.status('sandbox', job['requestId'])
        with self.assertRaises(AccountFileError): self.picker.status('dev', 'different')
        self.picker.close()
        self.assertIsNotNone(process.poll())

    def test_timeout_closes_dialog(self):
        job = self.start('import time; time.sleep(60)')
        self.picker.started -= 301
        self.assertEqual(self.picker.status('dev', job['requestId'])['status'], 'failed')
        self.assertIsNone(self.picker.process)


if __name__ == '__main__': unittest.main()
