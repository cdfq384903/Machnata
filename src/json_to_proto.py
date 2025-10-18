#!/usr/bin/env python3
import json
import os
import sys
import re
from collections import defaultdict

# ---- Default Go import base (可改成 CLI 第三參數) ----
DEFAULT_GO_IMPORT_BASE = "tmp"

# 避免重複產出
EMITTED = set()

# 全域：型別在哪個 group 檔（不含副檔名）
# 例如 {"Extension": "Element", "Reference": "CodeableReference"}
DEF_TO_GROUP = {}


# ---------------- Helpers ----------------
def sanitize_ident(name: str) -> str:
    name = re.sub(r"\W+", "_", str(name))
    if re.match(r"^\d", name):
        name = "_" + name
    return name


def pb_primitive(json_type: str) -> str:
    return {
        "string": "string",
        "integer": "int32",
        "boolean": "bool",
        "number": "double",
    }.get(json_type, "string")


def add_import(imports: set, path: str):
    if path:
        imports.add(path)


def add_import_guarded(imports: set, imp_path: str, self_path: str):
    """避免同檔 import 自己"""
    if imp_path and os.path.normpath(imp_path) != os.path.normpath(self_path):
        imports.add(imp_path)


def detect_version_from_output_dir(output_dir: str) -> str:
    base = os.path.basename(os.path.normpath(output_dir))
    return sanitize_ident(base)


def detect_schema_type_from_input_dir(input_dir: str) -> str:
    parent = os.path.dirname(os.path.normpath(input_dir))
    base = os.path.basename(parent)
    return sanitize_ident(base)


def normalize_type(t):
    if isinstance(t, list):
        for cand in t:
            if cand != "null":
                return cand
        return t[0]
    return t


def unwrap_nullable(schema: dict) -> dict:
    if not isinstance(schema, dict):
        return schema
    if "anyOf" in schema and isinstance(schema["anyOf"], list):
        non_null = [s for s in schema["anyOf"] if s.get("type") != "null"]
        if len(non_null) == 1:
            return non_null[0]
    if "oneOf" in schema and isinstance(schema["oneOf"], list):
        non_null = [s for s in schema["oneOf"] if s.get("type") != "null"]
        if len(non_null) == 1:
            return non_null[0]
    return schema


def make_child_typename(parent: str, prop: str, suffix: str = "") -> str:
    base = f"{sanitize_ident(parent)}_{sanitize_ident(prop)}"
    return (base + ("_" + suffix if suffix else "")).strip("_")


def resolve_json_pointer(doc: dict, pointer: str) -> dict:
    if not pointer.startswith("#/"):
        return {}
    parts = pointer[2:].split("/")
    node = doc
    for p in parts:
        p = p.replace("~1", "/").replace("~0", "~")
        if isinstance(node, list):
            try:
                idx = int(p)
                node = node[idx]
            except Exception:
                return {}
        else:
            node = node.get(p, {})
    return node


def path_to_suffix(path: str) -> str:
    parts = [x for x in path.split("/") if x and x not in ("#",)]
    return sanitize_ident("_".join(parts))


def remove_stale_enum_files(output_dir: str, registry: dict):
    """把舊版遺留在 types/ 底下、實際上應該在 types/enums/ 的 enum 檔刪掉"""
    types_dir = os.path.join(output_dir, "types")
    if not os.path.isdir(types_dir):
        return
    enum_names = {name for name, kind in registry.items() if kind == "enum"}
    for enum_name in enum_names:
        stale = os.path.join(types_dir, f"{sanitize_ident(enum_name)}.proto")
        if os.path.isfile(stale):
            try:
                os.remove(stale)
                print(f"[clean] removed stale enum file: {stale}")
            except Exception as e:
                print(f"[warn] failed to remove {stale}: {e}")
    # 確保 enums 目錄存在
    os.makedirs(os.path.join(types_dir, "enums"), exist_ok=True)


