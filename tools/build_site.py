"""Assemble the static Pages build of the Flask app.

Renders templates/index.html once through Flask, copies the real CSS and JS,
and injects the browser-side model in front of static/js/app.js. app.js and
charts.js are copied verbatim - bridge.js answers the /api calls they make.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SECRET_KEY", "static-build")

OUT = ROOT / "site"

INJECT = """
<!-- MCWP in the browser: the model, the engine, and the /api shim -->
<script src="model.js"></script>
<script src="predict.js"></script>
<script src="engine.js"></script>
<script src="bridge.js"></script>
"""


def main() -> None:
    from app import app

    OUT.mkdir(parents=True, exist_ok=True)
    html = app.test_client().get("/").get_data(as_text=True)

    # real assets, copied as-is
    for sub in ("css", "js"):
        dest = OUT / "static" / sub
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(ROOT / "static" / sub, dest)

    # Flask's absolute /static/... becomes relative, so the page works from
    # the /mcwp/app/ subpath Pages serves it on.
    html = html.replace('href="/static/', 'href="static/')
    html = html.replace('src="/static/', 'src="static/')

    # the model has to be in memory before app.js makes its first call
    marker = '<script src="static/js/app.js"'
    if marker not in html:
        raise SystemExit("could not find app.js script tag to inject before")
    html = html.replace(marker, INJECT.strip() + "\n" + marker, 1)

    # root-relative links would leave the project subpath
    html = re.sub(r'href="/"', 'href="./"', html)

    (OUT / "index.html").write_text(html, encoding="utf-8")
    raw = OUT / "_raw.html"
    if raw.exists():
        raw.unlink()

    css = sum(f.stat().st_size for f in (OUT / "static" / "css").iterdir())
    js = sum(f.stat().st_size for f in (OUT / "static" / "js").iterdir())
    print(f"wrote site/index.html  {len(html)/1000:.1f} KB")
    print(f"  css {css/1000:.1f} KB   js {js/1000:.1f} KB")


if __name__ == "__main__":
    main()
