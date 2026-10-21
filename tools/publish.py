# -*- coding: utf-8 -*-
"""
Maintainer helper: create the GitHub repository for this project and push.

    python tools/publish.py                  # public repo named "shake-cursor"
    python tools/publish.py my-name --private
    python tools/publish.py --local-only     # just init + commit, no network

Requires the GitHub CLI (https://cli.github.com) to be logged in once:

    gh auth login

Everything is idempotent: running it twice will not create a second repo, it
just pushes.
"""

import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GH_CANDIDATES = [
    os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "GitHub CLI", "gh.exe"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "GitHubCLI", "bin", "gh.exe"),
]


def find_gh():
    exe = shutil.which("gh")
    if exe:
        return exe
    for path in GH_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


def run(args, cwd=ROOT, check=False, capture=True):
    p = subprocess.run(args, cwd=cwd, text=True, encoding="utf-8", errors="replace",
                       stdout=subprocess.PIPE if capture else None,
                       stderr=subprocess.STDOUT if capture else None)
    if check and p.returncode != 0:
        raise SystemExit("command failed: %s\n%s" % (" ".join(args), (p.stdout or "").strip()))
    return p


def git(*args, check=False):
    return run(["git"] + list(args), check=check)


def has_git():
    return os.path.isdir(os.path.join(ROOT, ".git"))


def has_commits():
    return git("rev-parse", "--verify", "HEAD").returncode == 0


def main():
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass

    argv = [a for a in sys.argv[1:]]
    local_only = "--local-only" in argv
    private = "--private" in argv
    name = next((a for a in argv if not a.startswith("-")), os.path.basename(ROOT))

    if shutil.which("git") is None:
        raise SystemExit("git not found. Install Git first: https://git-scm.com/download/win")

    gh = None if local_only else find_gh()
    if not local_only and not gh:
        raise SystemExit("GitHub CLI (gh) not found. Install it: https://cli.github.com "
                         "or use --local-only and push manually.")

    login = None
    if not local_only:
        who = run([gh, "auth", "status"])
        if who.returncode != 0:
            print(who.stdout.strip())
            raise SystemExit("\nNot logged in. Run this once in your terminal (10 seconds):\n"
                             "    gh auth login --web --clipboard\n"
                             "The one-time code is copied to your clipboard - just paste it in\n"
                             "the browser page that opens and click Authorize.\n"
                             "Then run this script again.")
        run([gh, "auth", "setup-git"])      # let git push over https use gh's credentials
        who = run([gh, "api", "user", "--jq", ".login"])
        login = who.stdout.strip() if who.returncode == 0 else None
        if not login:
            raise SystemExit("Could not read your GitHub account (network?).")

    # ---- git init ----
    if not has_git():
        git("init", check=True)
        print("initialized empty git repository")
    git("branch", "-M", "main")

    # ---- commit identity: only set a repo-local fallback when none is configured ----
    if not git("config", "user.email").stdout.strip() or not git("config", "user.name").stdout.strip():
        if login:
            git("config", "user.name", login)
            git("config", "user.email", "%s@users.noreply.github.com" % login)
            print("set repo-local identity to %s <%s@users.noreply.github.com> "
                  "(override with `git config user.name/user.email` if you prefer)" % (login, login))
        else:
            raise SystemExit("git user.name / user.email are not configured. Run:\n"
                             "    git config --global user.name \"Your Name\"\n"
                             "    git config --global user.email \"you@example.com\"")

    # ---- commit ----
    git("add", "-A")
    staged = bool(git("diff", "--cached", "--name-only").stdout.strip())
    if staged:
        msg = "Initial commit" if not has_commits() else "Update shake-cursor"
        git("commit", "-m", msg, check=True)
        print("committed: " + msg)
    elif not has_commits():
        raise SystemExit("nothing to commit")
    else:
        print("nothing new to commit")

    if local_only:
        print("\nlocal repository ready at " + ROOT)
        print("push it yourself with: git remote add origin <url> && git push -u origin main")
        return 0

    # ---- remote / push ----
    remotes = git("remote").stdout.split()
    if "origin" not in remotes:
        flags = ["--private"] if private else ["--public"]
        created = run([gh, "repo", "create", name, "--source", ".", "--remote", "origin",
                       "--push"] + flags + ["--description",
                       "macOS-style shake-to-find-cursor for Windows. Zero dependencies."])
        if created.returncode != 0:
            print(created.stdout.strip())
            print("\nrepo creation failed - assuming it already exists, trying to attach it")
            url = "https://github.com/%s/%s.git" % (login, name)
            git("remote", "add", "origin", url)
            git("push", "-u", "origin", "main", check=False)
    else:
        git("push", "-u", "origin", "main", check=False)

    url = "https://github.com/%s/%s" % (login, name)
    print("\ndone -> " + url)
    print("remember to fill in the repository description and topics (python, windows, cursor, accessibility)")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