# ---------------- Graph & Registry ----------------
def collect_direct_definition_refs(def_schema: dict) -> set:
    """抓出此 definition 直接參照的 other definitions（僅限 #/definitions/<Name> 不含子路徑）"""
    out = set()

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                ref = node["$ref"]
                if isinstance(ref, str) and ref.startswith("#/definitions/"):
                    parts = ref.split("/")
                    if len(parts) == 3:  # #/definitions/Foo
                        out.add(sanitize_ident(parts[2]))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(def_schema)
    return out


def build_registry_and_graph(input_dir):
    """回傳：
    - registry: name -> "enum"|"message"
    - defs_per_file: filename -> (full_schema, definitions_dict)
    - dep_graph: def_name -> set(dep_def_names)（全域）
    """
    registry = {}
    defs_per_file = {}
    dep_graph = defaultdict(set)

    for fn in os.listdir(input_dir):
        if not fn.endswith(".json"):
            continue
        full_path = os.path.join(input_dir, fn)
        with open(full_path, encoding="utf-8") as f:
            schema = json.load(f)
        defs = schema.get("definitions", {})
        defs_per_file[fn] = (schema, defs)

        for def_name, def_schema in defs.items():
            name = sanitize_ident(def_name)
            kind = "enum" if "enum" in def_schema else "message"
            registry.setdefault(name, kind)

        # 建立依賴
        for def_name, def_schema in defs.items():
            name = sanitize_ident(def_name)
            for dep in collect_direct_definition_refs(def_schema):
                if dep != name:
                    dep_graph[name].add(dep)

    return registry, defs_per_file, dep_graph


# Tarjan SCC（local）- 仍保留以備需要，但不再用來分檔
# 在 Tarjan 內部，遍歷鄰居時改為 排序後再走。
# 在 Tarjan 外部，對節點清單用 排序。
# 決定 group 檔名時，不要用 comp[0]，而是用 字典序最小的名稱 min(comp)（或 sorted(comp)[0]）。兩個地方都要改：
# 第一次建立 DEF_TO_GROUP 與 GROUP_OWNER
# 第二次實際產生 group 檔
def scc_tarjan(nodes, edges):
    """edges: dict node -> set(nei). 回傳 list of components(list of nodes)"""
    index = 0
    indices = {}
    lowlink = {}
    onstack = set()
    stack = []
    comps = []

    def strongconnect(v):
        nonlocal index
        indices[v] = index
        lowlink[v] = index
        index += 1
        stack.append(v)
        onstack.add(v)

        for w in sorted(edges.get(v, [])):
            if w not in indices:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif w in onstack:
                lowlink[v] = min(lowlink[v], indices[w])

        if lowlink[v] == indices[v]:
            comp = []
            while True:
                w = stack.pop()
                onstack.discard(w)
                comp.append(w)
                if w == v:
                    break
            comps.append(comp)

    for v in sorted(nodes):
        if v not in indices:
            strongconnect(v)
    return comps


# ---------------- Emit for inline synthetic types ----------------
def generate_inline_file(
    def_name,
    def_schema,
    output_dir,
    pkg_types,
    pkg_enums,
    go_import_base_versioned,
    registry: dict,
):
    """僅用於子路徑/inline 產生的臨時型別：單檔一型別（避免太複雜）"""
    def_name = sanitize_ident(def_name)
    is_enum = "enum" in def_schema

    if is_enum:
        subdir = os.path.join(output_dir, "types", "enums")
        os.makedirs(subdir, exist_ok=True)
        pkg = f"{pkg_enums}.{def_name.lower()}"
        go_import = f"{go_import_base_versioned}/types/enums"
        go_pkg = "enums"
    else:
        subdir = os.path.join(output_dir, "types")
        os.makedirs(subdir, exist_ok=True)
        pkg = pkg_types
        go_import = f"{go_import_base_versioned}/types"
        go_pkg = "types"

    imports = set()
    lines = []
    lines.append('syntax = "proto3";')
    lines.append(f"package {pkg};")
    lines.append(f'option go_package = "{go_import};{go_pkg}";')
    lines.append(f'option csharp_namespace = "{pkg_enums if is_enum else pkg_types}";')

    if is_enum:
        lines.append("")
        lines.append(f"enum {def_name} {{")
        lines.append(f"  {def_name.upper()}_UNSPECIFIED = 0;")
        seen = {f"{def_name.upper()}_UNSPECIFIED"}
        for i, ev in enumerate(def_schema.get("enum", []), start=1):
            const = sanitize_ident(ev)
            if const in seen:
                const = f"{const}_{i}"
            seen.add(const)
            lines.append(f"  {const} = {i};")
        lines.append("}")
    else:
        # message
        body_lines, import_set = generate_message_body(
            def_name=def_name,
            def_schema=def_schema,
            pkg_types=pkg_types,
            pkg_enums=pkg_enums,
            go_import_base_versioned=go_import_base_versioned,
            output_dir=output_dir,
            current_group_filename=def_name,  # 當作各自一檔
            registry=registry,
        )
        imports |= import_set
        if imports:
            lines.append("")
            for imp in sorted(imports):
                lines.append(f'import "{imp}";')

        lines.append("")
        lines.append(f"message {def_name} {{")
        lines.extend(body_lines)
        lines.append("}")

    out_path = os.path.join(subdir, f"{def_name}.proto")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Generated {out_path}")


