"""Seed DevTools preferences only before a new Chromium profile is launched."""
import json
import re
from pathlib import Path

HAR_PREFERENCE = 'network.show-options-to-generate-har-with-sensitive-data'


def prepare_profile(profile):
    path = Path(profile) / 'Default/Preferences'
    if path.exists():
        raise ValueError('Use a new profile; never overwrite an open browser profile')
    path.parent.mkdir(parents=True, exist_ok=True)
    values = {HAR_PREFERENCE: 'true', 'network-log.preserve-log': 'true'}
    path.write_text(json.dumps({'extensions': {'ui': {'developer_mode': True}}, 'devtools': {
        'synced_preferences': values, 'synced_preferences_sync_disabled': values,
        'preferences': {'network-log.preserve-log': 'true'}
    }}))
    path.chmod(0o600)


def har_recording_filter():
    """Keep merchant traffic, excluding local credentials and Collect tokenization."""
    return re.compile(r'^https?://(?!(?:127\.0\.0\.1|localhost|\[::1\])(?::|/))(?![^/]*\.verygoodvault\.(?:io|com)(?::|/))(?!(?:[^/]*\.)?vgsapi\.(?:io|com)(?::|/))', re.IGNORECASE)
