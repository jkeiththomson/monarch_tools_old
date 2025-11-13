# Compatibility shim for older console-script entry points that expect `monarch_tools.cli:main`
from .console import main

__all__ = ["main"]
