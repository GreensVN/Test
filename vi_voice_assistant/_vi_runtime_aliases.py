"""Lazy aliases for the stateful runtime modules used by legacy scripts.

Only canonical names below this package are intercepted. Other short-name
modules are never replaced, and original flat specs are restored for reload().
This is not a hot-upgrade repair for already duplicated live module instances.
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from importlib.machinery import ModuleSpec
    from types import CodeType, ModuleType

_CORE_MODULES = ("paths", "config", "executor", "nlu_advanced", "stt", "tts")


class _CoreAliasLoader(importlib.abc.Loader):
    def __init__(self, short_name: str, expected_file: Path) -> None:
        self.short_name = short_name
        self.expected_file = expected_file.resolve()
        self.original_spec: ModuleSpec | None = None

    def _check_origin(self, origin: str | None) -> None:
        try:
            matches = origin is not None and Path(origin).resolve() == self.expected_file
        except (OSError, ValueError, RuntimeError):
            matches = False
        if not matches:
            raise ImportError(
                f"Cannot alias {self.short_name!r}: an unrelated short-name module shadows "
                f"{self.expected_file}"
            )

    def create_module(self, spec: ModuleSpec) -> ModuleType:
        loaded = sys.modules.get(self.short_name)
        if loaded is not None:
            self._check_origin(getattr(loaded, "__file__", None))
        else:
            found = importlib.util.find_spec(self.short_name)
            self._check_origin(found.origin if found is not None else None)
        # The ordinary flat import lock handles concurrent initialization.
        module = importlib.import_module(self.short_name)
        self._check_origin(getattr(module, "__file__", None))
        self.original_spec = module.__spec__
        return module

    def get_code(self, fullname: str) -> CodeType | None:
        """Delegate runpy/-m to source instead of treating an alias as source code."""
        found = importlib.util.find_spec(self.short_name)
        self._check_origin(found.origin if found is not None else None)
        getter = getattr(found.loader if found is not None else None, "get_code", None)
        if not callable(getter):
            raise ImportError(f"No source loader for {fullname}")
        code: CodeType | None = getter(self.short_name)
        return code

    def exec_module(self, module: ModuleType) -> None:
        # module_from_spec temporarily installs the alias spec. Keeping it
        # would make importlib.reload() run this no-op loader instead of source.
        module.__spec__ = self.original_spec


class _CoreAliasFinder(importlib.abc.MetaPathFinder):
    def __init__(self, package: str, root: Path) -> None:
        self._vi_alias_key = (package, str(root))
        self.aliases = {f"{package}.{name}": (name, root / f"{name}.py")
                        for name in _CORE_MODULES}

    def find_spec(self, fullname: str, path: Sequence[str] | None = None,
                  target: ModuleType | None = None) -> ModuleSpec | None:
        item = self.aliases.get(fullname)
        if item is None:
            return None
        short_name, filename = item
        return importlib.util.spec_from_loader(
            fullname, _CoreAliasLoader(short_name, filename), origin=str(filename), is_package=False
        )


def install_runtime_aliases(package: str, directory: str) -> None:
    root = Path(directory).resolve()
    key = (package, str(root))
    if not any(getattr(finder, "_vi_alias_key", None) == key for finder in sys.meta_path):
        sys.meta_path.insert(0, _CoreAliasFinder(package, root))
