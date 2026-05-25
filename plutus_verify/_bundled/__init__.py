"""Prebuilt wheel of plutus_verify, vendored by the release script.

When the package is installed from a release wheel, ``plutus_verify-X.Y.Z-
py3-none-any.whl`` sits in this directory. The runtime helper
:func:`plutus_verify.spec.runtime.sdk_bundle.ensure_plutus_wheel` looks for
it here first and uses it as-is to populate the Docker build context --
avoiding the fragile source-locate-and-rebuild path entirely.

In dev installs (`pip install -e .`), this directory is empty; the helper
falls back to building a wheel from the local source tree.
"""
