import hashlib
import json
from pathlib import Path

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["from_json"] = json.loads

# Cache-busting hash for static CSS
_css_path = Path(__file__).parent / "static" / "style.css"
_css_hash = hashlib.md5(_css_path.read_bytes()).hexdigest()[:8]
templates.env.globals["css_hash"] = _css_hash
