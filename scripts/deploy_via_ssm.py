"""Run the EC2 deployment through Systems Manager without sending secrets in commands."""
from __future__ import annotations

import base64
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLL_SECONDS = 8
TIMEOUT_SECONDS = 900
TERMINAL_STATUSES = {"Success", "Cancelled", "TimedOut", "Failed", "Cancelling"}


def build_remote_command(environment: dict[str, str], parameter_name: str) -> str:
    """Build a Run Command payload; only the SecureString parameter name is secret-related."""
    required = (
        "AWS_REGION",
        "ECR_REGISTRY",
        "ECR_REPOSITORY",
        "IMAGE_TAG",
        "DVC_REMOTE_URL",
        "EXPECTED_MODEL_VERSION",
        "PRODUCTION_HTTPS_URL",
    )
    missing = [name for name in required if not environment.get(name)]
    if missing:
        raise ValueError(f"Missing deployment configuration: {', '.join(missing)}")
    if not parameter_name.startswith("/voltguard/deploy/"):
        raise ValueError("API-key parameter must be under /voltguard/deploy/")

    deploy_script = (ROOT / "scripts" / "deploy.sh").read_bytes()
    guards_script = (ROOT / "scripts" / "deploy_guards.sh").read_bytes()
    deploy_b64 = base64.b64encode(deploy_script).decode("ascii")
    guards_b64 = base64.b64encode(guards_script).decode("ascii")

    lines = [
        "set -eu",
        "umask 077",
        "install -d -m 700 /tmp/voltguard",
        f"printf '%s' {shlex.quote(deploy_b64)} | base64 --decode > /tmp/voltguard/deploy.sh",
        f"printf '%s' {shlex.quote(guards_b64)} | base64 --decode > /tmp/voltguard/deploy_guards.sh",
        "chmod 700 /tmp/voltguard/deploy.sh /tmp/voltguard/deploy_guards.sh",
        "API_KEY_FILE=/tmp/voltguard/api-key.env",
        f"API_KEY_PARAMETER={shlex.quote(parameter_name)}",
        "cleanup() { rm -f -- \"$API_KEY_FILE\" /tmp/voltguard/deploy.sh /tmp/voltguard/deploy_guards.sh; }",
        "trap cleanup EXIT",
        "aws ssm get-parameter --name \"$API_KEY_PARAMETER\" --with-decryption --query Parameter.Value --output text > \"$API_KEY_FILE\"",
        "chmod 600 \"$API_KEY_FILE\"",
    ]
    for name in required:
        lines.append(f"export {name}={shlex.quote(environment[name])}")
    lines.extend(
        [
            'export HOST_PORT="8000"',
            'export API_KEY_FILE',
            "bash /tmp/voltguard/deploy.sh",
        ]
    )
    return "\n".join(lines)


def build_secret_file_contents(api_key: str) -> str:
    """Format the SecureString exactly as the remote deploy script's env file expects."""
    if not api_key or "\n" in api_key or "\r" in api_key:
        raise ValueError("API_KEY is missing or contains an unsupported line break")
    return f"API_KEY={api_key}"


def _aws(*arguments: str, capture: bool = True) -> str:
    aws_environment = os.environ.copy()
    aws_environment.pop("API_KEY", None)
    result = subprocess.run(
        ["aws", *arguments],
        check=False,
        text=True,
        capture_output=capture,
        env=aws_environment,
    )
    if result.returncode:
        detail = (result.stderr or "").strip()
        raise RuntimeError(f"AWS CLI command failed ({result.returncode}): {detail}")
    return result.stdout.strip() if capture else ""


def deploy(environment: dict[str, str]) -> None:
    api_key = environment.get("API_KEY", "")
    instance_id = environment.get("EC2_INSTANCE_ID", "")
    run_id = environment.get("GITHUB_RUN_ID", "")
    run_attempt = environment.get("GITHUB_RUN_ATTEMPT", "1")
    secret_file_contents = build_secret_file_contents(api_key)
    if not instance_id.startswith("i-") or not run_id.isdigit() or not run_attempt.isdigit():
        raise ValueError("EC2_INSTANCE_ID or GitHub run identifier is invalid")

    region = environment.get("AWS_REGION", "ap-south-1")
    parameter_name = f"/voltguard/deploy/{run_id}-{run_attempt}/api-key"
    remote_command = build_remote_command(environment, parameter_name)

    with tempfile.TemporaryDirectory(prefix="voltguard-ssm-") as temp_dir:
        payload_path = Path(temp_dir) / "parameter.json"
        payload_path.write_text(
            json.dumps(
                {
                    "Name": parameter_name,
                    "Description": "Temporary VoltGuard deployment API key",
                    "Type": "SecureString",
                    "Value": secret_file_contents,
                    "Tier": "Standard",
                    "Overwrite": False,
                }
            ),
            encoding="utf-8",
        )
        os.chmod(payload_path, 0o600)
        try:
            _aws(
                "ssm",
                "put-parameter",
                "--region",
                region,
                "--cli-input-json",
                f"file://{payload_path}",
            )
            with payload_path.open("w", encoding="utf-8") as payload_file:
                json.dump(
                    {
                        "commands": [remote_command],
                        "executionTimeout": [str(TIMEOUT_SECONDS)],
                    },
                    payload_file,
                )
            command_id = _aws(
                "ssm",
                "send-command",
                "--region",
                region,
                "--instance-ids",
                instance_id,
                "--document-name",
                "AWS-RunShellScript",
                "--parameters",
                f"file://{payload_path}",
                "--comment",
                f"VoltGuard deployment {run_id}-{run_attempt}",
                "--query",
                "Command.CommandId",
                "--output",
                "text",
            )
            print(f"SSM deployment command started: {command_id}")
            deadline = time.monotonic() + TIMEOUT_SECONDS
            invocation: dict[str, object] = {}
            while time.monotonic() < deadline:
                try:
                    response = _aws(
                        "ssm",
                        "get-command-invocation",
                        "--region",
                        region,
                        "--command-id",
                        command_id,
                        "--instance-id",
                        instance_id,
                        "--output",
                        "json",
                    )
                    invocation = json.loads(response)
                except RuntimeError as error:
                    # SSM may not have created the per-instance invocation record yet.
                    if "InvocationDoesNotExist" not in str(error):
                        raise
                status = str(invocation.get("Status", "Pending"))
                if status in TERMINAL_STATUSES:
                    break
                time.sleep(POLL_SECONDS)
            else:
                raise TimeoutError("Timed out waiting for the SSM deployment command")

            stdout = str(invocation.get("StandardOutputContent", ""))
            stderr = str(invocation.get("StandardErrorContent", ""))
            if stdout:
                print(stdout, end="" if stdout.endswith("\n") else "\n")
            if stderr:
                print(stderr, file=sys.stderr)
            if invocation.get("Status") != "Success":
                raise RuntimeError(f"SSM deployment failed with status {invocation.get('Status')}")
        finally:
            try:
                _aws("ssm", "delete-parameter", "--region", region, "--name", parameter_name)
            except RuntimeError as error:
                print(f"::warning::Could not remove temporary SSM API-key parameter: {error}", file=sys.stderr)


def main() -> int:
    try:
        deploy(dict(os.environ))
    except (RuntimeError, TimeoutError, ValueError) as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
