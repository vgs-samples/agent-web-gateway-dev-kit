"""Native file selection. Only the selected path leaves this local process."""
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import uuid

from account_files import AccountFileError


def picker_command():
    # Fixed scripts: no file contents, paths, or other user input become code.
    if sys.platform == 'darwin':
        script = '''ObjC.import('Cocoa');
const app = $.NSApplication.sharedApplication;
app.setActivationPolicy($.NSApplicationActivationPolicyAccessory);
app.activateIgnoringOtherApps(true);
const panel = $.NSOpenPanel.openPanel;
panel.title = 'Choose a service-account file';
panel.prompt = 'Choose';
panel.canChooseFiles = true;
panel.canChooseDirectories = false;
panel.allowsMultipleSelection = false;
panel.showsHiddenFiles = true;
panel.runModal === $.NSModalResponseOK ? ObjC.unwrap(panel.URL.path) : '';'''
        return ['/usr/bin/osascript', '-l', 'JavaScript', '-e', script], set()
    if sys.platform == 'win32':
        script = '''Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Title = 'Choose a service-account file'
$dialog.Filter = 'All files (*.*)|*.*'
$dialog.Multiselect = $false
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
  [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
  [Console]::Write($dialog.FileName)
}
$dialog.Dispose()'''
        return ['powershell.exe', '-NoProfile', '-STA', '-Command', script], set()
    if command := shutil.which('zenity'):
        return [command, '--file-selection', '--title=Choose a service-account file'], {1}
    if command := shutil.which('kdialog'):
        return [command, '--getopenfilename', str(Path.home()), '*', '--title', 'Choose a service-account file'], {1}
    raise AccountFileError('File explorer is unavailable. Enter the local file path instead.')


class CredentialFilePicker:
    """One dialog at a time, polled in short requests so extension workers can restart."""
    def __init__(self):
        self.lock = threading.Lock()
        self.process = None
        self.job = None
        self.cancel_codes = set()
        self.started = 0

    def start(self, environment):
        with self.lock:
            self._refresh()
            if self.process:
                if self.job['environment'] != environment:
                    raise AccountFileError('Finish the open file explorer before choosing another file.')
                return dict(self.job)
            command, self.cancel_codes = picker_command()
            try:
                self.process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                                stderr=subprocess.DEVNULL, encoding='utf-8')
            except OSError:
                raise AccountFileError('File explorer could not open. Enter the local file path instead.') from None
            self.started = time.monotonic()
            self.job = {'requestId': str(uuid.uuid4()), 'environment': environment, 'status': 'pending'}
            return dict(self.job)

    def status(self, environment, request_id):
        with self.lock:
            if not self.job or self.job['requestId'] != request_id or self.job['environment'] != environment:
                raise AccountFileError('File selection is no longer available. Choose the file again.')
            self._refresh()
            return dict(self.job)

    def _refresh(self):
        if not self.process:
            return
        if time.monotonic() - self.started > 300:
            self._stop()
            self.job.update(status='failed', error='File selection timed out. Choose the file again or enter its path.')
            return
        code = self.process.poll()
        if code is None:
            return
        try:
            path = self.process.stdout.read(8193).rstrip('\r\n')
            if code in self.cancel_codes or (code == 0 and not path):
                self.job['status'] = 'cancelled'
            elif code == 0 and len(path) <= 8192 and '\0' not in path and Path(path).is_absolute():
                self.job.update(status='selected', credentialsFile=path)
            else:
                self.job.update(status='failed', error='File explorer could not select a file. Enter its path instead.')
        except (OSError, UnicodeError):
            self.job.update(status='failed', error='File explorer could not select a file. Enter its path instead.')
        finally:
            self.process.stdout.close()
            self.process = None

    def _stop(self):
        if self.process:
            self.process.kill()
            self.process.wait(timeout=5)
            self.process.stdout.close()
            self.process = None

    def close(self):
        with self.lock:
            self._stop()
