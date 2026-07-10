"""Coach rule registry — docs/COACH.md §3, docs/ARCHITECTURE.md §1.

One module per rule in this package; each exposes a module-level ``RULE``
(a ``coach.proposals.Rule``). ``load_rules()`` auto-discovers every sibling
``*.py`` and collects their ``RULE`` — "adding a rule = one module in
coach/rules/, registered" (COACH §3), no central list to edit.

Import side effects matter: a rule module may register an action callback at
import time (the reading rule's one-tap habit-event writer, COACH §3.3), so
``load_rules()`` is also what wires those callbacks into ``app.notify`` — the
API process calls it at startup (app.main) so ``/api/nudges/act/{token}`` can
find them.
"""
from __future__ import annotations

import importlib
import pkgutil

from ..proposals import Rule

_CACHE: list[Rule] | None = None


def load_rules(force: bool = False) -> list[Rule]:
    global _CACHE
    if _CACHE is not None and not force:
        return _CACHE
    rules: list[Rule] = []
    for mod_info in pkgutil.iter_modules(__path__):
        if mod_info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{__name__}.{mod_info.name}")
        rule = getattr(module, "RULE", None)
        if isinstance(rule, Rule):
            rules.append(rule)
    rules.sort(key=lambda r: r.key)
    _CACHE = rules
    return rules
