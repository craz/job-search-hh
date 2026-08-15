# Development agent instructions

1. HH owns HH API, Chromium/Playwright, session state and apply safety controls.
2. It never reads Core PostgreSQL or imports Core source; use versioned contracts.
3. Real applications, messages and other HH writes require explicit authorization.
4. Browser/profile operations require single-process locking and persistent volumes.
5. CAPTCHA, expired auth and uncertain post-submit state stop automation safely.
6. Define User Story and executable Gherkin before user-facing behavior.
7. Keep code documentation factual about external effects and safety invariants.
8. Run applicable gates; never download browsers/images merely to bypass an
   environmental problem without user agreement.
9. Commit only a completed green step and never push without a request.