# ---------------- Core: 生成 message 本體（不含 header/import/結尾） ----------------
def ensure_inline_type_for_ref(
    full_schema_doc: dict,
    parent_typename: str,
    ref: str,
    output_dir: str,
    registry: dict,
    pkg_types: str,
    pkg_enums: str,
    go_import_base_versioned: str,
    current_group_filename: str,
):
    """回傳 (qualified_type, import_path_or_None)"""
    if not ref.startswith("#/"):
        return ("string", None)

    parts = ref[2:].split("/")
    if len(parts) < 2 or parts[0] != "definitions":
        # 非 definitions 指標 → 解析指標；物件/enum 走 inline，primitive 回傳對應型別
        target_schema = resolve_json_pointer(full_schema_doc, ref)
        if not isinstance(target_schema, dict):
            return ("string", None)
        suffix = path_to_suffix(ref[1:])
        typename = make_child_typename(parent_typename, suffix)
        key = (
            (
                "msg"
                if "properties" in target_schema
                else "enum" if "enum" in target_schema else "prim"
            ),
            typename,
        )
        if key not in EMITTED:
            generate_inline_file(
                typename,
                (
                    target_schema
                    if "enum" in target_schema or "properties" in target_schema
                    else {"properties": {}}
                ),
                output_dir,
                pkg_types,
                pkg_enums,
                go_import_base_versioned,
                registry,
            )
            EMITTED.add(key)
        if "enum" in target_schema:
            return (
                f"{pkg_enums}.{typename.lower()}.{typename}",
                f"types/enums/{typename}.proto",
            )
        elif "properties" in target_schema:
            return (f"{pkg_types}.{typename}", f"types/{typename}.proto")
        else:
            t = target_schema.get("type", "string")
            return (pb_primitive(normalize_type(t)), None)

    # 開頭為 #/definitions
    base_def = sanitize_ident(parts[1])
    sub_path = "/".join(parts[2:])

    if not sub_path:
        # 直接指到某 definition：只做「引用+import」，絕不 inline 產生
        kind = registry.get(base_def)  # << 需要知道是不是 enum
        target_group_file = DEF_TO_GROUP.get(base_def)
        imp_path = None
        if kind == "enum":
            # definitions 等級的 enum：指向 enums 套件與路徑
            imp_path = f"types/enums/{base_def}.proto"
            return (f"{pkg_enums}.{base_def.lower()}.{base_def}", imp_path)
        else:
            # 其餘維持原本 types/<group>.proto
            if target_group_file and target_group_file != current_group_filename:
                imp_path = f"types/{target_group_file}.proto"
            if not target_group_file:
                print(f"[warn] No owner group for {base_def}; check input scan.")
            return (f"{pkg_types}.{base_def}", imp_path)

    # 指到 definition 的子路徑：這才允許 inline
    key_for_doc = parts[1]
    defs = full_schema_doc.get("definitions", {})
    if key_for_doc not in defs:
        alt = sanitize_ident(key_for_doc)
        if alt in defs:
            key_for_doc = alt

    pointer = f"#/definitions/{key_for_doc}/{sub_path}"
    target_schema = resolve_json_pointer(full_schema_doc, pointer)
    if not isinstance(target_schema, dict):
        return ("string", None)

    typename = make_child_typename(base_def, path_to_suffix(sub_path))
    key = (
        (
            "enum"
            if "enum" in target_schema
            else "msg" if "properties" in target_schema else "prim"
        ),
        typename,
    )
    if key not in EMITTED:
        generate_inline_file(
            typename,
            (
                target_schema
                if "enum" in target_schema or "properties" in target_schema
                else {"properties": {}}
            ),
            output_dir,
            pkg_types,
            pkg_enums,
            go_import_base_versioned,
            registry,
        )
        EMITTED.add(key)

    if "enum" in target_schema:
        return (
            f"{pkg_enums}.{typename.lower()}.{typename}",
            f"types/enums/{typename}.proto",
        )
    elif "properties" in target_schema:
        return (f"{pkg_types}.{typename}", f"types/{typename}.proto")
    else:
        t = target_schema.get("type", "string")
        return (pb_primitive(normalize_type(t)), None)


