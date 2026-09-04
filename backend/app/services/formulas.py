from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from app.core.llm import LLMError
from app.core.settings import BACKEND_ROOT
from app.engine.ast_sandbox import validate_expr

logger = logging.getLogger("nexus.formulas")

SELECT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["catalog_id"],
    "properties": {
        "catalog_id": {"type": "string"},
        "constants": {"type": "object"},
        "input_map": {"type": "object"},
    },
}


class CatalogFormula(BaseModel):
    id: str
    description: str = ""
    aliases: list[str] = Field(default_factory=list)
    mode: str = "calculation"
    shape: str = "per_row"
    output: str = "result"
    inputs: list[str] = Field(default_factory=list)
    ast: str
    gate_ast: str | None = None
    slots: dict[str, Any] = Field(default_factory=dict)
    input_hints: dict[str, list[str]] = Field(default_factory=dict)
    group_by: list[str] = Field(default_factory=list)


class FormulaCatalog(BaseModel):
    version: str
    formulas: list[CatalogFormula]

    def get(self, formula_id: str) -> CatalogFormula:
        for item in self.formulas:
            if item.id == formula_id:
                return item
        raise KeyError(formula_id)

    def ids(self) -> list[str]:
        return [item.id for item in self.formulas]


@lru_cache
def load_catalog(path: str | None = None) -> FormulaCatalog:
    file = Path(path) if path else BACKEND_ROOT / "data" / "formulas" / "v1.yaml"
    data = yaml.safe_load(file.read_text(encoding="utf-8"))
    catalog = FormulaCatalog.model_validate(data)
    for item in catalog.formulas:
        _assert_safe(item.ast)
        if item.gate_ast:
            _assert_safe(item.gate_ast)
    return catalog


def catalog_digest(path: str | None = None) -> str:
    catalog = load_catalog(path)
    lines = []
    for item in catalog.formulas:
        slot_names = ",".join(item.slots.keys()) or "none"
        lines.append(f"{item.id}: {item.description} (slots: {slot_names})")
    return "\n".join(lines)


def _assert_safe(expression: str) -> None:
    validate_expr(expression)


class CompiledLogic(BaseModel):
    catalog_id: str | None = None
    ast: str
    gate_ast: str | None = None
    shape: str = "per_row"
    mode: str = "calculation"
    output: str = "result"
    inputs: list[str] = Field(default_factory=list)
    constants: dict[str, Any] = Field(default_factory=dict)
    input_map: dict[str, str] = Field(default_factory=dict)
    group_by: list[str] = Field(default_factory=list)


def infer_logic_from_english(
    english: str, catalog: FormulaCatalog, config: dict[str, Any]
) -> CompiledLogic | None:
    item = _match_catalog_item(str(english), catalog, config)
    if item is None:
        return None
    constants = fill_slots_from_english(str(english), item, dict(config.get("constants") or {}))
    if config.get("threshold") is not None and "amount" in item.slots:
        constants.setdefault("amount", config["threshold"])
    return _logic_from_catalog(item, config, constants=constants)


def _match_catalog_item(
    english: str, catalog: FormulaCatalog, config: dict[str, Any]
) -> CatalogFormula | None:
    text = english.lower()
    best: CatalogFormula | None = None
    best_score = 0
    for item in catalog.formulas:
        score = sum(1 for alias in item.aliases if alias.lower() in text)
        if score > best_score:
            best = item
            best_score = score
    if best_score:
        return best
    shape = str(config.get("shape") or "").lower()
    constants = dict(config.get("constants") or {})
    if shape == "sequential":
        try:
            return catalog.get("running_balance")
        except KeyError:
            return None
    if config.get("threshold") is not None or ("pct" in constants and "amount" in constants):
        try:
            return catalog.get("min_pct_amount_tolerance")
        except KeyError:
            return None
    return None


def fill_slots_from_english(english: str, item: CatalogFormula, existing: dict[str, Any]) -> dict[str, Any]:
    out = dict(existing)
    compact = str(english).replace(",", "")
    if "pct" in item.slots and out.get("pct") in (None, ""):
        match = re.search(r"(\d+(?:\.\d+)?)\s*%", compact)
        if match:
            out["pct"] = float(match.group(1)) / 100.0
    if "amount" in item.slots and out.get("amount") in (None, ""):
        money = re.search(r"\$\s*(\d+(?:\.\d+)?)", compact)
        big = re.search(r"\b(\d{3,})(?:\.\d+)?\b", compact)
        if money:
            out["amount"] = float(money.group(1))
        elif big:
            out["amount"] = float(big.group(1))
        elif item.slots.get("amount", {}).get("default") is not None:
            out["amount"] = item.slots["amount"]["default"]
    for name, spec in item.slots.items():
        if out.get(name) in (None, "") and isinstance(spec, dict) and spec.get("default") is not None:
            out[name] = spec["default"]
    return out


