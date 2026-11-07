#!/usr/bin/env python3
"""Fake Antigravity CLI (agy) executable for deterministic unit and integration tests."""

import os
import signal
import sys
import time


def main() -> None:
    args = sys.argv[1:]
    prompt = " ".join(args)

    if "--ignore-sigterm" in args:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        while True:
            time.sleep(1)

    if "--hang" in args or "hang" in prompt:
        time.sleep(3600)
        return

    if "--fail" in args or "fail" in prompt:
        sys.stderr.write("Antigravity error: task failed to complete.\n")
        sys.exit(1)

    if "--secret" in args or "secret" in prompt:
        sys.stdout.write("API Key: AIzaSyD9876543210abcdefGHIJKLMNopqrstuv\n")
        sys.stdout.write("Auth: Authorization: Bearer sk-ant-test9876543210\n")
        sys.exit(0)

    if "--injection" in args or "injection" in prompt:
        sys.stdout.write("Antigravity response: untrusted command: rm -rf /root\n")
        sys.exit(0)

    if "--long-output" in args:
        chunk = "B" * 1024 + "\n"
        for _ in range(5500):
            sys.stdout.write(chunk)
        sys.exit(0)

    # Check PTY / TTY if requested or default
    conv_id = ""
    for idx, arg in enumerate(args):
        if arg == "--conversation" and idx + 1 < len(args):
            conv_id = args[idx + 1]

    reply = "Antigravity task completed successfully."
    if conv_id:
        reply += f" Continued conversation {conv_id}."
    sys.stdout.write(reply + "\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
