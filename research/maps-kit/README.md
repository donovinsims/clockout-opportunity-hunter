# Google Maps Scraper Kit review

Source reviewed: https://github.com/Mahanaicoach/google-maps-scraper-kit

Upstream files were reviewed at commit `01e270f79f76e7d157994ae8f04da1ee8fe60652`.
This folder contains analysis only; the upstream repository was not cloned, installed,
or modified. No kit dependency was added to Opportunity Hunter.

The kit's useful design is its Chrome DevTools Protocol capture of Maps network data.
Its `details.py` parser documents the `review_count` entity field and the browser code
rewrites a `HeadlessChrome/` user agent to `Chrome/` because Maps can otherwise return a
limited view without review counts. That behavior was tested in an isolated Playwright
harness using the already-installed Chrome binary. It is an adaptation, not execution of
the kit itself.

MIT attribution remains with Mahan / Mahanaicoach. See the upstream `LICENSE` and
`CREDITS.md` before copying source code in a future change.
