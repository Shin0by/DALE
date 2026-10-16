"""Exercise the actual helper and Git hook against isolated, local bare remotes."""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = "skills/dale-push/scripts/push.py"


class Checkout:
    def __init__(self, root, remote):
        self.root = root
        self.remote = remote
        self.env = {
            **os.environ,
            "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
        }

    def git(self, *args, check=True):
        result = subprocess.run(
            ["git", "-c", f"safe.directory={self.root.as_posix()}", "-C", str(self.root), *args],
            env=self.env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if check:
            assert result.returncode == 0, result.stderr
        return result

    def helper(self, *args, check=True):
        result = subprocess.run(
            [sys.executable, str(self.root / HELPER), "--repo", str(self.root), *args],
            env=self.env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if check:
            assert result.returncode == 0, result.stderr
            return json.loads(result.stdout)
        assert result.returncode != 0, result.stdout
        return result.stderr

    def tip(self, target):
        result = self.git("ls-remote", "--refs", "origin", f"refs/heads/{target}").stdout
        return result.split()[0] if result else None

    def commit(self):
        with (self.root / "content.txt").open("a") as stream:
            stream.write("new change\n")
        self.git("add", "content.txt")
        self.git("commit", "-m", "Change content")
        return self.git("rev-parse", "HEAD").stdout.strip()

    def plan(self, target="development"):
        return self.helper("plan", "--request", "Push this change", "--target", target)["id"]


@pytest.fixture
def checkout(tmp_path):
    remote = tmp_path / "private remote.git"
    root = tmp_path / "DALE checkout"
    root.mkdir()
    instance = Checkout(root, remote)
    instance.git("init", "--bare", str(remote))
    instance.git("init", "-b", "main")
    instance.git("config", "user.name", "DALE test")
    instance.git("config", "user.email", "dale-test@example.invalid")
    instance.git("config", "commit.gpgsign", "false")
    shutil.copytree(ROOT / "skills/dale-push", root / "skills/dale-push")
    shutil.copytree(ROOT / ".githooks", root / ".githooks")
    (root / ".githooks/pre-push").chmod(0o755)
    (root / ".gitattributes").write_text("* text eol=lf\n")
    instance.git("add", ".")
    instance.git("commit", "-m", "Initialize isolated push fixture")
    instance.git("remote", "add", "origin", str(remote))
    instance.helper("configure")
    return instance


def test_default_plan_is_read_only_and_push_is_single_attempt(checkout):
    plan = checkout.helper("plan", "--request", "Push")
    assert plan["target"] == "development"
    assert checkout.tip("development") is None
    result = checkout.helper("push", "--plan", plan["id"])
    assert result["head"] == checkout.tip("development")
    assert result["target"] == "origin/development"
    assert checkout.tip("main") is None
    assert checkout.tip("release") is None
    assert "already attempted" in checkout.helper("push", "--plan", plan["id"], check=False)
    assert not (checkout.root / ".git/dale-push/active.json").exists()


@pytest.mark.parametrize(
    "arguments",
    [(), ("origin", "HEAD:main"), ("origin", "HEAD:release"), ("origin", "HEAD:development")],
)
def test_direct_pushes_are_blocked(checkout, arguments):
    result = checkout.git("push", *arguments, check=False)
    assert result.returncode != 0
    assert "DALE push blocked" in result.stderr
    assert checkout.tip("main") is None
    assert checkout.tip("development") is None
    assert checkout.tip("release") is None


def test_release_requires_separate_confirmation_of_the_plan(checkout):
    plan_id = checkout.plan("release")
    assert "separate confirmation" in checkout.helper("push", "--plan", plan_id, check=False)
    assert checkout.tip("release") is None
    assert "affirmative reply" in checkout.helper(
        "confirm-release", "--plan", plan_id, "--answer", "", check=False
    )
    confirmation = checkout.helper(
        "confirm-release", "--plan", plan_id, "--answer", "Yes, confirm this release commit"
    )
    assert confirmation["pushed"] is False
    assert checkout.tip("release") is None
    result = checkout.helper("push", "--plan", plan_id)
    assert checkout.tip("release") == result["head"]
    assert checkout.tip("development") is None


def test_changed_head_invalidates_release_confirmation(checkout):
    plan_id = checkout.plan("release")
    checkout.helper("confirm-release", "--plan", plan_id, "--answer", "Yes")
    checkout.commit()
    assert "HEAD or origin changed" in checkout.helper("push", "--plan", plan_id, check=False)
    assert checkout.tip("release") is None


def test_changed_remote_tip_invalidates_an_older_plan(checkout):
    old = checkout.plan()
    new = checkout.plan()
    checkout.helper("push", "--plan", new)
    assert "Remote target changed" in checkout.helper("push", "--plan", old, check=False)


def test_changed_origin_invalidates_the_plan(checkout):
    plan_id = checkout.plan()
    checkout.git("remote", "set-url", "--push", "origin", str(checkout.remote.parent / "other.git"))
    assert "HEAD or origin changed" in checkout.helper("push", "--plan", plan_id, check=False)
    assert checkout.tip("development") is None


@pytest.mark.parametrize(
    "refspec",
    ["HEAD:refs/tags/probe", "HEAD:release", "HEAD:main", ":development"],
)
def test_permit_cannot_authorize_other_refs_or_deletion(checkout, refspec):
    checkout.helper("push", "--plan", checkout.plan())
    old = checkout.tip("development")
    checkout.commit()
    plan_id = checkout.plan()
    directory = checkout.root / ".git/dale-push"
    path = directory / f"{plan_id}.json"
    plan = json.loads(path.read_text())
    plan["attempted"] = True
    path.write_text(json.dumps(plan))
    token = "isolated-test-permit"
    (directory / "active.json").write_text(
        json.dumps({"token": token, "plan": plan_id, "expires": time.time() + 60})
    )
    checkout.env["DALE_PUSH_PERMIT"] = token
    result = checkout.git("push", "origin", refspec, check=False)
    assert result.returncode != 0
    assert "Ref update does not match" in result.stderr
    assert checkout.tip("development") == old
    assert checkout.tip("release") is None
    assert checkout.tip("main") is None
    assert not checkout.git("ls-remote", "origin", "refs/tags/probe").stdout


def test_no_request_dirty_checkout_other_targets_and_expiry_are_rejected(checkout):
    assert "owner push request" in checkout.helper("plan", "--request", " ", check=False)
    assert "invalid choice" in checkout.helper(
        "plan", "--request", "Push", "--target", "main", check=False
    )
    plan_id = checkout.plan()
    path = checkout.root / ".git/dale-push" / f"{plan_id}.json"
    plan = json.loads(path.read_text())
    plan["expires"] = time.time() - 1
    path.write_text(json.dumps(plan))
    assert "expired" in checkout.helper("push", "--plan", plan_id, check=False)
    (checkout.root / "uncommitted.txt").write_text("unfinished")
    assert "clean working tree" in checkout.helper("plan", "--request", "Push", check=False)


def test_successful_update_and_up_to_date_attempt_use_the_guard(checkout):
    checkout.helper("push", "--plan", checkout.plan())
    new_head = checkout.commit()
    checkout.helper("push", "--plan", checkout.plan())
    assert checkout.tip("development") == new_head
    checkout.helper("push", "--plan", checkout.plan())
    assert not (checkout.root / ".git/dale-push/active.json").exists()


def test_failed_remote_push_consumes_request_without_retry(checkout):
    reject = checkout.remote / "hooks/pre-receive"
    reject.write_text("#!/bin/sh\nexit 1\n")
    reject.chmod(0o755)
    plan_id = checkout.plan()
    assert "request consumed" in checkout.helper("push", "--plan", plan_id, check=False)
    assert "already attempted" in checkout.helper("push", "--plan", plan_id, check=False)
    assert checkout.tip("development") is None


def test_reconfiguration_preserves_existing_custom_hooks(checkout):
    checkout.git("config", "core.hooksPath", "owner-hooks")
    assert "Existing custom hooksPath" in checkout.helper("configure", check=False)
    assert checkout.git("config", "core.hooksPath").stdout.strip() == "owner-hooks"
    assert "Configure the local" in checkout.helper("plan", "--request", "Push", check=False)
