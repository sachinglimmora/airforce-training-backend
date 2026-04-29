"""API key rotation utility.

Updates the .env file (local dev) or prints export commands for CI.
In production, keys should be stored in Vault / AWS Secrets Manager.

Usage:
    python -m scripts.rotate_api_keys --provider gemini
    python -m scripts.rotate_api_keys --provider openai
"""

import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Rotate AI provider API keys")
    parser.add_argument("--provider", choices=["gemini", "openai"], required=True)
    parser.add_argument("--new-key", required=True, help="The new API key value")
    parser.add_argument("--env-file", default=".env", help="Path to .env file")
    args = parser.parse_args()

    env_path = Path(args.env_file)
    key_name = "GEMINI_API_KEY" if args.provider == "gemini" else "OPENAI_API_KEY"

    if not env_path.exists():
        print(f"ERROR: {env_path} not found", file=sys.stderr)
        sys.exit(1)

    lines = env_path.read_text().splitlines()
    updated = False
    new_lines = []
    for line in lines:
        if line.startswith(f"{key_name}="):
            new_lines.append(f"{key_name}={args.new_key}")
            updated = True
        else:
            new_lines.append(line)

    if not updated:
        new_lines.append(f"{key_name}={args.new_key}")

    env_path.write_text("\n".join(new_lines) + "\n")
    print(f"Rotated {key_name} in {env_path}")
    print("IMPORTANT: Restart the application to pick up the new key.")


if __name__ == "__main__":
    main()