def generate_message_body(
    def_name: str,
    def_schema: dict,
    pkg_types: str,
    pkg_enums: str,
    go_import_base_versioned: str,
    output_dir: str,
    current_group_filename: str,
    registry: dict,
):
    """回傳 (lines:list[str], imports:set[str])，僅 message 內容（fields）"""
    lines = []
    imports = set()
    field_no = 1
    props = def_schema.get("properties", {})

    for p_name, p_schema in props.items():
        p_schema = unwrap_nullable(p_schema)
        p_out_json_key = str(p_name)  # 原始 JSON key（可能是 "_value"）
        p_out_proto = sanitize_ident(p_name)  # 先用 sanitize 後的 proto 欄位名

        # 若原始 JSON key 以 "_" 開頭，改用不會撞 camelCase 的 proto 欄位名
        needs_shadow = isinstance(p_name, str) and p_name.startswith("_")
        if needs_shadow:
            base = p_out_proto.lstrip("_")
            if not base:
                base = "field"
            p_out_proto = f"shadow__{base}"

        ty = "string"
        is_arr = False

        if p_schema.get("type") == "array":
            is_arr = True
            items = unwrap_nullable(p_schema.get("items", {}))
            if "type" in items:
                if items["type"] == "object" and "properties" in items:
                    child_name = make_child_typename(def_name, p_out_proto, "item")
                    key = ("msg", child_name)
                    if key not in EMITTED:
                        generate_inline_file(
                            child_name,
                            items,
                            output_dir,
                            pkg_types,
                            pkg_enums,
                            go_import_base_versioned,
                            registry,
                        )
                        EMITTED.add(key)
                    ty = f"{pkg_types}.{child_name}"
                    add_import(imports, f"types/{child_name}.proto")
                else:
                    ty = pb_primitive(normalize_type(items["type"]))
            elif "$ref" in items:
                ty, imp = ensure_inline_type_for_ref(
                    full_schema_doc={"definitions": {def_name: def_schema}},
                    parent_typename=def_name,
                    ref=items["$ref"],
                    output_dir=output_dir,
                    registry=registry,
                    pkg_types=pkg_types,
                    pkg_enums=pkg_enums,
                    go_import_base_versioned=go_import_base_versioned,
                    current_group_filename=current_group_filename,
                )
                if imp:
                    add_import(imports, imp)
            elif "enum" in items:
                enum_name = make_child_typename(def_name, p_out_proto, "item_enum")
                key = ("enum", enum_name)
                if key not in EMITTED:
                    generate_inline_file(
                        enum_name,
                        {"enum": items["enum"]},
                        output_dir,
                        pkg_types,
                        pkg_enums,
                        go_import_base_versioned,
                        registry,
                    )
                    EMITTED.add(key)
                ty = f"{pkg_enums}.{enum_name.lower()}.{enum_name}"
                add_import(imports, f"types/enums/{enum_name}.proto")
            else:
                ty = "string"
        elif "$ref" in p_schema:
            ty, imp = ensure_inline_type_for_ref(
                full_schema_doc={"definitions": {def_name: def_schema}},
                parent_typename=def_name,
                ref=p_schema["$ref"],
                output_dir=output_dir,
                registry=registry,
                pkg_types=pkg_types,
                pkg_enums=pkg_enums,
                go_import_base_versioned=go_import_base_versioned,
                current_group_filename=current_group_filename,
            )
            if imp:
                add_import(imports, imp)
        elif "enum" in p_schema:
            enum_name = make_child_typename(def_name, p_out_proto, "enum")
            key = ("enum", enum_name)
            if key not in EMITTED:
                generate_inline_file(
                    enum_name,
                    {"enum": p_schema["enum"]},
                    output_dir,
                    pkg_types,
                    pkg_enums,
                    go_import_base_versioned,
                    registry,
                )
                EMITTED.add(key)
            ty = f"{pkg_enums}.{enum_name.lower()}.{enum_name}"
            add_import(imports, f"types/enums/{enum_name}.proto")
        elif p_schema.get("type") == "object" and "properties" in p_schema:
            child_name = make_child_typename(def_name, p_out_proto)
            key = ("msg", child_name)
            if key not in EMITTED:
                generate_inline_file(
                    child_name,
                    p_schema,
                    output_dir,
                    pkg_types,
                    pkg_enums,
                    go_import_base_versioned,
                    registry,
                )
                EMITTED.add(key)
            ty = f"{pkg_types}.{child_name}"
            add_import(imports, f"types/{child_name}.proto")
        elif "type" in p_schema:
            ty = pb_primitive(normalize_type(p_schema["type"]))
        else:
            ty = "string"

        if is_arr:
            ty = f"repeated {ty}"

        # 設定 json_name（只有 shadow 欄位才需要）
        json_name_opt = ""
        if needs_shadow:
            json_name_opt = f' [json_name = "{p_out_json_key}"]'

        lines.append(f"  {ty} {p_out_proto} = {field_no}{json_name_opt};")
        field_no += 1

    return lines, imports


