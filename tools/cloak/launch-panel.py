#!/usr/bin/env python3
"""Open CloakBrowser with the Agent Web Gateway Control Panel loaded.

Start the control panel helper first (./awg panel ...). It generates the private
extension folder this script loads. Then run:

    ./awg browser --session /path/to/RS....json [url]

The session file is used only to trust that session's VGS certificate in this
browser. The control panel itself chooses the route and answers the proxy login.
"""
import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[2]
DEFAULT_EXTENSION = KIT / "tools" / "vgs-proxy-controls" / ".private-extension"
DEFAULT_PROFILE = Path.home() / ".awg-dev-kit" / "cloak-profile"


def ca_pin(session_path):
    """Return the SPKI pin of the session's CA, so only that CA is trusted extra."""
    bundle = json.loads(session_path.read_text())["data"]["attributes"]["proxy"]["ca_bundle"]
    public_key = subprocess.check_output(["openssl", "x509", "-pubkey", "-noout"], input=bundle.encode())
    der = subprocess.check_output(["openssl", "pkey", "-pubin", "-outform", "der"], input=public_key)
    return base64.b64encode(hashlib.sha256(der).digest()).decode()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("url", nargs="?", help="Page to open in a second tab")
    parser.add_argument("--session", type=Path, help="Saved reveal-session creation response; trusts its CA")
    parser.add_argument("--extension", type=Path, default=DEFAULT_EXTENSION, help="Generated control panel extension folder")
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE, help="Browser profile folder (kept between runs)")
    args = parser.parse_args()
    os.umask(0o077)

    extension = args.extension.expanduser().resolve()
    if not (extension / "manifest.json").is_file():
        sys.exit(f"No generated extension at {extension}.\nStart the helper first:  ./awg panel --session ... --credentials-file ... --sessions-dir ...")

    try:
        from cloakbrowser import launch_persistent_context
    except ImportError:
        sys.exit("CloakBrowser is not available. Run this through the kit launcher:  ./awg browser ...")

    browser_args = ["--disable-quic"]
    if args.session:
        session = args.session.expanduser().resolve()
        if not session.is_file():
            sys.exit(f"No session file at {session}")
        try:
            browser_args.append("--ignore-certificate-errors-spki-list=" + ca_pin(session))
        except (OSError, KeyError, ValueError, subprocess.CalledProcessError):
            sys.exit("Could not read the session's CA certificate. Is this the original creation response, and is openssl installed?")

    profile = args.profile.expanduser().resolve()
    if not profile.exists():
        (profile / "Default").mkdir(parents=True)
        (profile / "Default" / "Preferences").write_text(json.dumps({"extensions": {"ui": {"developer_mode": True}}}))

    try:
        context = launch_persistent_context(str(profile), headless=False, extension_paths=[str(extension)], args=browser_args)
    except Exception as error:  # the license check and the first-run download both surface here
        name = type(error).__name__
        if "License" in name:
            sys.exit("CloakBrowser needs a license key (the free tier is enough).\nGet one and save it with:  ./awg cloak-login")
        sys.exit(f"CloakBrowser could not start ({name}). On macOS, allow the browser once if Gatekeeper blocked it, then try again.")

    try:
        worker = context.service_workers[0] if context.service_workers else context.wait_for_event("serviceworker", timeout=20000)
        extension_id = worker.url.split("/")[2]
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(f"chrome-extension://{extension_id}/popup.html")
        if args.url:
            context.new_page().goto(args.url, wait_until="commit")
        print("CloakBrowser is open with the control panel. Close the browser window to finish.", flush=True)
        context.wait_for_event("close", timeout=0)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            context.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
