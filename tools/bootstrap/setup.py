#!/usr/bin/env python3
"""Provision Sandbox credentials through the pyenv-installed VGS CLI.

CLI YAML (including tenant links and one-time secrets) stays in a private journal.
A saved apply attempt is never repeated automatically after an uncertain result.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import uuid

import yaml

API = "https://sandbox.vgsapi.com"
AUTH = "https://auth.verygoodsecurity.com/auth/realms/vgs/protocol/openid-connect/token"
SCOPES = (
    "cards:create", "cards:read", "cards:update", "aliases:write",
    "reveal-sessions:read", "reveal-sessions:write",
    "agent-gateway:read", "agent-gateway:write",
)


class SetupError(Exception):
    pass


def private_write(path, text):
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w") as handle:
        os.chmod(temporary, 0o600)
        handle.write(text)
    temporary.replace(path)


def read_yaml(path):
    try:
        value = yaml.safe_load(path.read_text())
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (OSError, ValueError, yaml.YAMLError):
        raise SetupError("VGS CLI returned unexpected output. Inspect the private setup files locally.") from None


class CLI:
    def __init__(self, executable, directory):
        self.executable, self.directory = executable, directory
        # A personal login must not silently become inherited service-account auth.
        self.environment = {k: v for k, v in os.environ.items() if not k.startswith("VGS_")}

    def run(self, args, filename):
        output = self.directory / filename
        with output.open("w") as stdout, (self.directory / (filename + ".stderr")).open("w") as stderr:
            result = subprocess.run([self.executable, *args], cwd=self.directory,
                                    env=self.environment, stdout=stdout, stderr=stderr)
        if result.returncode:
            raise SetupError(f"VGS CLI {' '.join(args[:2])} failed. Inspect {output.name}.stderr in the private setup directory.")
        return output

    def login(self):
        print(f"Complete VGS login in your browser. If it does not open, inspect {self.directory / 'login.log'} locally.", flush=True)
        self.run(["login"], "login.log")


def choose_organization(document, requested=None, prompt=input):
    organizations = document.get("data", [])
    if not isinstance(organizations, list) or not organizations:
        raise SetupError("No organizations are available to this VGS login.")
    choices = {item["id"]: item for item in organizations
               if isinstance(item, dict) and re.fullmatch(r"AC[A-Za-z0-9]+", item.get("id", ""))}
    if requested is None:
        print("Available organizations:")
        for identifier, item in choices.items():
            # Keep terminal control characters out of names from remote data.
            name = str(item.get("attributes", {}).get("name", ""))
            print(f"  {identifier}  {''.join(c for c in name if c.isprintable())}")
        try:
            requested = prompt("Which organization should this dev kit use? Enter its AC… ID: ").strip()
        except EOFError:
            raise SetupError("Confirm an organization, then run ./awg setup --organization AC….") from None
    if requested not in choices:
        raise SetupError("The selected organization is not in the VGS login's organization list.")
    return requested


def choose_tenant(document, organization, requested=None):
    candidates = []
    for item in document.get("data", []):
        attributes = item.get("attributes", {})
        owner = item.get("relationships", {}).get("organization", {}).get("data", {}).get("id")
        tenant = attributes.get("identifier", "")
        if (owner == organization and attributes.get("environment") == "SANDBOX"
                and re.fullmatch(r"tnt[A-Za-z0-9]+", tenant)):
            candidates.append((attributes.get("name") != "Agent Web Gateway Dev Kit", tenant))
    allowed = {tenant for _, tenant in candidates}
    if requested and requested not in allowed:
        raise SetupError("The requested tenant is not a Sandbox tenant in the confirmed organization.")
    if not candidates:
        raise SetupError("This organization has no accessible Sandbox tenant. Have its administrator provision one, then retry.")
    return requested or sorted(candidates)[0][1]


def verify(credentials):
    """Read-only authentication and Agent Web Gateway permission checks; never echo responses."""
    try:
        request = Request(AUTH, data=urlencode({"grant_type": "client_credentials",
                          "client_id": credentials["VGS_CLIENT_ID"],
                          "client_secret": credentials["VGS_CLIENT_SECRET"]}).encode())
        with urlopen(request, timeout=30) as response:
            token = json.load(response)["access_token"]
        headers = {"Authorization": "Bearer " + token,
                   "VGS-Tenant": credentials["VGS_TENANT"], "Accept": "application/vnd.api+json"}
        for endpoint in ("/reveal-sessions?limit=1", "/agent-gateway-destinations?limit=1"):
            with urlopen(Request(API + endpoint, headers=headers), timeout=30) as response:
                if response.status != 200:
                    raise ValueError()
    except Exception:
        raise SetupError("The saved account could not authenticate or read Sandbox Agent Web Gateway resources. "
                         "Check tenant enablement and permissions with your administrator, then rerun setup. "
                         "The saved creation result will be reused; no additional account will be created.") from None


def credentials_from_result(result, tenant):
    data = result.get("data", {})
    if (result.get("kind") != "ServiceAccount" or data.get("vaults") != [tenant]
            or not all(isinstance(data.get(k), str) and data[k] and not any(c in data[k] for c in "\r\n\0")
                       for k in ("clientId", "clientSecret"))):
        raise SetupError("The creation output has no usable tenant-scoped credentials. Inspect it privately; do not repeat creation.")
    return {"VGS_TENANT": tenant, "VGS_CLIENT_ID": data["clientId"],
            "VGS_CLIENT_SECRET": data["clientSecret"], "VGS_API": API, "VGS_AUTH_URL": AUTH}


def onboard(state, executable, organization=None, tenant=None, force=False):
    credentials_file = state / "sandbox.env"
    pending = state / "setup-pending.json"
    if credentials_file.exists() and not force and not pending.exists():
        saved = dict(line.split("=", 1) for line in credentials_file.read_text().splitlines() if "=" in line)
        if organization or tenant:
            metadata = json.loads((state / "setup-selection.json").read_text()) if (state / "setup-selection.json").exists() else {}
            if ((organization and metadata.get("organization") != organization)
                    or (tenant and saved.get("VGS_TENANT") != tenant)):
                raise SetupError("Saved credentials target a different selection. Use --force to provision a replacement.")
        os.chmod(credentials_file, 0o600)
        verify(saved)
        print("Saved Sandbox credentials verified. No service account was created.")
        return

    if pending.exists():
        attempt = json.loads(pending.read_text())
        if ((organization and organization != attempt["organization"])
                or (tenant and tenant != attempt["tenant"]) or force):
            raise SetupError("A previous creation attempt needs recovery first. Rerun setup without --force or a different selection.")
        directory = Path(attempt["directory"])
        if not (directory / "created.yaml").exists():
            raise SetupError("Service-account creation was interrupted. Inspect the organization and private setup journal before retrying; do not create another account blindly.")
        tenant = attempt["tenant"]
    else:
        directory = state / "setup" / uuid.uuid4().hex
        directory.mkdir(parents=True, mode=0o700)
        cli = CLI(executable, directory)
        cli.login()
        organization = choose_organization(read_yaml(cli.run(["get", "organizations"], "organizations.yaml")), organization)
        tenant = choose_tenant(read_yaml(cli.run(["get", "tenants"], "tenants.yaml")), organization, tenant)
        print(f"Using Sandbox tenant {tenant} in organization {organization}.", flush=True)
        # The released CLI lacks the Agent Web Gateway template. Generate a supported template,
        # then replace its permissions before any remote write.
        template = read_yaml(cli.run(["generate", "service-account", "--template", "vgs-cli", "--tenant", tenant], "generated.yaml"))
        template["data"] = {"name": "awg-dev-kit-" + directory.name[:12], "vaults": [tenant],
                            "scopes": [{"name": scope} for scope in SCOPES]}
        definition = directory / "service-account.yaml"
        private_write(definition, yaml.safe_dump(template))
        attempt = {"organization": organization, "tenant": tenant, "directory": str(directory)}
        # Persist before apply: the CLI create API has no idempotency key.
        private_write(pending, json.dumps(attempt))
        output = cli.run(["apply", "service-account", "-O", organization, "--file", str(definition)], "apply-output.yaml")
        credentials_from_result(read_yaml(output), tenant)
        output.replace(directory / "created.yaml")

    credentials = credentials_from_result(read_yaml(directory / "created.yaml"), tenant)
    verify(credentials)
    private_write(credentials_file, "".join(f"{key}={value}\n" for key, value in credentials.items()))
    private_write(state / "setup-selection.json", json.dumps(attempt))
    pending.unlink()
    (state / "sessions").mkdir(exist_ok=True, mode=0o700)
    print(f"Sandbox credentials saved privately and verified for {tenant}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--vgs", required=True)
    parser.add_argument("--organization")
    parser.add_argument("--tenant")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    state = args.state_dir.expanduser().resolve()
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(state, 0o700)
    with (state / "setup.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.exit(1, "error: another setup process is running.\n")
        try:
            onboard(state, args.vgs, args.organization, args.tenant, args.force)
        except (SetupError, OSError, ValueError, KeyError):
            error = sys.exc_info()[1]
            message = str(error) if isinstance(error, SetupError) else "Setup could not read or save its private state. Inspect it locally."
            parser.exit(1, "error: " + message + "\n")
        except KeyboardInterrupt:
            parser.exit(130, "\nSetup interrupted. Rerun setup to recover any saved creation result.\n")


if __name__ == "__main__":
    main()
