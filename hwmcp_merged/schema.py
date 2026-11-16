"""由函数签名生成 MCP 的 inputSchema。

上游用 FastMCP 自动生成 schema；这里不依赖 pydantic，只处理常见的
str / int / float / bool / list / dict / Optional / Union 组合。
"""

from __future__ import annotations

import inspect
import typing
from typing import Any, Callable


def _json_type(annotation: Any) -> dict[str, Any]:
    """把类型注解翻译成 JSON Schema 片段。无法判定时返回空 schema（任意值）。"""
    if annotation in (inspect.Parameter.empty, Any):
        return {}

    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)

    # Optional[X] / Union[...]
    if origin is typing.Union:
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return _json_type(non_none[0])
        return {}  # 多分支联合：交给调用方传原始结构

    if origin in (list, set, tuple):
        item = _json_type(args[0]) if args else {}
        out: dict[str, Any] = {"type": "array"}
        if item:
            out["items"] = item
        return out

    if origin is dict:
        return {"type": "object"}

    mapping = {str: "string", int: "integer", float: "number", bool: "boolean",
               dict: "object", list: "array"}
    if annotation in mapping:
        return {"type": mapping[annotation]}

    # 字符串形式注解（上游用了 from __future__ import annotations）
    if isinstance(annotation, str):
        text = annotation.strip()
        if text.startswith("list[") or text.startswith("List["):
            return {"type": "array"}
        if text.startswith("dict[") or text.startswith("Dict["):
            return {"type": "object"}
        for key, jt in (("str", "string"), ("int", "integer"),
                        ("float", "number"), ("bool", "boolean")):
            if text == key:
                return {"type": jt}
        return {}

    return {}


def build_input_schema(fn: Callable[..., Any]) -> dict[str, Any]:
    signature = inspect.signature(fn)
    try:
        hints = typing.get_type_hints(fn)
    except Exception:  # noqa: BLE001 - 解析失败就退回字符串注解
        hints = {}

    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, param in signature.parameters.items():
        if name in ("self", "cls") or param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        fragment = _json_type(hints.get(name, param.annotation))
        if param.default is inspect.Parameter.empty:
            required.append(name)
        elif param.default is not None:
            fragment = {**fragment, "default": param.default}
        properties[name] = fragment

    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def first_doc_line(fn: Callable[..., Any]) -> str:
    doc = inspect.getdoc(fn) or ""
    for line in doc.splitlines():
        line = line.strip()
        if line:
            return line
    return fn.__name__


def accepts(fn: Callable[..., Any], kwargs: dict[str, Any]) -> tuple[bool, str]:
    """判断 kwargs 是否与该函数签名匹配，返回 (是否可调, 错误说明)。"""
    params = inspect.signature(fn).parameters
    allowed = {n for n, p in params.items()
               if p.kind not in (inspect.Parameter.VAR_KEYWORD,)}
    unknown = set(kwargs) - allowed
    if unknown:
        return False, f"未知参数：{sorted(unknown)}；可接受：{sorted(allowed)}"
    missing = [n for n, p in params.items()
               if p.default is inspect.Parameter.empty
               and p.kind not in (inspect.Parameter.VAR_POSITIONAL,
                                  inspect.Parameter.VAR_KEYWORD)
               and n not in kwargs]
    if missing:
        return False, f"缺少必填参数：{missing}"
    return True, ""
