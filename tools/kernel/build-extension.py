#!/usr/bin/env python3
"""Build the Control Panel extension as a zip for a browser that cannot reach a local helper.

The panel is generated without a helper address, so it shows the session and switches the
browser's route, and the features that need the helper stay disabled. The zip contains the
session's proxy credentials: keep it private and delete it after use.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vgs-proxy-controls"))

from environments import EnvironmentClient  # noqa: E402
from session_catalog import alive, session_config  # noqa: E402
from session_proxy_extension import write_extension  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True, type=Path, help="Original saved reveal-session creation response")
    parser.add_argument("--credentials-file", required=True, type=Path, help="Private service-account environment file")
    parser.add_argument("--output", required=True, type=Path, help="Zip file to write")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        session = args.session.expanduser().resolve()
        attributes = json.loads(session.read_text())["data"]["attributes"]
        if not alive(attributes):
            raise ValueError("Session expired or revoked")
        tenant = EnvironmentClient(args.credentials_file.expanduser().resolve(), "sandbox").tenant
        config = session_config(session, attributes["proxy"]["ca_bundle"], "sandbox", tenant)
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "extension"
            write_extension(folder, config["pacUrl"], config["credentials"], config["proxies"]["session"],
                            config["proxies"]["egress"], session_id=config["sessionId"],
                            expires_at=config["expiresAt"], catalog=None)
            with zipfile.ZipFile(args.output, "w", zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(folder.rglob("*")):
                    if path.is_file():
                        archive.write(path, path.relative_to(folder).as_posix())
        args.output.chmod(0o600)
    except Exception:
        # Session JSON and URLs can contain secrets. Never print them.
        sys.exit("Could not build the Control Panel for this session. Check that the session is active and belongs to the saved tenant.")


if __name__ == "__main__":
    main()
