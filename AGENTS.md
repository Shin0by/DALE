# Agent entry point

## Working agreement
- Communicate with the owner in Russian. Write code, identifiers, comments, technical documentation, commit messages, and application text in English. The README introduction is English first, then Russian.
- The owner directs development through chat. Maintain the repository for efficient agent navigation; do not require the owner to curate documentation or operate developer tools.
- Read `project/index.json`, then `project/state.json`. Read only the task-relevant documents and modules listed there. Use `rg` for targeted discovery; exclude generated artifacts and private examples.
- Keep requirements traceable by stable `FR-*` / `NFR-*` IDs. Update state and relevant documentation with each substantive behavior change. State facts, assumptions, validation evidence, and remaining work separately.
- Do not spawn other agents unless the owner explicitly requests delegation.

## Product invariants
- DALE is a local desktop image editor for Dungeon Alchemist exports used in Foundry VTT.
- Source input is a JPG/JPEG plus Foundry scene JSON. Export is an RGBA PNG with exactly the original image dimensions and origin.
- Never overwrite imported JPG/JSON or write temporary closure lines into Foundry JSON. Closures and brushes belong to DALE editing sessions only.
- Store geometry and brush coordinates in original image pixels. Preview resolution must never limit export resolution.
- Keep geometry, import validation, and raster/export logic independent of Qt. Validate them with meaningful tests.
- Do not claim semantic terrain recognition, real Dungeon Alchemist compatibility, or a Foundry integration test without evidence.
- User-supplied files in `examples/` are local, untrusted, and untracked by default. Never upload or commit them without explicit authorization.

## Commands (PowerShell)
```powershell
.\.venv\Scripts\python.exe -m dale
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe tools/check_repository.py
```

If Git reports ownership mismatch, use the command-scoped option `git -c safe.directory=C:/Programming/GitHub/DALE ...`. Do not change global Git settings to resolve it.
