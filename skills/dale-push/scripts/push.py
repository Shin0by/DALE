"""Single-attempt DALE push plans and a local pre-push guard; standard library only."""

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

TARGETS = ("development", "release")
PLAN_SECONDS = 3600
PERMIT_ENV = "DALE_PUSH_PERMIT"
HOOK_PATH = ".githooks"


class PolicyError(Exception):
    """An explicit owner request or its concrete push plan is missing/stale."""


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PolicyError("Push authorization is missing or unreadable.") from exc


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


class Repository:
    def __init__(self, root):
        self.root = Path(root).resolve()
        actual = self.git("rev-parse", "--show-toplevel").stdout.strip()
        if Path(actual).resolve() != self.root:
            raise PolicyError("Run from the checkout root or supply --repo <root>.")
        self.state = Path(self.git("rev-parse", "--absolute-git-dir").stdout.strip()) / "dale-push"

    def git(self, *args, check=True, **kwargs):
        result = subprocess.run(
            ["git", "-c", f"safe.directory={self.root.as_posix()}", "-C", str(self.root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            **kwargs,
        )
        if check and result.returncode:
            # Git authentication errors may include credentials; do not echo remote output.
            raise PolicyError(f"Git {args[0]} failed (exit {result.returncode}).")
        return result

    def config(self, key):
        return self.git("config", "--local", "--get-all", key, check=False).stdout.strip()

    def configure(self):
        if self.config("core.hooksPath") not in ("", HOOK_PATH):
            raise PolicyError("Existing custom hooksPath requires review; nothing changed.")
        default_hook = self.state.parent / "hooks/pre-push"
        if default_hook.exists():
            raise PolicyError("Existing pre-push hook requires review; nothing changed.")
        if not (self.root / HOOK_PATH / "pre-push").is_file():
            raise PolicyError("The versioned DALE pre-push hook is missing.")
        settings = {
            "core.hooksPath": HOOK_PATH,
            "push.default": "nothing",
            "push.autoSetupRemote": "false",
            "remote.pushDefault": "origin",
            "remote.origin.push": "HEAD:refs/heads/development",
            "branch.development.pushRemote": "origin",
        }
        for key, value in settings.items():
            self.git("config", "--local", "--replace-all", key, value)
        return {"configured": True, "default_target": "origin/development", "pushed": False}

    def ensure_configured(self):
        if (
            self.config("core.hooksPath") != HOOK_PATH
            or self.config("remote.origin.push") != "HEAD:refs/heads/development"
            or self.config("push.default") != "nothing"
        ):
            raise PolicyError("Configure the local DALE push guard first.")
        if not (self.root / HOOK_PATH / "pre-push").is_file():
            raise PolicyError("The local push guard is missing.")

    def clean_head(self):
        if self.git("status", "--porcelain").stdout:
            raise PolicyError("Commit intended changes and leave a clean working tree first.")
        return self.git("rev-parse", "HEAD").stdout.strip()

    def remote_url(self):
        urls = self.git("remote", "get-url", "--push", "--all", "origin").stdout.splitlines()
        if len(urls) != 1:
            raise PolicyError("Exactly one origin push URL is required.")
        url = urls[0]
        parsed = urlsplit(url)
        if parsed.scheme in ("http", "https") and (
            parsed.username or parsed.password or parsed.query or parsed.fragment
        ):
            raise PolicyError("Use the credential manager; remove credentials from the origin URL.")
        return url

    def remote_head(self, url, target):
        lines = self.git("ls-remote", "--refs", "--", url, f"refs/heads/{target}").stdout
        return lines.split()[0] if lines.strip() else None

    def plan_path(self, plan_id):
        if not re.fullmatch(r"[0-9a-f]{32}", plan_id):
            raise PolicyError("Invalid plan ID.")
        return self.state / f"{plan_id}.json"

    def plan(self, request, target):
        if not request.strip():
            raise PolicyError("A fresh explicit owner push request is required.")
        self.ensure_configured()
        head = self.clean_head()
        url = self.remote_url()
        old = self.remote_head(url, target)
        if old and self.git("merge-base", "--is-ancestor", old, head, check=False).returncode:
            raise PolicyError(
                "Fetch and review origin history; target must be an ancestor of HEAD."
            )
        revision_range = f"{old}..{head}" if old else head
        plan = {
            "id": secrets.token_hex(16),
            "repo": str(self.root),
            "request": request.strip(),
            "target": target,
            "head": head,
            "remote_url": url,
            "remote_head": old,
            "expires": time.time() + PLAN_SECONDS,
            "attempted": False,
            "release_confirmation": None,
            "commit_count": int(self.git("rev-list", "--count", revision_range).stdout),
            "commits": self.git("log", "--oneline", "-20", revision_range).stdout.splitlines(),
        }
        self.state.mkdir(parents=True, exist_ok=True)
        write_json(self.plan_path(plan["id"]), plan)
        return self.public_plan(plan)

    @staticmethod
    def public_plan(plan):
        return {
            key: plan[key]
            for key in ("id", "target", "head", "remote_head", "commit_count", "commits")
        }

    def validate(self, plan_id):
        self.ensure_configured()
        plan = read_json(self.plan_path(plan_id))
        if (
            plan.get("id") != plan_id
            or plan.get("repo") != str(self.root)
            or plan.get("target") not in TARGETS
            or plan.get("attempted")
            or plan.get("expires", 0) < time.time()
        ):
            raise PolicyError("Plan is expired, already attempted or belongs to another checkout.")
        if self.clean_head() != plan["head"] or self.remote_url() != plan["remote_url"]:
            raise PolicyError("HEAD or origin changed; prepare a new plan.")
        if self.remote_head(plan["remote_url"], plan["target"]) != plan["remote_head"]:
            raise PolicyError("Remote target changed; prepare a new plan.")
        return plan

    def confirm_release(self, plan_id, answer):
        if not answer.strip():
            raise PolicyError(
                "Record the owner's separate affirmative reply, never an empty answer."
            )
        plan = self.validate(plan_id)
        if plan["target"] != "release":
            raise PolicyError("Development needs no separate release confirmation.")
        plan["release_confirmation"] = answer.strip()
        write_json(self.plan_path(plan_id), plan)
        return {"confirmed_release": plan["head"], "pushed": False}

    def push(self, plan_id):
        plan = self.validate(plan_id)
        if plan["target"] == "release" and not plan["release_confirmation"]:
            raise PolicyError("Release requires the owner's separate confirmation of this plan.")
        permit = self.state / "active.json"
        token = secrets.token_hex(32)
        try:
            with permit.open("x", encoding="utf-8") as stream:
                json.dump({"token": token, "plan": plan_id, "expires": time.time() + 60}, stream)
        except FileExistsError as exc:
            raise PolicyError("An active/stale push permit needs review; no push started.") from exc
        try:
            plan["attempted"] = True
            write_json(self.plan_path(plan_id), plan)
            result = self.git(
                "push",
                "origin",
                f"{plan['head']}:refs/heads/{plan['target']}",
                check=False,
                env={**os.environ, PERMIT_ENV: token},
            )
            if result.returncode:
                raise PolicyError(
                    f"Push failed (exit {result.returncode}); request consumed. "
                    "Stop; a new attempt requires a fresh owner request."
                )
            receipt = read_json(permit)
            if receipt.get("token") != token or not receipt.get("consumed"):
                raise PolicyError(
                    "Push returned without consuming the guard permit; inspect hooks."
                )
            return {"pushed": True, "target": f"origin/{plan['target']}", "head": plan["head"]}
        finally:
            permit.unlink(missing_ok=True)

    def hook(self, remote, url, updates):
        self.ensure_configured()
        permit_path = self.state / "active.json"
        permit = read_json(permit_path)
        if (
            not os.environ.get(PERMIT_ENV)
            or permit.get("token") != os.environ[PERMIT_ENV]
            or permit.get("expires", 0) < time.time()
            or permit.get("consumed")
        ):
            raise PolicyError(
                "Direct push blocked; use the dale-push skill on an explicit request."
            )
        plan = read_json(self.plan_path(permit["plan"]))
        if (
            remote != "origin"
            or url != plan["remote_url"]
            or str(self.root) != plan["repo"]
            or plan["target"] not in TARGETS
            or not plan["attempted"]
            or plan["expires"] < time.time()
            or (plan["target"] == "release" and not plan["release_confirmation"])
            or self.clean_head() != plan["head"]
        ):
            raise PolicyError("Push does not match the authorized plan.")
        lines = updates.splitlines()
        if len(lines) > 1 or (not lines and plan["remote_head"] != plan["head"]):
            raise PolicyError("Only the single planned branch may be pushed.")
        for line in lines:
            fields = line.split()
            if (
                len(fields) != 4
                or fields[1] != plan["head"]
                or fields[2] != f"refs/heads/{plan['target']}"
                or fields[3] != (plan["remote_head"] or "0" * len(plan["head"]))
            ):
                raise PolicyError("Ref update does not match the authorized commit/target/tip.")
        # Keep the lock until Git exits, including the remote receive phase.
        permit["consumed"] = True
        write_json(permit_path, permit)
        return {"allowed": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("configure")
    plan_parser = commands.add_parser("plan")
    plan_parser.add_argument("--request", required=True)
    plan_parser.add_argument("--target", choices=TARGETS, default="development")
    confirm = commands.add_parser("confirm-release")
    confirm.add_argument("--plan", required=True)
    confirm.add_argument("--answer", required=True)
    push_parser = commands.add_parser("push")
    push_parser.add_argument("--plan", required=True)
    hook_parser = commands.add_parser("hook")
    hook_parser.add_argument("remote")
    hook_parser.add_argument("url")
    args = parser.parse_args()
    try:
        repo = Repository(args.repo)
        if args.command == "configure":
            result = repo.configure()
        elif args.command == "plan":
            result = repo.plan(args.request, args.target)
        elif args.command == "confirm-release":
            result = repo.confirm_release(args.plan, args.answer)
        elif args.command == "push":
            result = repo.push(args.plan)
        else:
            result = repo.hook(args.remote, args.url, sys.stdin.read())
        if args.command != "hook":
            print(json.dumps(result, indent=2))
        return 0
    except (PolicyError, OSError) as exc:
        print(f"DALE push blocked: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