# ---------------- Group emitter ----------------
def generate_group_proto(
    group_filename: str,
    defs_in_group,  # list[(def_name_sanitized, def_schema)]
    output_dir: str,
    registry: dict,
    pkg_types: str,
    pkg_enums: str,
    go_import_base_versioned: str,
):
    """把同一個 JSON 檔的 definitions 合成一個 types/<group>.proto"""
    subdir = os.path.join(output_dir, "types")
    os.makedirs(subdir, exist_ok=True)
    pkg = pkg_types
    go_import = f"{go_import_base_versioned}/types"
    go_pkg = "types"

    imports = set()
    lines = []
    lines.append('syntax = "proto3";')
    lines.append(f"package {pkg};")
    lines.append(f'option go_package = "{go_import};{go_pkg}";')
    lines.append(f'option csharp_namespace = "{pkg_types}";')
    lines.append("")

    # 收集各 message/enum 區塊
    blocks = []
    emitted_names = set()

    for def_name, def_schema in defs_in_group:
        def_name = sanitize_ident(def_name)
        if def_name in emitted_names:
            continue
        emitted_names.add(def_name)

        if "enum" in def_schema:
            # 產生 types/enums/<EnumName>.proto（避免重複）
            key = ("enum", def_name)
            if key not in EMITTED:
                generate_inline_file(
                    def_name,
                    def_schema,  # 這個 dict 裡有 "enum": [...]
                    output_dir,
                    pkg_types,
                    pkg_enums,
                    go_import_base_versioned,
                    registry,
                )
                EMITTED.add(key)
            continue

        body_lines, import_set = generate_message_body(
            def_name=def_name,
            def_schema=def_schema,
            pkg_types=pkg_types,
            pkg_enums=pkg_enums,
            go_import_base_versioned=go_import_base_versioned,
            output_dir=output_dir,
            current_group_filename=group_filename,
            registry=registry,
        )
        imports |= import_set

        block = []
        block.append(f"message {def_name} {{")
        block.extend(body_lines)
        block.append("}")
        block.append("")  # 空行分隔
        blocks.append("\n".join(block))

    # 輸出 imports（避免自我 import）
    for imp in sorted(imports):
        if os.path.normpath(imp) != os.path.normpath(f"types/{group_filename}.proto"):
            lines.append(f'import "{imp}";')

    # 若沒有任何 message（只有 enums），就不要產生 types/<group>.proto
    if not blocks:
        return

    lines.append("")
    lines.extend(blocks)

    out_path = os.path.join(subdir, f"{group_filename}.proto")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Generated {out_path}")


