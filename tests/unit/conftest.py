"""Test configuration and fixtures."""
import sys
from unittest.mock import MagicMock

# Mock httpx at import time before extract modules load
sys.modules["httpx"] = MagicMock()
