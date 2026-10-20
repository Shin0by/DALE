# Application icon

The owner supplied `shin0by.png` and the ready-made `favicon.ico` on 2026-10-16 for the window and Windows executable icon. Preserve both files byte for byte. Use `favicon.ico` directly for Qt and Windows packaging.

- `favicon.ico`: 16 x 16, 32 x 32, and 48 x 48 images; SHA-256 `5cbe7ced26b590c27a6ecb2ac459766bda0326baed2e4ad35ab85006c7b50ea1`.
- `shin0by.png`: original 256 x 256 RGBA artwork reference; SHA-256 `16483efa485a007c86a1fc6cffc872a48e190223cce05d59ae6e31f2df416446`.
- Qt loads the ICO relative to the application module, independent of the current working directory.
- PyInstaller embeds the supplied ICO directly in `DALE.exe`; it must not regenerate or redraw it from the PNG.
- Include both formats in Python package data, the standalone bundle, and portable source fingerprints.
