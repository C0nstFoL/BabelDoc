#!/usr/bin/env python3
"""Check reachable Git history without printing potentially private content."""

import re
import subprocess
import sys


def git(*args):
    return subprocess.check_output(["git", *args])


def main():
    configured = subprocess.run(
        ["git", "config", "--local", "--get-all", "privacy.forbiddenLiteral"],
        stdout=subprocess.PIPE, check=False,
    )
    literals = configured.stdout.decode().splitlines()
    if configured.returncode not in (0, 1) or not literals or any(not s.strip() for s in literals):
        print("Privacy check requires nonempty local privacy.forbiddenLiteral settings.", file=sys.stderr)
        return 1
    patterns = [re.compile(re.escape(s.encode()), re.IGNORECASE) for s in literals]
    identity = b"BabelDoc contributors <>"
    # Include annotated tags, their messages, every ancestor, file path and file version.
    refs = sys.argv[1:] or ["--all"]
    objects = git("rev-list", "--objects", *refs).splitlines()
    failures = []
    batch = subprocess.Popen(
        ["git", "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
    )
    try:
        for entry in objects:
            oid = entry.split(b" ", 1)[0]
            batch.stdin.write(oid + b"\n")
            batch.stdin.flush()
            header = batch.stdout.readline().split()
            if len(header) != 3:
                raise RuntimeError("Cannot read Git object")
            kind, size = header[1], int(header[2])
            data = batch.stdout.read(size)
            if len(data) != size or batch.stdout.read(1) != b"\n":
                raise RuntimeError("Incomplete Git object")
            if any(p.search(entry) or p.search(data) for p in patterns):
                failures.append((oid.decode(), "forbidden personal text"))
            if kind in (b"commit", b"tag"):
                metadata = data.split(b"\n\n", 1)[0]
                for line in metadata.splitlines():
                    if line.startswith((b"author ", b"committer ", b"tagger ")):
                        actual = line.split(b" ", 1)[1].rsplit(b" ", 2)[0]
                        if actual != identity:
                            failures.append((oid.decode(), "non-anonymous identity"))
        batch.stdin.close()
        if batch.wait() != 0:
            raise RuntimeError("Git object reader failed")
    finally:
        if batch.poll() is None:
            batch.kill()
            batch.wait()
    if failures:
        for oid, reason in failures:
            print(f"BLOCKED {oid[:12]}: {reason}", file=sys.stderr)
        return 1
    print(f"Privacy check passed: {len(objects)} reachable objects.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
