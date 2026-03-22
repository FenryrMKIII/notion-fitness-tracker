#!/usr/bin/env python3
"""Refresh Garmin OAuth tokens and upload to GitHub Actions secrets.

Run this locally when the cached Garmin tokens expire (~1 year) and the
Running Sync workflow starts failing with 429 rate-limit errors.

Usage:
    uv run python -m scripts.refresh_garmin_tokens
    uv run python -m scripts.refresh_garmin_tokens --upload
"""

import argparse
import base64
import io
import logging
import os
import subprocess
import tarfile

from dotenv import load_dotenv
from garminconnect import Garmin

logger = logging.getLogger(__name__)

TOKEN_DIR = ".garmin_tokens"
REPO = "FenryrMKIII/notion-fitness-tracker"
SECRET_NAME = "GARMIN_TOKENS"
ENVIRONMENT = "prod"


def login_and_save_tokens() -> None:
    """Authenticate with Garmin and save tokens locally."""
    email = os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD")
    if not email or not password:
        logger.error("GARMIN_EMAIL and GARMIN_PASSWORD must be set in .env")
        raise SystemExit(1)

    client = Garmin(email, password)
    client.login()
    os.makedirs(TOKEN_DIR, exist_ok=True)
    client.garth.dump(TOKEN_DIR)
    logger.info("Garmin login succeeded, tokens saved to %s/", TOKEN_DIR)


def upload_tokens_to_github() -> None:
    """Base64-encode tokens and upload as a GitHub Actions secret."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name in os.listdir(TOKEN_DIR):
            tar.add(os.path.join(TOKEN_DIR, name), arcname=name)
    encoded = base64.b64encode(buf.getvalue()).decode()

    result = subprocess.run(
        [
            "gh", "secret", "set", SECRET_NAME,
            "-R", REPO,
            "--env", ENVIRONMENT,
        ],
        input=encoded,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        logger.error("Failed to upload secret: %s", result.stderr.strip())
        raise SystemExit(1)
    logger.info("Uploaded %s secret to %s (env: %s)", SECRET_NAME, REPO, ENVIRONMENT)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh Garmin OAuth tokens for CI"
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Also upload tokens to GitHub Actions secrets (requires gh CLI)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    load_dotenv()
    login_and_save_tokens()

    if args.upload:
        upload_tokens_to_github()
    else:
        logger.info(
            "Tokens saved locally. Run with --upload to push to GitHub, or run:\n"
            "  tar -czf - -C %s . | base64 | tr -d '\\n' | "
            "gh secret set %s -R %s --env %s",
            TOKEN_DIR, SECRET_NAME, REPO, ENVIRONMENT,
        )


if __name__ == "__main__":
    main()
