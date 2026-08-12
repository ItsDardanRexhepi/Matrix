"""Does this method mutate SERVICE STATE? One implementation, shared.

WHY THIS IS A MODULE AND NOT A HELPER IN ONE TEST FILE. This logic has been
wrong twice and fixed twice — NEW-99 (`_mutates` blind to alias writes) and
NEW-99b (`_shape`'s write clause, the same gap in the sibling function of the
same file, left half-fixed for one commit). D11 is now a third consumer.

Three copies of a rule that has already needed two corrections is the
vocabulary-drift problem in a new costume: the next fix reaches whichever
copies its author happens to remember. tests/refusal_primitives.py exists for
exactly this reason on the refusal side; this is its counterpart for mutation.

THE RULE, and both of its known limits, stated rather than implied:

  MATCHES  self.<store>[k] = v
           self.<store>.append/update/setdefault/pop/extend/remove/clear(...)
           <alias>[k] = v            where <alias> was bound from self.*
           <alias>.append(...)  etc.  same

  LIMIT 1 — REBINDING UN-ALIASES, and this is load-bearing rather than a
  nicety. `NFTService.process_sale` does

      sale_result = await self._royalty.process_sale(...)   # live ledger object
      sale_result = dict(sale_result)                       # NEW-90 defensive copy
      sale_result["status"] = "recorded_unsettled"          # mutates the COPY

  Without the rule, this reads as service-state mutation and every detector
  built on it fires on the one method where the aliasing bug was CORRECTED. A
  detector that flags a correct fix does not merely cry wolf — it creates
  pressure to revert the fix, which is worse than a miss.

  LIMIT 2 — ORDER-INSENSITIVE. A mutation occurring BEFORE a later rebinding is
  not counted. That trades silence on a narrow case for not crying wolf on the
  common one. Deliberate, not an oversight.
"""

from __future__ import annotations

import ast

#: Method names that mutate a container in place.
MUTATING_CALLS = (
    "append", "update", "setdefault", "pop", "extend", "remove", "clear",
)


def state_aliases(fn: ast.AST) -> set[str]:
    """Locals bound from service state; rebinding to anything else removes them."""
    aliases: set[str] = set()
    assigns = [n for n in ast.walk(fn) if isinstance(n, ast.Assign)]
    for node in sorted(assigns, key=lambda n: (n.lineno, n.col_offset)):
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        value = node.value
        if isinstance(value, ast.Await):
            value = value.value
        name = node.targets[0].id
        if ast.unparse(value).startswith("self."):
            aliases.add(name)
        else:
            aliases.discard(name)
    return aliases


def base_name(node: ast.AST) -> str | None:
    """The root Name of a possibly-nested subscript chain."""
    while isinstance(node, ast.Subscript):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def mutates_service_state(fn: ast.AST) -> bool:
    """True if this method changes state the service owns."""
    aliases = state_aliases(fn)

    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if not isinstance(target, ast.Subscript):
                    continue
                if (
                    isinstance(target.value, ast.Attribute)
                    and isinstance(target.value.value, ast.Name)
                    and target.value.value.id == "self"
                ):
                    return True
                if base_name(target) in aliases:
                    return True
        if isinstance(node, ast.Call):
            f = node.func
            if not (isinstance(f, ast.Attribute) and f.attr in MUTATING_CALLS):
                continue
            if (
                isinstance(f.value, ast.Attribute)
                and isinstance(f.value.value, ast.Name)
                and f.value.value.id == "self"
            ):
                return True
            if base_name(f.value) in aliases:
                return True
    return False
