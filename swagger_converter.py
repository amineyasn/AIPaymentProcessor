"""
Converts the FastAPI OpenAPI 3.0 spec to a strict Swagger 2.0 spec.
Fixes all Azure API Management / Copilot Studio validation errors:

  1. anyOf in query/path parameters  -> flatten to concrete type
  2. anyOf in definitions (Optional)  -> flatten to concrete type
  3. Duplicate tags on operations     -> deduplicated
  4. multipart/form-data with $ref    -> resolved inline
"""

from __future__ import annotations
from urllib.parse import urlparse
from typing import Any


def _ref_30_to_20(ref: str) -> str:
    return ref.replace("#/components/schemas/", "#/definitions/")


def _flatten_anyof(branches: list) -> dict:
    non_null = [b for b in branches if b.get("type") != "null" and b != {"type": "null"}]
    if len(non_null) == 1:
        return non_null[0]
    if non_null:
        return non_null[0]
    return {"type": "string"}


def _convert_schema(schema: Any) -> Any:
    if not isinstance(schema, dict):
        return schema

    if "anyOf" in schema and "$ref" not in schema and "type" not in schema:
        flat = _flatten_anyof(schema["anyOf"])
        merged = {k: v for k, v in schema.items() if k != "anyOf"}
        merged.update(flat)
        return _convert_schema(merged)

    out: dict = {}
    for k, v in schema.items():
        if k == "$ref":
            out["$ref"] = _ref_30_to_20(v)
        elif k in ("nullable", "discriminator", "externalDocs"):
            pass
        elif k in ("anyOf", "oneOf"):
            flat = _flatten_anyof([_convert_schema(s) for s in v])
            out.update(flat)
        elif k == "items":
            out["items"] = _convert_schema(v)
        elif isinstance(v, dict):
            out[k] = _convert_schema(v)
        elif isinstance(v, list):
            out[k] = [_convert_schema(i) if isinstance(i, dict) else i for i in v]
        else:
            out[k] = v
    return out


def _extract_definitions(components: dict) -> dict:
    return {
        name: _convert_schema(schema)
        for name, schema in components.get("schemas", {}).items()
    }


def _convert_parameter(p: dict) -> dict:
    np = {k: v for k, v in p.items() if k not in ("schema", "content", "style", "explode")}
    raw_schema = p.get("schema", {})
    converted = _convert_schema(raw_schema)

    for key in ("type", "format", "enum", "default", "minimum", "maximum",
                "minLength", "maxLength", "pattern", "items"):
        if key in converted:
            np[key] = converted[key]

    if "$ref" in converted:
        np["type"] = "string"

    if "type" not in np and "$ref" not in np:
        np["type"] = "string"

    if "required" not in np:
        np["required"] = np.get("in") == "path"

    return np


def _convert_parameters(parameters: list) -> list:
    return [_convert_parameter(p) for p in parameters]


def _convert_request_body(request_body: dict, all_schemas: dict):
    def resolve(schema):
        if "$ref" in schema:
            name = schema["$ref"].replace("#/components/schemas/", "")
            return all_schemas.get(name, schema)
        return schema

    content = request_body.get("content", {})
    required = request_body.get("required", False)
    params, consumes = [], []

    if "multipart/form-data" in content:
        consumes = ["multipart/form-data"]
        raw = content["multipart/form-data"].get("schema", {})
        schema = resolve(raw)
        properties = schema.get("properties", {})
        req_fields = schema.get("required", [])

        for prop_name, prop_schema in properties.items():
            prop_schema = resolve(prop_schema)
            if "anyOf" in prop_schema:
                prop_schema = _flatten_anyof(prop_schema["anyOf"])
            param = {
                "name": prop_name,
                "in": "formData",
                "required": prop_name in req_fields,
            }
            typ = prop_schema.get("type", "string")
            fmt = prop_schema.get("format", "")
            if typ == "string" and fmt == "binary":
                param["type"] = "file"
            else:
                param["type"] = typ
                if fmt:
                    param["format"] = fmt
            params.append(param)

    elif "application/json" in content:
        consumes = ["application/json"]
        schema = content["application/json"].get("schema", {})
        params.append({
            "name": "body",
            "in": "body",
            "required": required,
            "schema": _convert_schema(schema),
        })

    return params, consumes


def _convert_responses(responses: dict) -> dict:
    out = {}
    for status, resp in responses.items():
        nr = {"description": resp.get("description", "")}
        content = resp.get("content", {})
        if "application/json" in content:
            schema = content["application/json"].get("schema", {})
            nr["schema"] = _convert_schema(schema)
        out[str(status)] = nr
    return out


def convert_to_swagger2(openapi3: dict) -> dict:
    info = openapi3.get("info", {})
    servers = openapi3.get("servers", [])
    host, base_path, schemes = "localhost", "/", ["https"]
    if servers:
        parsed = urlparse(servers[0]["url"])
        host = parsed.netloc or "localhost"
        base_path = parsed.path or "/"
        schemes = [parsed.scheme] if parsed.scheme else ["https"]

    swagger: dict = {
        "swagger": "2.0",
        "info": {
            "title":       info.get("title", "API"),
            "description": info.get("description", ""),
            "version":     info.get("version", "1.0.0"),
        },
        "host":     host,
        "basePath": base_path,
        "schemes":  schemes,
        "consumes": ["application/json"],
        "produces": ["application/json"],
        "paths":       {},
        "definitions": {},
    }

    components  = openapi3.get("components", {})
    all_schemas = components.get("schemas", {})
    swagger["definitions"] = _extract_definitions(components)

    for path, path_item in openapi3.get("paths", {}).items():
        swagger["paths"][path] = {}
        for method, operation in path_item.items():
            if method not in ("get", "post", "put", "patch", "delete", "head", "options"):
                continue

            # Deduplicate tags — fixes APIM "Non-unique array item" error
            unique_tags = list(dict.fromkeys(operation.get("tags", [])))

            op: dict = {
                "operationId": operation.get("operationId", f"{method}_{path}"),
                "summary":     operation.get("summary", ""),
                "description": operation.get("description", ""),
                "tags":        unique_tags,
                "parameters":  [],
                "responses":   _convert_responses(operation.get("responses", {})),
            }

            op["parameters"].extend(
                _convert_parameters(operation.get("parameters", []))
            )

            if "requestBody" in operation:
                body_params, consumes = _convert_request_body(
                    operation["requestBody"], all_schemas
                )
                op["parameters"].extend(body_params)
                if consumes:
                    op["consumes"] = consumes

            swagger["paths"][path][method] = op

    return swagger
