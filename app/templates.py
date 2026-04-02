import hashlib
import json
from pathlib import Path
from typing import Any

from fastapi.templating import Jinja2Templates
from starlette.requests import Request
from starlette.responses import Response


class _FlashTemplates(Jinja2Templates):
    """Jinja2Templates subclass that auto-injects flash messages and clears the cookie."""

    def TemplateResponse(self, name: str, context: dict[str, Any], **kwargs: Any) -> Response:
        request: Request = context.get("request")  # type: ignore[assignment]
        if request and not context.get("flash_msg"):
            from .auth.sessions import get_flash
            flash = get_flash(request)
            if flash:
                context["flash_msg"], context["flash_level"] = flash
        resp = super().TemplateResponse(name, context, **kwargs)
        if context.get("flash_msg"):
            resp.delete_cookie("cleanarr_flash")
        return resp


templates = _FlashTemplates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["from_json"] = json.loads

def _timestamp_date(ts: int | str) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")

templates.env.filters["timestamp_date"] = _timestamp_date

# Cache-busting hash for static CSS
_css_path = Path(__file__).parent / "static" / "style.css"
_css_hash = hashlib.md5(_css_path.read_bytes()).hexdigest()[:8]
templates.env.globals["css_hash"] = _css_hash
