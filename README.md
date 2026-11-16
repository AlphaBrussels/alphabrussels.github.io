# Alpha Brussels website

The public website of Alpha Brussels, the student finance and economics club in Brussels.

- `index.html` is the whole site (home, events, newsletter, about, join).
- `issues/` holds the weekly newsletter. `issues.json` lists the issues; the site shows the newest and files the rest under "Past issues".
- `events.json` lists events.
- `tools/build_issue.py` checks prices and citations and builds each issue. `tools/make_host_page.py` turns the preview page into this site's `index.html`.

Issues are prepared as drafts each Saturday and are only added here after the club approves them.
