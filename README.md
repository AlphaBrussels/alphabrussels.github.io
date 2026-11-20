# Alpha Brussels website

The public website of Alpha Brussels, the student finance and economics club in Brussels: https://alphabrussels.github.io

- `index.html` is the whole site (Home, About, Events, Newsletter, Join). Issues are read in the Newsletter tab.
- `privacy.html` and `legal.html` are the privacy and cookie policy and the legal notice with the investment disclaimer.
- `issues/` holds the weekly newsletter. `issues.json` lists the issues; the site opens the newest and lists every issue under "Past issues". Direct visits to an issue page are sent to the Newsletter tab.
- `tools/build_issue.py` checks prices and citations and builds each issue and its email version; `tools/render_images.py` draws the email picture.
- `assets/fonts/` holds the self-hosted fonts (SIL Open Font License), so no visitor data goes to Google.
- TradingView prices and the Substack sign-up box load only after the visitor allows them.

Issues are prepared as drafts each Saturday and are only added here after the club approves them.