# ---------------- Top-level schema emitter ----------------
def generate_schema_proto(
    schema_name,
    schema,
    output_dir,
    registry,
    pkg_schemas,
    pkg_types,
    pkg_enums,
    go_import_base_versioned,
    go_pkg_schemas,
):
    os.makedirs(output_dir, exist_ok=True)

    pkg = pkg_schemas
    go_import = f"{go_import_base_versioned}"
    go_pkg = go_pkg_schemas

    imports = set()

    lines = []
    lines.append('syntax = "proto3";')
    lines.append(f"package {pkg};")
    lines.append(f'option go_package = "{go_import};{go_pkg}";')
    lines.append(f'option csharp_namespace = "{pkg_schemas}";')

    top = sanitize_ident(schema_name)
    lines.append("")

    # 如果整檔 schema 用 $ref 指到某個 definition，就把它展成該 definition 的 properties
    main_schema = schema
    if "$ref" in schema and schema.get("definitions"):
        ref_path = schema["$ref"].split("/")
        if len(ref_path) == 3 and ref_path[1] == "definitions":
            def_key = ref_path[2]  # 直接用原始 JSON key
            main_schema = schema["definitions"].get(def_key, schema)

    if "$ref" in schema and not main_schema.get("properties"):
        print(
            f"[warn] {schema_name}: $ref points to definition without properties; check key sanitization."
        )

    body = []
    body.append(f"message {top} {{")
    field_no = 1
    props = main_schema.get("properties", {})
    required = set(main_schema.get("required", []))

    for p_name, p_schema in props.items():
        p_schema = unwrap_nullable(p_schema)
        p_out_json_key = str(p_name)
        p_out_proto = sanitize_ident(p_name)

        needs_shadow = isinstance(p_name, str) and p_name.startswith("_")
        if needs_shadow:
            base = p_out_proto.lstrip("_")
            if not base:
                base = "field"
            p_out_proto = f"shadow__{base}"

        ty = "string"
        is_arr = False

        if p_schema.get("type") == "array":
            is_arr = True
            items = unwrap_nullable(p_schema.get("items", {}))
            if "type" in items:
                if items["type"] == "object" and "properties" in items:
                    child_name = make_child_typename(top, p_out_proto, "item")
                    key = ("msg", child_name)
                    if key not in EMITTED:
                        generate_inline_file(
                            child_name,
                            items,
                            output_dir,
                            pkg_types,
                            pkg_enums,
                            go_import_base_versioned,
                            registry,
                        )
                        EMITTED.add(key)
                    ty = f"{pkg_types}.{child_name}"
                    add_import(imports, f"types/{child_name}.proto")
                else:
                    ty = pb_primitive(normalize_type(items["type"]))
            elif "$ref" in items:
                ref = items["$ref"]
                if ref.startswith("#/definitions/"):
                    base_def = sanitize_ident(ref.split("/")[2])
                    if registry.get(base_def) == "enum":
                        ty = f"{pkg_enums}.{base_def.lower()}.{base_def}"
                        add_import(imports, f"types/enums/{base_def}.proto")
                    else:
                        group_file = DEF_TO_GROUP.get(base_def, base_def)
                        ty = f"{pkg_types}.{base_def}"
                        add_import(imports, f"types/{group_file}.proto")
                else:
                    ty = "string"
            elif "enum" in items:
                enum_name = make_child_typename(top, p_out_proto, "item_enum")
                key = ("enum", enum_name)
                if key not in EMITTED:
                    generate_inline_file(
                        enum_name,
                        {"enum": items["enum"]},
                        output_dir,
                        pkg_types,
                        pkg_enums,
                        go_import_base_versioned,
                        registry,
                    )
                    EMITTED.add(key)
                ty = f"{pkg_enums}.{enum_name.lower()}.{enum_name}"
                add_import(imports, f"types/enums/{enum_name}.proto")
            else:
                ty = "string"

        elif "$ref" in p_schema:
            ref = p_schema["$ref"]
            if ref.startswith("#/definitions/"):
                base_def = sanitize_ident(ref.split("/")[2])
                if registry.get(base_def) == "enum":
                    ty = f"{pkg_enums}.{base_def.lower()}.{base_def}"
                    add_import(imports, f"types/enums/{base_def}.proto")
                else:
                    group_file = DEF_TO_GROUP.get(base_def, base_def)
                    ty = f"{pkg_types}.{base_def}"
                    add_import(imports, f"types/{group_file}.proto")
            else:
                ty, imp = ensure_inline_type_for_ref(
                    full_schema_doc=schema,
                    parent_typename=top,
                    ref=ref,
                    output_dir=output_dir,
                    registry=registry,
                    pkg_types=pkg_types,
                    pkg_enums=pkg_enums,
                    go_import_base_versioned=go_import_base_versioned,
                    current_group_filename=DEF_TO_GROUP.get(top, top),
                )
                if imp:
                    add_import(imports, imp)

        elif "enum" in p_schema:
            enum_name = make_child_typename(top, p_out_proto, "enum")
            key = ("enum", enum_name)
            if key not in EMITTED:
                generate_inline_file(
                    enum_name,
                    {"enum": p_schema["enum"]},
                    output_dir,
                    pkg_types,
                    pkg_enums,
                    go_import_base_versioned,
                    registry,
                )
            EMITTED.add(key)
            ty = f"{pkg_enums}.{enum_name.lower()}.{enum_name}"
            add_import(imports, f"types/enums/{enum_name}.proto")

        elif p_schema.get("type") == "object" and "properties" in p_schema:
            child_name = make_child_typename(top, p_out_proto)
            key = ("msg", child_name)
            if key not in EMITTED:
                generate_inline_file(
                    child_name,
                    p_schema,
                    output_dir,
                    pkg_types,
                    pkg_enums,
                    go_import_base_versioned,
                    registry,
                )
                EMITTED.add(key)
            ty = f"{pkg_types}.{child_name}"
            add_import(imports, f"types/{child_name}.proto")

        elif "type" in p_schema:
            ty = pb_primitive(normalize_type(p_schema["type"]))
        else:
            ty = "string"

        if is_arr:
            ty = f"repeated {ty}"

        json_name_opt = ""
        if needs_shadow:
            json_name_opt = f' [json_name = "{p_out_json_key}"]'

        if p_out_proto in required:
            body.append("  // NOTE: This field is required by standard Spec.")
        body.append(f"  {ty} {p_out_proto} = {field_no}{json_name_opt};")
        field_no += 1

    body.append("}")

    # imports
    for imp in sorted(imports):
        lines.append(f'import "{imp}";')

    lines.append("")
    lines.extend(body)

    out_path = os.path.join(output_dir, f"{schema_name}.proto")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Generated {out_path}")


