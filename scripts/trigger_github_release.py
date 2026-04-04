#!/usr/bin/env python3
"""
Erstellt ein GitHub-Release (und Tag) über die REST API und stößt damit die Pipeline an.

Der Workflow ".github/workflows/release.yml" startet bei push von Tags "v*".

Voraussetzungen:
  - Git im PATH; Aufruf aus dem synarius-studio-Repo-Root oder beliebig (Skript wechselt ins Repo).
  - Umgebungsvariable GITHUB_TOKEN oder GH_TOKEN: PAT oder Fine-grained Token mit
    Inhalt-Releases/Tags schreiben für das Ziel-Repo (z. B. "Contents: Read and write").

Hinweis: Im Job "release-assets" setzt der Workflow prerelease auf true, wenn der Tag
mit "v0.0." beginnt – unabhängig von --prerelease hier.

Beispiele:
  set GITHUB_TOKEN=ghp_...
  python scripts/trigger_github_release.py v0.0.18 --prerelease
  python scripts/trigger_github_release.py v0.1.16 --push-dev
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

TAG_RE = re.compile(r"^v\d+\.\d+\.\d+$")
ORIGIN_REPO_RE = re.compile(r"github\.com[:/]([^/]+)/([^/.]+?)(?:\.git)?$")
API_VERSION = "2022-11-28"


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _run_git(args: list[str], *, cwd: Path) -> str:
    p = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {p.stderr.strip() or p.stdout.strip()}")
    return p.stdout.strip()


def _repo_from_origin(cwd: Path) -> str | None:
    try:
        url = _run_git(["remote", "get-url", "origin"], cwd=cwd)
    except RuntimeError:
        return None
    m = ORIGIN_REPO_RE.search(url.replace("\\", "/"))
    if not m:
        return None
    return f"{m.group(1)}/{m.group(2)}"


def _token() -> str:
    t = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not t or not t.strip():
        sys.exit(
            "GITHUB_TOKEN oder GH_TOKEN muss gesetzt sein (PAT mit Rechten für Releases/Tags)."
        )
    return t.strip()


def _create_release(
    *,
    token: str,
    repo: str,
    tag: str,
    target_branch: str,
    prerelease: bool,
    api_base: str,
) -> dict:
    owner, _, name = repo.partition("/")
    if not owner or not name:
        sys.exit(f"Ungültiges Repo-Format (owner/name erwartet): {repo!r}")

    url = f"{api_base.rstrip('/')}/repos/{owner}/{name}/releases"
    payload = {
        "tag_name": tag,
        "target_commitish": target_branch,
        "name": tag,
        "draft": False,
        "prerelease": prerelease,
        "generate_release_notes": True,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": API_VERSION,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            err = json.loads(body)
            msg = err.get("message", body)
        except json.JSONDecodeError:
            msg = body
        sys.exit(f"GitHub API HTTP {e.code}: {msg}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="GitHub-Release per REST API anlegen (triggert Tag-Workflow)."
    )
    parser.add_argument("tag", help="Tag, z. B. v0.0.18 (Format vX.Y.Z)")
    parser.add_argument(
        "--prerelease",
        action="store_true",
        help="Release als Pre-release markieren",
    )
    parser.add_argument(
        "--target-branch",
        default="dev",
        help="Branch für target_commitish (Standard: dev)",
    )
    parser.add_argument(
        "--repo",
        default="",
        help="owner/repo; leer = aus git remote origin ableiten",
    )
    parser.add_argument(
        "--push-dev",
        action="store_true",
        help="Vorher: git push origin <target-branch>",
    )
    parser.add_argument(
        "--api-url",
        default=os.environ.get("GITHUB_API_URL", "https://api.github.com"),
        help="API-Basis-URL (Standard: https://api.github.com; für GHE anpassen)",
    )
    args = parser.parse_args()

    tag = args.tag.strip()
    if not TAG_RE.match(tag):
        sys.exit(
            f"Tag muss Form vX.Y.Z haben (wie im Release-Workflow). Erhalten: {tag!r}"
        )

    root = _repo_root()
    os.chdir(root)

    repo = args.repo.strip() or _repo_from_origin(root)
    if not repo:
        sys.exit("Konnte owner/repo nicht aus origin ableiten; --repo setzen.")

    if _run_git(["tag", "-l", tag], cwd=root):
        sys.exit(f"Lokaler Tag {tag!r} existiert bereits.")

    remote_tags = _run_git(["ls-remote", "--tags", "origin", f"refs/tags/{tag}"], cwd=root)
    if remote_tags:
        sys.exit(
            f"Tag {tag!r} existiert bereits auf origin. Release/Tag dort entfernen oder anderen Tag wählen."
        )

    try:
        cur = _run_git(["branch", "--show-current"], cwd=root)
    except RuntimeError:
        cur = ""
    if cur and cur != args.target_branch:
        print(
            f"Warnung: Aktueller Branch ist {cur!r}, Release zeigt auf {args.target_branch!r}. "
            f"Mit --push-dev wird nur {args.target_branch!r} gepusht.",
            file=sys.stderr,
        )

    if args.push_dev:
        print(f"Push origin {args.target_branch} …", flush=True)
        subprocess.run(
            ["git", "push", "origin", args.target_branch],
            cwd=root,
            check=True,
        )

    if tag.startswith("v0.0.") and not args.prerelease:
        print(
            "Warnung: Tags v0.0.* werden im Workflow-Job 'release-assets' weiterhin als "
            "Pre-release behandelt (startsWith github.ref_name, 'v0.0.').",
            file=sys.stderr,
        )

    token = _token()
    print(f"Erstelle Release {tag} auf {repo} (target: {args.target_branch}) …", flush=True)
    rel = _create_release(
        token=token,
        repo=repo,
        tag=tag,
        target_branch=args.target_branch,
        prerelease=args.prerelease,
        api_base=args.api_url,
    )
    html_url = rel.get("html_url", "")
    if html_url:
        print(html_url)
    print(f"Pipeline: https://github.com/{repo}/actions", flush=True)


if __name__ == "__main__":
    main()
