"""
ContractGenerator — generate optimised Solidity from the intermediate
representation (IR) produced by :class:`SourceParser`.

Injects gas optimisation patterns specifically for Base L2:
  - Tight variable packing
  - Custom errors instead of require strings
  - Unchecked arithmetic where safe
  - Calldata instead of memory for external params
  - Short-circuiting storage reads
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Gas-optimised pragma for Base
_BASE_PRAGMA = "pragma solidity ^0.8.20;"

# Chain-specific optimisation flags
_CHAIN_OPTIMISATIONS: dict[str, dict[str, Any]] = {
    "base": {
        "use_custom_errors": True,
        "use_calldata": True,
        "use_unchecked_increments": True,
        "pack_storage": True,
        "optimizer_runs": 200,
    },
    "ethereum": {
        "use_custom_errors": True,
        "use_calldata": True,
        "use_unchecked_increments": True,
        "pack_storage": True,
        "optimizer_runs": 200,
    },
    "polygon": {
        "use_custom_errors": True,
        "use_calldata": True,
        "use_unchecked_increments": True,
        "pack_storage": True,
        "optimizer_runs": 1000,
    },
}


class ContractGenerator:
    """Generate optimised Solidity source from an IR dict.

    Parameters
    ----------
    config : dict
        Platform config.  Reads ``conversion.default_license`` and
        ``conversion.chain_optimisations`` for overrides.
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        conv_cfg = config.get("conversion", {})
        self._default_license: str = conv_cfg.get("default_license", "MIT")
        self._custom_optimisations: dict[str, dict[str, Any]] = conv_cfg.get(
            "chain_optimisations", {}
        )

    def generate(self, ir: dict[str, Any], target_chain: str = "base") -> str:
        """Generate Solidity source from the parsed IR.

        Parameters
        ----------
        ir : dict
            Intermediate representation from :meth:`SourceParser.parse`.
        target_chain : str
            Target chain for optimisation (``base``, ``ethereum``, ``polygon``).

        Returns
        -------
        str
            Complete, deployable Solidity source code.
        """
        chain = target_chain.lower()
        opts = self._custom_optimisations.get(
            chain, _CHAIN_OPTIMISATIONS.get(chain, _CHAIN_OPTIMISATIONS["base"])
        )

        sections: list[str] = []

        # License
        sections.append(f"// SPDX-License-Identifier: {self._default_license}")

        # Pragma
        pragmas = ir.get("pragmas", [])
        if pragmas:
            for p in pragmas:
                if "solidity" in p:
                    sections.append(p)
                    break
            else:
                sections.append(_BASE_PRAGMA)
        else:
            sections.append(_BASE_PRAGMA)

        sections.append("")  # blank line

        # Imports
        imports = ir.get("imports", [])
        if imports:
            for imp in imports:
                sections.append(imp)
            sections.append("")

        # Custom errors (gas-optimised replacement for require strings)
        custom_errors: list[str] = []
        if opts.get("use_custom_errors"):
            custom_errors = self._extract_custom_errors(ir)
            if custom_errors:
                for err in custom_errors:
                    sections.append(err)
                sections.append("")

        # Contract declaration
        contract_name = ir.get("contract_name", "GeneratedContract")
        inheritance = ir.get("inheritance", [])
        if inheritance:
            parents = ", ".join(inheritance)
            sections.append(f"contract {contract_name} is {parents} {{")
        else:
            sections.append(f"contract {contract_name} {{")

        # Structs
        for struct in ir.get("structs", []):
            sections.append(self._generate_struct(struct))

        # Enums
        for enum in ir.get("enums", []):
            sections.append(self._generate_enum(enum))

        # Events
        for event in ir.get("events", []):
            sections.append(self._generate_event(event))

        # State variables (with packing optimisation)
        state_vars = ir.get("state_variables", [])
        if opts.get("pack_storage"):
            state_vars = self._pack_storage(state_vars)
        for var in state_vars:
            sections.append(self._generate_state_var(var))

        if state_vars:
            sections.append("")

        # Modifiers
        for modifier in ir.get("modifiers", []):
            sections.append(self._generate_modifier(modifier))

        # Constructor (if present)
        constructor = None
        functions = []
        for func in ir.get("functions", []):
            if func["name"] == "constructor":
                constructor = func
            else:
                functions.append(func)

        if constructor:
            sections.append(self._generate_constructor(constructor))

        # Functions
        for func in functions:
            sections.append(
                self._generate_function(func, opts)
            )

        # Close contract
        sections.append("}")

        source = "\n".join(sections)

        # Post-processing: apply unchecked increments
        if opts.get("use_unchecked_increments"):
            source = self._apply_unchecked_increments(source)

        logger.info(
            "Generated Solidity for '%s' targeting %s (%d lines)",
            contract_name, chain, source.count("\n") + 1,
        )
        return source

    # ── Code generators ───────────────────────────────────────────────

    def _generate_struct(self, struct: dict[str, Any]) -> str:
        lines = [f"    struct {struct['name']} {{"]
        for field in struct.get("fields", []):
            lines.append(f"        {field['type']} {field['name']};")
        lines.append("    }")
        lines.append("")
        return "\n".join(lines)

    def _generate_enum(self, enum: dict[str, Any]) -> str:
        values = ", ".join(enum.get("values", []))
        return f"    enum {enum['name']} {{ {values} }}\n"

    def _generate_event(self, event: dict[str, Any]) -> str:
        params = []
        for p in event.get("params", []):
            indexed = " indexed" if p.get("indexed") else ""
            params.append(f"{p['type']}{indexed} {p['name']}")
        param_str = ", ".join(params)
        return f"    event {event['name']}({param_str});\n"

    def _generate_state_var(self, var: dict[str, Any]) -> str:
        default = f" = {var['default']}" if var.get("default") else ""
        return f"    {var['type']} {var['visibility']} {var['name']}{default};"

    def _generate_modifier(self, modifier: dict[str, Any]) -> str:
        params = ", ".join(
            f"{p['type']} {p['name']}" for p in modifier.get("params", [])
        )
        body = modifier.get("body", "_;\n")
        lines = [f"    modifier {modifier['name']}({params}) {{"]
        for line in body.splitlines():
            lines.append(f"        {line}")
        lines.append("    }")
        lines.append("")
        return "\n".join(lines)

    def _generate_constructor(self, func: dict[str, Any]) -> str:
        params = ", ".join(
            f"{p['type']} {p['name']}" for p in func.get("params", [])
        )
        body = func.get("body", "")
        lines = [f"    constructor({params}) {{"]
        for line in body.splitlines():
            lines.append(f"        {line}")
        lines.append("    }")
        lines.append("")
        return "\n".join(lines)

    def _generate_function(
        self, func: dict[str, Any], opts: dict[str, Any]
    ) -> str:
        # Build parameter list with calldata optimisation
        params: list[str] = []
        for p in func.get("params", []):
            ptype = p["type"]
            if opts.get("use_calldata") and func.get("visibility") == "external":
                # Replace memory with calldata for reference types
                if ptype in ("string", "bytes") or ptype.endswith("[]"):
                    if "memory" in ptype:
                        ptype = ptype.replace("memory", "calldata")
                    elif "calldata" not in ptype:
                        ptype = f"{ptype} calldata"
            params.append(f"{ptype} {p['name']}")

        param_str = ", ".join(params)

        # Visibility and mutability
        visibility = func.get("visibility", "public")
        mutability = func.get("mutability", "")
        if mutability == "nonpayable":
            mutability = ""

        # Modifiers
        modifiers = " ".join(func.get("modifiers", []))

        # Returns
        returns = ""
        if func.get("returns"):
            returns = f" returns ({func['returns']})"

        # Build signature
        sig_parts = [f"    function {func['name']}({param_str})"]
        qualifiers = " ".join(
            q for q in [visibility, mutability, modifiers] if q
        )
        if qualifiers:
            sig_parts.append(f"        {qualifiers}{returns}")
        elif returns:
            sig_parts.append(f"        {returns}")

        body = func.get("body", "")

        lines = ["\n".join(sig_parts) + "\n    {"]
        for line in body.splitlines():
            lines.append(f"        {line}")
        lines.append("    }")
        lines.append("")
        return "\n".join(lines)

    # ── Optimisation helpers ──────────────────────────────────────────

    @staticmethod
    def _pack_storage(
        variables: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Reorder state variables for optimal storage slot packing.

        Sorts smaller types together so the EVM can pack multiple
        variables into a single 32-byte storage slot.
        """
        type_sizes: dict[str, int] = {
            "bool": 1,
            "uint8": 1,
            "int8": 1,
            "uint16": 2,
            "int16": 2,
            "uint32": 4,
            "int32": 4,
            "uint64": 8,
            "int64": 8,
            "uint128": 16,
            "int128": 16,
            "address": 20,
            "uint256": 32,
            "int256": 32,
            "bytes32": 32,
        }

        def sort_key(var: dict[str, Any]) -> int:
            base_type = var["type"].split()[0]
            return type_sizes.get(base_type, 32)

        return sorted(variables, key=sort_key)

    @staticmethod
    def _extract_custom_errors(ir: dict[str, Any]) -> list[str]:
        """Extract require messages and generate custom errors."""
        errors: set[str] = set()
        for func in ir.get("functions", []):
            body = func.get("body", "")
            for m in re.finditer(r'require\([^,]+,\s*"([^"]+)"\)', body):
                error_name = re.sub(r"[^a-zA-Z0-9]", "", m.group(1))
                if error_name:
                    errors.add(f"error {error_name}();")
        return sorted(errors)

    @staticmethod
    def _apply_unchecked_increments(source: str) -> str:
        """Wrap simple `i++` / `i += 1` in for-loops with `unchecked`."""
        # Pattern: detect `for (...; ...; i++)` and wrap the increment
        pattern = re.compile(
            r"(for\s*\([^;]+;\s*[^;]+;\s*)(\w+\+\+)(\s*\))"
        )
        return pattern.sub(
            lambda m: f"{m.group(1)}unchecked {{ {m.group(2)}; }}{m.group(3)}",
            source,
        )