# ---------------- Driver ----------------
def process_directory(input_dir, output_dir, go_import_base=DEFAULT_GO_IMPORT_BASE):
    os.makedirs(output_dir, exist_ok=True)

    pkg_schema_type = detect_schema_type_from_input_dir(input_dir)  # e.g., "HL7"
    version_name = detect_version_from_output_dir(output_dir)  # e.g., "v600"
    pkg_schemas = f"{pkg_schema_type}.{version_name}"
    pkg_types = f"{pkg_schemas}.types"
    pkg_enums = f"{pkg_types}.enums"

    go_import_base_versioned = f"{go_import_base}/{version_name}"
    go_pkg_schemas = f"{pkg_schema_type}{version_name}"  # e.g., HL7v600

    # 1) registry + per-file defs + 全域依賴圖
    registry, defs_per_file, dep_graph = build_registry_and_graph(input_dir)
    remove_stale_enum_files(output_dir, registry)

    # 2) 以「每個檔」做 SCC：把每個 definition 指到它所在 SCC 的第一個成員（group 檔名）
    global DEF_TO_GROUP
    DEF_TO_GROUP = {}

    # 同名 group 檔若出現在多個 JSON，只讓第一個檔來產生
    GROUP_OWNER = {}  # group_head -> owner_filename(base, sanitized)

    for filename in sorted(defs_per_file.keys()):  # 排序確保穩定
        schema, defs = defs_per_file[filename]
        if not defs:
            continue
        local_nodes = sorted(sanitize_ident(n) for n in defs.keys())
        if not local_nodes:
            continue
        local_edges = {n: set() for n in local_nodes}
        for n in local_nodes:
            local_edges[n] = set(
                [m for m in dep_graph.get(n, set()) if m in local_nodes]
            )

        comps = scc_tarjan(local_nodes, local_edges)
        for comp in comps:
            group_head = sorted(comp)[0]
            # 這個檔若是第一次遇到該 group，就記成 owner
            GROUP_OWNER.setdefault(
                group_head, sanitize_ident(os.path.splitext(filename)[0])
            )
            for dn in comp:
                DEF_TO_GROUP[dn] = group_head

    # 3) 依每個檔的 SCC 產生 types/<group_head>.proto（但每個 group 只讓它的 owner 輸出一次）
    for filename in sorted(defs_per_file.keys()):
        schema, defs = defs_per_file[filename]
        if not defs:
            continue
        local_nodes = sorted(sanitize_ident(n) for n in defs.keys())
        if not local_nodes:
            continue
        local_edges = {n: set() for n in local_nodes}
        for n in local_nodes:
            local_edges[n] = set(
                [m for m in dep_graph.get(n, set()) if m in local_nodes]
            )

        comps = scc_tarjan(local_nodes, local_edges)
        for comp in comps:
            group_head = sorted(comp)[0]
            # 只讓 owner 產生這個 group 檔
            if GROUP_OWNER.get(group_head) != sanitize_ident(
                os.path.splitext(filename)[0]
            ):
                continue

            defs_in_group = []
            for dn in comp:
                # 找回原始 key
                orig_key = next(
                    (k for k in defs.keys() if sanitize_ident(k) == dn), None
                )
                if orig_key is None:
                    continue
                defs_in_group.append((dn, defs[orig_key]))

            if defs_in_group:
                generate_group_proto(
                    group_filename=group_head,  # 注意：檔名用 group_head（SCC 頭）
                    defs_in_group=defs_in_group,
                    output_dir=output_dir,
                    registry=registry,
                    pkg_types=pkg_types,
                    pkg_enums=pkg_enums,
                    go_import_base_versioned=go_import_base_versioned,
                )

    # 4) 輸出 top-level（每個 json 一個 <name>.proto）
    for filename in os.listdir(input_dir):
        if not filename.endswith(".json"):
            continue
        with open(os.path.join(input_dir, filename), encoding="utf-8") as f:
            schema = json.load(f)
        schema_name = os.path.splitext(filename)[0]
        generate_schema_proto(
            schema_name,
            schema,
            output_dir,
            registry,
            pkg_schemas,
            pkg_types,
            pkg_enums,
            go_import_base_versioned,
            go_pkg_schemas,
        )


if __name__ == "__main__":
    if not (3 <= len(sys.argv) <= 4):
        print(
            "Usage: python json_to_proto.py <input_directory> <output_directory> [go_import_base]"
        )
        sys.exit(1)
    input_dir = sys.argv[1]
    output_dir = sys.argv[2]
    go_import_base = sys.argv[3] if len(sys.argv) == 4 else DEFAULT_GO_IMPORT_BASE
    process_directory(input_dir, output_dir, go_import_base)
