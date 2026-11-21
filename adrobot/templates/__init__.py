from pathlib import Path

from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

templates = Environment(
    loader=FileSystemLoader(Path(__file__).parent),
    autoescape=select_autoescape(["html"]),
    undefined=StrictUndefined,
)


def render(
    template: str, title: str, *, status_code: int = 200, **context: object
) -> HTMLResponse:
    content = templates.get_template(template).render(title=title, **context)
    return HTMLResponse(content, status_code=status_code)
