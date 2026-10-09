# Moldova refugee response: coordination (right pane)

Static page for the right pane of the UNHCR ODP Moldova page. No build step and no data files.
Settings → Pages → deploy from `main`, root folder, then embed the page URL by iframe.

What to edit, all in `index.html`:
- Help links: the two `<a id="help-ukr">` / `<a id="help-en">` buttons.
- Calendar: the `src` of `<iframe id="cal">` (Google Slides "Publish to web" link, `/embed` form) and the full-screen link below it.
- Coordination structure: the `structure` and `separate` lists in the script (working-group id and name).
- Logos: `assets/unhcr-help.svg` (white artwork, shown on the blue banner) and `assets/rrp-govt.jpg`.
