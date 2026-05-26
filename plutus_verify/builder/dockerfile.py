"""Template generator for the auto-fixing build path."""
from __future__ import annotations

from typing import Iterable


_BASE_IMAGE = "python:3.11-slim"


def generate_dockerfile(
    *,
    apt_packages: Iterable[str] = (),
    base_image: str = _BASE_IMAGE,
) -> str:
    """Render a minimal Dockerfile that installs the repo's requirements.

    If ``apt_packages`` is non-empty, install them in a separate layer
    before pip (lets fixers inject dev headers like libpq-dev / build-essential).
    """
    apt_list = list(apt_packages)
    lines: list[str] = [f"FROM {base_image}", "WORKDIR /srv/repo"]
    if apt_list:
        joined = " ".join(sorted(set(apt_list)))
        lines.extend(
            [
                "RUN apt-get update \\",
                f"    && apt-get install -y --no-install-recommends {joined} \\",
                "    && rm -rf /var/lib/apt/lists/*",
            ]
        )
    lines.extend(
        [
            "COPY requirements.txt .",
            "RUN pip install --no-cache-dir -r requirements.txt",
            "COPY . .",
            'CMD ["python", "--version"]',
        ]
    )
    return "\n".join(lines) + "\n"
