---
name: dale-push
description: Push the DALE repository only on a fresh explicit owner request, defaulting to development. Require separate confirmation of the exact commit before pushing release. Also apply when configuring or reviewing DALE push rules.
---

# DALE push

Use this workflow for DALE Git pushes. Read the current repository's `AGENTS.md` first. Chat is Russian; technical text and commits are English.

## Authorization and destination

- A fresh explicit owner request to push is required for each attempt. Coding, building, committing, configuring this skill, previous push requests, and standing permission never authorize a new push. Do not schedule or automate pushes.
- Default destination is `origin/development`, including a request that just says "push". Only an explicit request naming `release` selects `origin/release`. Refuse other destinations until the owner changes this policy.
- A release request is not its own confirmation. Prepare a concrete plan first, show the exact commit, destination and change summary, then ask separately in Russian. Cite this skill and the owner's separate-confirmation rule. Wait for an affirmative answer; cancellation, silence or an ambiguous answer does not authorize release.
- Confirmation applies only to the displayed plan. A changed commit, destination or remote tip requires a new plan and, for release, new confirmation.

## Release confirmation interface

Use `functions.request_user_input_async` for the separate release confirmation,
with exactly two suggested choices: `Подтверждаю пуш в release` and
`Не подтверждаю`. Include the pinned full commit, target branch, change summary
and any accompanying publication/cleanup actions in the question so the submitted
answer applies to one concrete plan. Display the archive identity/checksum when
publishing a portable release. Cite this skill's separate-confirmation rule.

Wait for the submitted answer before recording confirmation or pushing. A
preselected choice, elapsed time or the tool's immediate return is not approval.
`Не подтверждаю`, cancellation, silence and ambiguous text never authorize a push;
do not pass a negative answer to `confirm-release`. Preserve support for an
unambiguous affirmative free-text reply to the displayed question. If the choice
tool is unavailable, ask the same explicit two-choice question in chat. Do not
treat updating this skill as confirmation; after a changed plan ask again.

## Workflow

Before every release plan, update the bilingual README for the current functionality,
review or replace its actual English UI screenshots, and rebuild `docs/DALE-guide.pdf`
from the same article with `tools/build_article.py`. Follow `docs/article-maintenance.md`;
inspect all rendered pages. Commit the article, images, PDF and fingerprint manifest
with the release. The helper checks their version and hashes during release planning
and again before pushing; missing/stale documentation blocks release. This does not
authorize an additional push, a new build or any remote cleanup by itself.

Canonical implementation: `skills/dale-push/scripts/push.py` in the checkout. Use the repository copy so versioned policy and hook agree. The installed copy is available for discovery; do not run a stale installed helper against newer repository rules.

1. Inspect status, current branch, origin, ignored/private files, commits and relevant checks. Finish authorized work, validate it, rebuild the portable package if needed, and commit intended changes locally. Track the owner-approved complete DALE runtime; keep UserData, cache, private examples/projects, release ZIPs and other generated evidence ignored. A clean working tree is required. Never expose credentials.
2. If the local guard is not configured, run `python skills/dale-push/scripts/push.py configure`. It changes only this repository's Git configuration and refuses existing custom hooks. This command never pushes. Use `.venv/Scripts/python.exe` on Windows.
3. Fetch origin if needed to inspect its current history. Prepare the request with `python skills/dale-push/scripts/push.py plan --request "<current owner request>"`. Add `--target release` only when explicitly requested. Review the printed plan ID, full HEAD, target, remote tip and commit summary. Planning only reads the remote; no branches are created there.
4. For release, present that concrete result and ask through the Release confirmation interface above. After the owner's submitted affirmative reply, record it with `python skills/dale-push/scripts/push.py confirm-release --plan <id> --answer "<owner's affirmative reply>"`. Never invent this answer or call this step before the reply arrives.
5. Run `python skills/dale-push/scripts/push.py push --plan <id>`. The helper performs one normal push of the pinned commit to the pinned branch through the local pre-push guard. Development needs no second confirmation.
6. Report destination, commit and result in Russian. On an attempted push failure, stop and report the error; no automatic retry, force push, hook bypass, remote replacement or protection changes. A new attempt needs a fresh owner request. Read-only diagnosis may continue. Observe CI only after a successful authorized push; CI failures do not authorize another push.

Plans expire after one hour and are single-attempt. The guard rejects unplanned direct pushes, other refs, deletions and stale plans. Do not use `--no-verify`, `--force`, `--mirror`, `--all`, tag pushes, or disable/change hooks to bypass this workflow. Never change global Git configuration. For ownership mismatches use command-scoped `-c safe.directory=<checkout>`.
