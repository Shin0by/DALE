# Windows product discovery

FR-163 / ADR-101 registers the last normally launched packaged Windows copy. The
registry is a discovery index, not an installation record or a settings store.

## Product metadata

The application first writes `HKEY_CURRENT_USER\Software\Shin0by\DALE`, then
attempts the same values under `HKEY_LOCAL_MACHINE\Software\Shin0by\DALE` with
the existing process token. Each key write is independent and best effort.

| Value | Type | Meaning |
| --- | --- | --- |
| DisplayName | REG_SZ | Dungeon Alchemist Levels Export |
| DisplayVersion | REG_SZ | Current application version, for example1.03.085 |
| Publisher | REG_SZ | Shin0by, the author and publisher |
| RepositoryUrl | REG_SZ | https://github.com/Shin0by/DALE |
| ExecutablePath | REG_SZ | Absolute path of the actual launched EXE |
| ProductId | REG_SZ | Stable Shin0by.DALE identifier |
| LastRunTimeUtc | REG_SZ | UTC launch time in ISO8601, ending in Z |
| RegistrySchemaVersion | REG_DWORD | 1, independent of project schema7 |

Use the64-bit registry view explicitly through `KEY_WOW64_64KEY`; never construct
a Wow6432Node path manually. Request only `KEY_SET_VALUE` on the created/opened
key. Windows checks the existing ACL. Do not request administrative elevation,
change permissions or take ownership. Access and availability failures do not
prevent the editor from starting. Existing unrelated values/subkeys are retained.

The last launch wins, including launching an older version or a moved portable
copy. A future product-discovery reader should prefer HKCU, check that the recorded
EXE still exists, and treat HKLM as a possibly stale fallback. This feature does
not provide installation enumeration or automatic removal of stale entries.

## App Paths

Also set the default REG_SZ value of
`Software\Microsoft\Windows\CurrentVersion\App Paths\DALE.exe` to the same absolute
EXE path, first in HKCU and then best effort in HKLM. Windows Shell can resolve
DALE.exe through App Paths. No optional Path value is added; process/system PATH,
file associations, Uninstall and Installed Apps entries are unchanged.

## Launch scope and portability

Registration runs after the editor window is created during an ordinary packaged
Windows launch. Python/development launches, tests and `--smoke-report` launches
skip it before importing the registry API. The executable path comes from
`sys.executable`, never the current directory, source checkout or Python runtime.
Both hives receive the same version, timestamp and path snapshot.

UserData remains beside the portable EXE. Project format7, settings ownership,
source assets and editing history are unchanged. No registry read is required for
opening the application. Registry entries survive moving or deleting a portable
folder until another normal launch replaces them.

Unit tests use an in-memory registry double, including access denials and partial
write errors. Portable smoke verification must leave discovery keys untouched;
an explicitly authorized normal launch validates actual registration separately.

## References

- [Microsoft App Registration](https://learn.microsoft.com/en-us/windows/win32/shell/app-registration)
- [Microsoft registry key security and access rights](https://learn.microsoft.com/en-us/windows/win32/sysinfo/registry-key-security-and-access-rights)
- [Microsoft alternate registry views](https://learn.microsoft.com/en-us/windows/win32/winprog64/accessing-an-alternate-registry-view)
- [Python winreg API](https://docs.python.org/3/library/winreg.html)
