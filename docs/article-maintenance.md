# Release article maintenance

The owner requires the illustrated README and the same article in PDF to remain
current at every release push. README.md is the single text source, English first
and Russian second. Both languages share actual English UI captures in
docs/images/readme. docs/DALE-guide.pdf is tracked in Git and linked from README.
This supersedes the earlier policy of keeping the README PDF preview local only.

The PDF starts with a linked bilingual contents page and provides chapter bookmarks
and footer links to contents and both languages. Keep the new DA topics at the end
of each language. Describe user actions and results, without implementation details
such as database technology. Show complexity using the same palm at maximum detail
and a simplified value, with identical camera and slice settings. Thinning comparisons
must have clearly visible native contour outlines and identical camera settings.

1. Review functionality since the previous release and update both README sections.
   Correct removed behavior as well as adding new functions. Keep source maps private.
2. Capture current application states in an isolated process with temporary settings.
   Never save over example projects or alter an owner's running window. Review every
   referenced screenshot; replace outdated controls and translate presentation labels
   only in the unsaved capture copy. Use the same screenshots for both languages.
3. Complete the runtime build before final PDF generation so its footer uses the
   exact release version. Install documentation dependencies from
   tools/article-requirements.txt in an isolated target or environment. The desktop
   application does not require them. Arial on Windows or DejaVu Sans on Linux supplies
   embedded Cyrillic fonts.
4. Run `.venv/Scripts/python.exe tools/build_article.py --deps artifacts/article-deps
   --screenshots-reviewed`. The review flag records a deliberate check of screenshots
   against the current application source; it is not a substitute for visual review.
   The renderer reads README directly, expands all sections and creates the PDF and
   docs/article-build.json. Do not hand-edit its recorded hashes.
5. Render every PDF page with Poppler or PyMuPDF and inspect text, images, captions,
   page breaks and footers. Check internal link destinations and extracted text in both languages. Keep page PNGs,
   temporary dependency folders and diagnostic reports in ignored artifacts.
6. Run `.venv/Scripts/python.exe tools/build_article.py --check`, repository checks and
   relevant tests. Commit README, screenshots, PDF and manifest with intended changes.
   The release helper repeats the version/hash check when planning and validating
   the push. Development does not silently publish a release.
7. Prepare the exact release plan and request its separate owner confirmation using
   skills/dale-push/SKILL.md. Documentation maintenance never authorizes a push,
   force update, tag, GitHub Release creation or deletion of remote assets.

The check uses only Python's standard library, so release validation and CI need no
PDF renderer or installed game. It detects changed article text, image bytes, renderer,
application source, application version and PDF bytes. Human/agent inspection remains
necessary to judge whether the screenshots and explanations are correct.
