"""Generate a deterministic Dockerfile from a v2 manifest's Env block.

The Dockerfile shape is fixed by the standard. Authors do not write Dockerfiles
in the v2 world; they declare env and we emit the build. This module mirrors
``plutus_verify.builder.dockerfile`` but consumes the v2 ``Env`` directly.
"""
from __future__ import annotations

from plutus_verify.spec.manifest import Env, Secret


class UnsupportedEnvError(NotImplementedError):
    """Raised when an Env asks for capability not yet implemented."""


def generate_dockerfile(
    env: Env,
    *,
    secrets: tuple[Secret, ...] = (),
    sdk_wheel_basename: str | None = None,
) -> str:
    if env.gpu_required:
        raise UnsupportedEnvError(
            "GPU support not implemented in Plan 2 — deferred to Plan 2.5"
        )
    if env.base == "python-cuda":
        raise UnsupportedEnvError(
            "env.base=python-cuda not supported in Plan 2 — deferred to Plan 2.5"
        )
    if env.base == "none":
        raise UnsupportedEnvError("env.base=none not supported (no base image)")

    _ = secrets  # reserved for future use (e.g., build-time env)

    lines: list[str] = [
        f"FROM python:{env.python_version}-slim",
        "WORKDIR /srv/repo",
    ]
    if env.os_packages:
        joined = " ".join(sorted(set(env.os_packages)))
        lines.extend(
            [
                "RUN apt-get update \\",
                f"    && apt-get install -y --no-install-recommends {joined} \\",
                "    && rm -rf /var/lib/apt/lists/*",
            ]
        )
    if env.requirements_file:
        lines.extend(
            [
                f"COPY {env.requirements_file} .",
                f"RUN pip install --no-cache-dir -r {env.requirements_file}",
            ]
        )
    if sdk_wheel_basename:
        # Stage the verifier SDK so author scripts can `import plutus_verify`
        # without touching their own requirements.txt. The wheel is placed in
        # the build context at .plutus/build/<basename> by the orchestrator
        # before `docker build` is invoked.
        lines.extend(
            [
                f"COPY .plutus/build/{sdk_wheel_basename} /tmp/{sdk_wheel_basename}",
                f"RUN pip install --no-cache-dir /tmp/{sdk_wheel_basename}",
            ]
        )
    lines.extend(
        [
            "COPY . .",
            'CMD ["python", "--version"]',
        ]
    )
    return "\n".join(lines) + "\n"