def _logic_from_catalog(
    item: CatalogFormula,
    config: dict[str, Any],
    *,
    constants: dict[str, Any] | None = None,
    input_map: dict[str, str] | None = None,
) -> CompiledLogic:
    return CompiledLogic(
        catalog_id=item.id,
        ast=item.ast,
        gate_ast=item.gate_ast,
        shape=config.get("shape") or item.shape,
        mode=config.get("mode") or item.mode,
        output=config.get("output_column") or item.output,
        inputs=item.inputs,
        constants=dict(constants or config.get("constants") or {}),
        input_map=dict(input_map or config.get("input_map") or {}),
        group_by=list(config.get("group_by") or item.group_by or []),
    )


def _fallback_logic(catalog: FormulaCatalog, config: dict[str, Any]) -> CompiledLogic | None:
    return infer_logic_from_english(str(config.get("formula_en") or config.get("formula") or ""), catalog, config)


async def compile_logic(config: dict[str, Any], llm) -> CompiledLogic:
    catalog = load_catalog(config.get("catalog_path"))
    if config.get("ast"):
        _assert_safe(config["ast"])
        if config.get("gate_ast"):
            _assert_safe(config["gate_ast"])
        return CompiledLogic(
            catalog_id=config.get("catalog_id"),
            ast=config["ast"],
            gate_ast=config.get("gate_ast"),
            shape=config.get("shape") or "per_row",
            mode=config.get("mode") or "calculation",
            output=config.get("output_column") or config.get("output") or "result",
            inputs=list(config.get("inputs") or []),
            constants=dict(config.get("constants") or {}),
            input_map=dict(config.get("input_map") or {}),
            group_by=list(config.get("group_by") or []),
        )
    catalog_id = config.get("catalog_id")
    if catalog_id:
        try:
            item = catalog.get(str(catalog_id))
        except KeyError:
            item = None
        if item:
            constants = fill_slots_from_english(
                str(config.get("formula_en") or ""),
                item,
                dict(config.get("constants") or {}),
            )
            return _logic_from_catalog(item, config, constants=constants)
    english = config.get("formula_en") or config.get("formula")
    if not english:
        raise ValueError("math node needs catalog_id, ast, or formula_en")
    inferred = infer_logic_from_english(str(english), catalog, config)
    if inferred:
        return inferred
    prompt = (
        "Pick exactly one formula from this library. Do not invent an expression.\n"
        "Return catalog_id plus any constants and input_map you can fill from the user's words.\n"
        f"{catalog_digest(config.get('catalog_path'))}\n\n"
        f"User formula: {english}\n"
        f"Existing constants: {config.get('constants') or {}}\n"
        f"Existing input_map: {config.get('input_map') or {}}"
    )
    try:
        payload = await llm.complete_json("reasoning", prompt, SELECT_SCHEMA)
    except LLMError as exc:
        logger.warning("formula pick llm failed: %s", exc)
        fallback = _fallback_logic(catalog, config)
        if fallback:
            return fallback
        raise ValueError(
            "Math could not match this formula to the library. "
            "Confirm the agent again so Math saves a catalog formula, then Save."
        ) from None
    cid = str(payload.get("catalog_id") or "").strip()
    if cid not in catalog.ids():
        fallback = _fallback_logic(catalog, config)
        if fallback:
            return fallback
        raise ValueError(
            "Math could not match this formula to the library. "
            "Confirm the agent again so Math saves a catalog formula, then Save."
        )
    item = catalog.get(cid)
    constants = fill_slots_from_english(
        str(english),
        item,
        {**dict(config.get("constants") or {}), **dict(payload.get("constants") or {})},
    )
    input_map = {**dict(config.get("input_map") or {}), **dict(payload.get("input_map") or {})}
    return _logic_from_catalog(item, config, constants=constants, input_map=input_map)


def logic_to_config(value: dict[str, Any], logic: CompiledLogic) -> dict[str, Any]:
    out = dict(value)
    if logic.catalog_id:
        out["catalog_id"] = logic.catalog_id
    out["ast"] = logic.ast
    if logic.gate_ast:
        out["gate_ast"] = logic.gate_ast
    out["shape"] = logic.shape or out.get("shape") or "per_row"
    out["mode"] = logic.mode or out.get("mode") or "calculation"
    out["output_column"] = logic.output or out.get("output_column") or "result"
    constants = {**dict(out.get("constants") or {}), **dict(logic.constants or {})}
    if constants:
        out["constants"] = constants
    if logic.input_map:
        out["input_map"] = {**dict(out.get("input_map") or {}), **logic.input_map}
    if logic.group_by and not out.get("group_by"):
        out["group_by"] = logic.group_by
    source = str(out.get("formula_en") or out.get("catalog_id") or out.get("ast") or "")
    out["compiled_from"] = source
    return out


async def compile_math_value(value: dict[str, Any], llm) -> dict[str, Any]:
    source = str(value.get("formula_en") or value.get("catalog_id") or value.get("ast") or "")
    if not source:
        return value
    if value.get("compiled_from") == source and value.get("ast"):
        return value
    cfg = dict(value)
    if value.get("formula_en") and value.get("compiled_from") != source:
        cfg.pop("ast", None)
        cfg.pop("gate_ast", None)
    logic = await compile_logic(cfg, llm)
    return logic_to_config(value, logic)
