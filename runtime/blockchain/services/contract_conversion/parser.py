"""
SourceParser — parse Solidity, Vyper, or pseudocode into an AST-like
intermediate representation (IR).

The IR is a plain dict with normalised keys so that the generator can
produce optimised Solidity regardless of the source language.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Supported source languages
SUPPORTED_LANGUAGES: set[str] = {"solidity", "vyper", "pseudocode"}


class SourceParser:
    """Parse smart-contract source code into an intermediate representation.

    Parameters
    ----------
    config : dict
        Platform config (currently unused, reserved for future parser
        plugin configuration).
    """

    def __init__(self, config: dict) -> None:
        self._config = config

    def parse(self, source: str, lang: str) -> dict[str, Any]:
        """Parse *source* written in *lang* and return an IR dict.

        The IR contains:
            - ``contract_name`` (str)
            - ``lang`` (str) — normalised source language
            - ``pragmas`` (list[str])
            - ``imports`` (list[str])
            - ``state_variables`` (list[dict])
            - ``functions`` (list[dict])
            - ``events`` (list[dict])
            - ``modifiers`` (list[dict])
            - ``structs`` (list[dict])
            - ``enums`` (list[dict])
            - ``inheritance`` (list[str])
            - ``raw_source`` (str)

        Raises
        ------
        ValueError
            If *lang* is not one of ``solidity``, ``vyper``, ``pseudocode``.
        """
        lang = lang.strip().lower()
        if lang not in SUPPORTED_LANGUAGES:
            raise ValueError(
                f"Unsupported language '{lang}'. "
                f"Supported: {', '.join(sorted(SUPPORTED_LANGUAGES))}"
            )

        dispatch = {
            "solidity": self._parse_solidity,
            "vyper": self._parse_vyper,
            "pseudocode": self._parse_pseudocode,
        }

        ir = dispatch[lang](source)
        ir["lang"] = lang
        ir["raw_source"] = source

        logger.info(
            "Parsed %s source: contract=%s functions=%d state_vars=%d events=%d",
            lang,
            ir.get("contract_name", "<unknown>"),
            len(ir.get("functions", [])),
            len(ir.get("state_variables", [])),
            len(ir.get("events", [])),
        )
        return ir

    # ── Solidity parser ───────────────────────────────────────────────

    def _parse_solidity(self, source: str) -> dict[str, Any]:
        ir: dict[str, Any] = self._empty_ir()

        # Pragmas
        ir["pragmas"] = re.findall(r"pragma\s+[^;]+;", source)

        # Imports
        ir["imports"] = re.findall(r'import\s+[^;]+;', source)

        # Contract name and inheritance
        contract_match = re.search(
            r"contract\s+(\w+)(?:\s+is\s+([\w\s,]+))?\s*\{", source
        )
        if contract_match:
            ir["contract_name"] = contract_match.group(1)
            if contract_match.group(2):
                ir["inheritance"] = [
                    s.strip() for s in contract_match.group(2).split(",")
                ]

        # State variables
        state_var_pattern = re.compile(
            r"^\s*((?:uint\d*|int\d*|address|bool|string|bytes\d*|mapping\s*\([^)]+\))\s+"
            r"(?:public\s+|private\s+|internal\s+|external\s+|immutable\s+|constant\s+)*"
            r"(\w+))\s*(?:=\s*([^;]+))?;",
            re.MULTILINE,
        )
        for m in state_var_pattern.finditer(source):
            full_decl = m.group(1).strip()
            var_name = m.group(2)
            default_value = m.group(3).strip() if m.group(3) else None
            # Extract type and visibility from full declaration
            visibility = "internal"
            for vis in ("public", "private", "external", "internal"):
                if vis in full_decl:
                    visibility = vis
                    break
            type_match = re.match(r"([\w\s\(\),]+?)\s+(?:public|private|internal|external|immutable|constant\s+)*\w+$", full_decl)
            var_type = type_match.group(1).strip() if type_match else full_decl.split()[0]
            ir["state_variables"].append({
                "name": var_name,
                "type": var_type,
                "visibility": visibility,
                "default": default_value,
            })

        # Functions
        func_pattern = re.compile(
            r"function\s+(\w+)\s*\(([^)]*)\)\s*"
            r"((?:(?:public|private|internal|external|view|pure|payable|virtual|override|"
            r"nonReentrant|onlyOwner|returns\s*\([^)]*\))\s*)*)"
            r"\{",
            re.MULTILINE,
        )
        for m in func_pattern.finditer(source):
            name = m.group(1)
            params_raw = m.group(2).strip()
            modifiers_raw = m.group(3).strip()

            params = self._parse_params(params_raw)
            visibility = "public"
            for vis in ("external", "public", "internal", "private"):
                if vis in modifiers_raw:
                    visibility = vis
                    break
            mutability = "nonpayable"
            for mut in ("view", "pure", "payable"):
                if mut in modifiers_raw:
                    mutability = mut
                    break

            returns_match = re.search(r"returns\s*\(([^)]*)\)", modifiers_raw)
            returns = returns_match.group(1).strip() if returns_match else None

            func_modifiers = []
            for mod in ("onlyOwner", "nonReentrant", "virtual", "override"):
                if mod in modifiers_raw:
                    func_modifiers.append(mod)

            # Extract function body
            body = self._extract_body(source, m.end() - 1)

            ir["functions"].append({
                "name": name,
                "params": params,
                "visibility": visibility,
                "mutability": mutability,
                "returns": returns,
                "modifiers": func_modifiers,
                "body": body,
            })

        # Events
        event_pattern = re.compile(r"event\s+(\w+)\s*\(([^)]*)\)\s*;")
        for m in event_pattern.finditer(source):
            ir["events"].append({
                "name": m.group(1),
                "params": self._parse_params(m.group(2).strip()),
            })

        # Modifiers
        mod_pattern = re.compile(r"modifier\s+(\w+)\s*\(([^)]*)\)\s*\{")
        for m in mod_pattern.finditer(source):
            body = self._extract_body(source, m.end() - 1)
            ir["modifiers"].append({
                "name": m.group(1),
                "params": self._parse_params(m.group(2).strip()),
                "body": body,
            })

        # Structs
        struct_pattern = re.compile(r"struct\s+(\w+)\s*\{([^}]+)\}")
        for m in struct_pattern.finditer(source):
            fields = []
            for line in m.group(2).strip().splitlines():
                line = line.strip().rstrip(";").strip()
                if line:
                    parts = line.rsplit(None, 1)
                    if len(parts) == 2:
                        fields.append({"type": parts[0], "name": parts[1]})
            ir["structs"].append({"name": m.group(1), "fields": fields})

        # Enums
        enum_pattern = re.compile(r"enum\s+(\w+)\s*\{([^}]+)\}")
        for m in enum_pattern.finditer(source):
            values = [v.strip() for v in m.group(2).split(",") if v.strip()]
            ir["enums"].append({"name": m.group(1), "values": values})

        return ir

    # ── Vyper parser ──────────────────────────────────────────────────

    def _parse_vyper(self, source: str) -> dict[str, Any]:
        ir: dict[str, Any] = self._empty_ir()

        # Vyper version pragma
        version_match = re.search(r"#\s*@version\s+(.+)", source)
        if version_match:
            ir["pragmas"] = [f"# @version {version_match.group(1).strip()}"]

        # Interfaces/imports
        ir["imports"] = re.findall(r"from\s+\S+\s+import\s+\S+", source)

        # Contract name from comments or filename convention
        name_match = re.search(r"#\s*@title\s+(\w+)", source)
        ir["contract_name"] = name_match.group(1) if name_match else "VyperContract"

        # State variables (Vyper: `name: type`)
        state_var_pattern = re.compile(
            r"^(\w+)\s*:\s*((?:public|constant|immutable)\s*\()?\s*"
            r"([\w\[\]()., ]+)\)?\s*(?:=\s*(.+))?$",
            re.MULTILINE,
        )
        for m in state_var_pattern.finditer(source):
            var_name = m.group(1)
            # Skip function defs and decorators
            if var_name in ("def", "event", "struct", "interface", "from", "import"):
                continue
            visibility = "public" if m.group(2) and "public" in m.group(2) else "internal"
            var_type = m.group(3).strip()
            default = m.group(4).strip() if m.group(4) else None
            ir["state_variables"].append({
                "name": var_name,
                "type": self._vyper_type_to_solidity(var_type),
                "visibility": visibility,
                "default": default,
            })

        # Functions
        func_pattern = re.compile(
            r"@(external|internal|view|pure|payable|nonreentrant\([^)]*\))\s*\n"
            r"(?:@(\w+)[^\n]*\n)*"
            r"def\s+(\w+)\s*\(([^)]*)\)\s*(?:->\s*([^:]+))?\s*:",
            re.MULTILINE,
        )
        for m in func_pattern.finditer(source):
            decorators = [m.group(1)]
            if m.group(2):
                decorators.append(m.group(2))
            name = m.group(3)
            params_raw = m.group(4).strip()
            returns = m.group(5).strip() if m.group(5) else None

            visibility = "public"
            mutability = "nonpayable"
            for dec in decorators:
                if dec in ("external", "internal"):
                    visibility = dec
                if dec in ("view", "pure", "payable"):
                    mutability = dec

            params = self._parse_vyper_params(params_raw)

            # Extract indented body
            body = self._extract_vyper_body(source, m.end())

            ir["functions"].append({
                "name": name if name != "__init__" else "constructor",
                "params": params,
                "visibility": visibility if name != "__init__" else "public",
                "mutability": mutability,
                "returns": self._vyper_type_to_solidity(returns) if returns else None,
                "modifiers": [],
                "body": body,
            })

        # Events
        event_pattern = re.compile(
            r"event\s+(\w+):\s*\n((?:\s+\w+:\s*\w+[^\n]*\n)*)", re.MULTILINE
        )
        for m in event_pattern.finditer(source):
            params = []
            for line in m.group(2).strip().splitlines():
                line = line.strip()
                if ":" in line:
                    pname, ptype = line.split(":", 1)
                    indexed = "indexed" in ptype
                    ptype = ptype.replace("indexed", "").strip()
                    params.append({
                        "name": pname.strip(),
                        "type": self._vyper_type_to_solidity(ptype),
                        "indexed": indexed,
                    })
            ir["events"].append({"name": m.group(1), "params": params})

        # Structs
        struct_pattern = re.compile(
            r"struct\s+(\w+):\s*\n((?:\s+\w+:\s*\w+[^\n]*\n)*)", re.MULTILINE
        )
        for m in struct_pattern.finditer(source):
            fields = []
            for line in m.group(2).strip().splitlines():
                line = line.strip()
                if ":" in line:
                    fname, ftype = line.split(":", 1)
                    fields.append({
                        "name": fname.strip(),
                        "type": self._vyper_type_to_solidity(ftype.strip()),
                    })
            ir["structs"].append({"name": m.group(1), "fields": fields})

        return ir

    # ── Pseudocode parser ─────────────────────────────────────────────

    def _parse_pseudocode(self, source: str) -> dict[str, Any]:
        ir: dict[str, Any] = self._empty_ir()
        ir["pragmas"] = ["pragma solidity ^0.8.20;"]

        # Extract contract name
        name_match = re.search(
            r"(?:contract|class|module|token)\s+(\w+)", source, re.IGNORECASE
        )
        ir["contract_name"] = name_match.group(1) if name_match else "GeneratedContract"

        # Extract state variables from declarations like "variable: type" or "type variable"
        var_patterns = [
            re.compile(r"(?:var|let|state|storage)\s+(\w+)\s*:\s*(\w+)", re.IGNORECASE),
            re.compile(r"(?:var|let|state|storage)\s+(\w+)\s+as\s+(\w+)", re.IGNORECASE),
        ]
        for pat in var_patterns:
            for m in pat.finditer(source):
                ir["state_variables"].append({
                    "name": m.group(1),
                    "type": self._pseudo_type_to_solidity(m.group(2)),
                    "visibility": "public",
                    "default": None,
                })

        # Extract functions from patterns like "function name(params)" or "def name(params)"
        func_pattern = re.compile(
            r"(?:function|def|method|action)\s+(\w+)\s*\(([^)]*)\)"
            r"(?:\s*(?:->|returns?|:)\s*(\w+))?",
            re.IGNORECASE,
        )
        for m in func_pattern.finditer(source):
            name = m.group(1)
            params = self._parse_pseudo_params(m.group(2).strip())
            returns = self._pseudo_type_to_solidity(m.group(3)) if m.group(3) else None

            # Guess visibility from keywords
            line_start = source.rfind("\n", 0, m.start()) + 1
            line = source[line_start:m.end()]
            visibility = "public"
            if "private" in line.lower() or "internal" in line.lower():
                visibility = "internal"
            mutability = "nonpayable"
            if "view" in line.lower() or "readonly" in line.lower():
                mutability = "view"
            if "payable" in line.lower():
                mutability = "payable"

            # Extract body as everything indented after the function line
            body = self._extract_pseudo_body(source, m.end())

            ir["functions"].append({
                "name": name,
                "params": params,
                "visibility": visibility,
                "mutability": mutability,
                "returns": returns,
                "modifiers": [],
                "body": body,
            })

        # Extract events from "event Name(params)" or "emit Name"
        event_pattern = re.compile(
            r"event\s+(\w+)\s*\(([^)]*)\)", re.IGNORECASE
        )
        for m in event_pattern.finditer(source):
            ir["events"].append({
                "name": m.group(1),
                "params": self._parse_pseudo_params(m.group(2).strip()),
            })

        return ir

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _empty_ir() -> dict[str, Any]:
        return {
            "contract_name": "",
            "pragmas": [],
            "imports": [],
            "state_variables": [],
            "functions": [],
            "events": [],
            "modifiers": [],
            "structs": [],
            "enums": [],
            "inheritance": [],
        }

    @staticmethod
    def _parse_params(raw: str) -> list[dict[str, str]]:
        if not raw:
            return []
        params = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            tokens = part.split()
            if len(tokens) >= 2:
                param_type = " ".join(tokens[:-1])
                param_name = tokens[-1]
            else:
                param_type = tokens[0]
                param_name = f"param{len(params)}"
            params.append({"type": param_type, "name": param_name})
        return params

    @staticmethod
    def _parse_vyper_params(raw: str) -> list[dict[str, str]]:
        if not raw:
            return []
        params = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            if ":" in part:
                name, ptype = part.split(":", 1)
                params.append({"type": ptype.strip(), "name": name.strip()})
            else:
                params.append({"type": part, "name": f"param{len(params)}"})
        return params

    @staticmethod
    def _parse_pseudo_params(raw: str) -> list[dict[str, str]]:
        if not raw:
            return []
        params = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            if ":" in part:
                name, ptype = part.split(":", 1)
                params.append({
                    "type": ptype.strip(),
                    "name": name.strip(),
                })
            elif " " in part:
                tokens = part.split()
                params.append({
                    "type": " ".join(tokens[:-1]),
                    "name": tokens[-1],
                })
            else:
                params.append({"type": "uint256", "name": part})
        return params

    @staticmethod
    def _extract_body(source: str, brace_pos: int) -> str:
        """Extract the body of a braced block starting at *brace_pos*."""
        depth = 0
        start = brace_pos
        for i in range(brace_pos, len(source)):
            if source[i] == "{":
                depth += 1
            elif source[i] == "}":
                depth -= 1
                if depth == 0:
                    return source[start + 1:i].strip()
        return source[start + 1:].strip()

    @staticmethod
    def _extract_vyper_body(source: str, start_pos: int) -> str:
        """Extract indented body after a Vyper function definition."""
        lines = source[start_pos:].split("\n")
        body_lines: list[str] = []
        for line in lines[1:]:  # skip the colon line
            if line and not line[0].isspace() and line.strip():
                break
            body_lines.append(line)
        return "\n".join(body_lines).strip()

    @staticmethod
    def _extract_pseudo_body(source: str, start_pos: int) -> str:
        """Extract indented body after a pseudocode function."""
        lines = source[start_pos:].split("\n")
        body_lines: list[str] = []
        for line in lines[1:]:
            if line and not line[0].isspace() and line.strip():
                break
            body_lines.append(line)
        return "\n".join(body_lines).strip()

    @staticmethod
    def _vyper_type_to_solidity(vyper_type: str) -> str:
        """Convert a Vyper type name to its Solidity equivalent."""
        mapping = {
            "uint256": "uint256",
            "int128": "int128",
            "int256": "int256",
            "decimal": "uint256",  # Vyper decimal -> uint256 (scaled)
            "bool": "bool",
            "address": "address",
            "bytes32": "bytes32",
            "String": "string",
            "Bytes": "bytes",
            "DynArray": "uint256[]",
            "HashMap": "mapping",
        }
        for vyper_t, sol_t in mapping.items():
            if vyper_type and vyper_t in vyper_type:
                return sol_t
        return vyper_type if vyper_type else "uint256"

    @staticmethod
    def _pseudo_type_to_solidity(pseudo_type: str) -> str:
        """Convert a pseudocode type to Solidity type."""
        mapping = {
            "int": "uint256",
            "integer": "uint256",
            "number": "uint256",
            "float": "uint256",
            "string": "string",
            "str": "string",
            "bool": "bool",
            "boolean": "bool",
            "address": "address",
            "addr": "address",
            "bytes": "bytes",
            "map": "mapping(address => uint256)",
            "list": "uint256[]",
            "array": "uint256[]",
        }
        return mapping.get(pseudo_type.lower(), pseudo_type) if pseudo_type else "uint256"
