from . import applications, content, i18n, menu, people, shops, system  # noqa: F401 — регистрируют экраны
from .core import router

__all__ = ["router"]
