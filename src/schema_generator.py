#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Schema/code generation orchestrator for:
- HL7 (v600)
- OCPI (v211, v22, v221)
- OCPP (v16, v201, v21)

Supported languages (initial subset):
  c, cpp, java, python, csharp, go, ruby

Examples:
  # 全部規格都跑，產 C/C++/Java/Python/C#/Go 與 Ruby
  python3 src/schema_generator.py --all --langs c cpp java python csharp go ruby

  # 只跑 OCPI v211 與 v221，產 C/Java
  python3 src/schema_generator.py --ocpi v211 v221 --langs c java

  # 跑 OCPP 全版本但跳過清除舊輸出
  python3 src/schema_generator.py --ocpp --skip-clean --langs cpp

  # 只清除 HL7 的輸出（不做生成）
  python3 src/schema_generator.py --hl7 --only-clean

  # 乾跑
  python3 src/schema_generator.py --all --langs cpp go --dry-run
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from collections import defaultdict

# repo root（本檔位在 src/ 內）
REPO_ROOT = Path(__file__).resolve().parent.parent

JSON_TO_PROTO = REPO_ROOT / "src" / "json_to_proto.py"

RESOURCES = REPO_ROOT / "resources" / "schemas"
OUTPUT_PROTO = REPO_ROOT / "output" / "proto"
OUTPUT_GEN_ROOT = REPO_ROOT / "output" / "gen"

# 規格與版本對應
OCPI_VERSIONS = ["v211", "v22", "v221"]
OCPP_VERSIONS = ["v16", "v201", "v21"]
HL7_VERSIONS = ["v600"]

# 限定要支援的語言
LANG_TO_FLAG = {
    "c": "--c_out",
    "cpp": "--cpp_out",
    "java": "--java_out",
    "python": "--python_out",
    "csharp": "--csharp_out",
    "go": "--go_out",
    "ruby": "--ruby_out",
}

# 可選的預設編譯選項（視需求調整）
GO_OUT_OPTS = "paths=source_relative"  # 常見設定
# NANOPB 可在這邊放參數，例如：nanopb_opt1=...,nanopb_opt2=...
NANOPB_OUT_OPTS = ""  # 留空則不帶 options


def sh(cmd, dry_run=False):
    print("$", " ".join(map(str, cmd)))
    if dry_run:
        return 0
    try:
        subprocess.check_call(cmd)
        return 0
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Command failed with exit code {e.returncode}")
        return e.returncode


def which_or_none(name: str):
    from shutil import which

    return which(name)


def ensure_protoc_or_die():
    if which_or_none("protoc") is None:
        print(
            "[ERROR] 'protoc' not found in PATH. Please install Protocol Buffers compiler."
        )
        sys.exit(1)


def clean_dir(path: Path, dry_run=False):
    if path.exists():
        print(f"[CLEAN] rm -rf {path}")
        if not dry_run:
            shutil.rmtree(path, ignore_errors=True)
    print(f"[MKDIR] {path}")
    if not dry_run:
        path.mkdir(parents=True, exist_ok=True)


def json_to_proto(input_dir: Path, output_dir: Path, dry_run=False):
    cmd = [sys.executable, str(JSON_TO_PROTO), str(input_dir), str(output_dir)]
    return sh(cmd, dry_run=dry_run)


def protoc_lang(proto_root: Path, lang: str, out_dir: Path, dry_run=False):
    """Compile all .proto under proto_root into out_dir for a specific language."""
    ensure_protoc_or_die()

    if lang not in LANG_TO_FLAG:
        print(f"[WARN] Unsupported lang '{lang}', skip.")
        return 0

    flag = LANG_TO_FLAG[lang]

    protos_abs = sorted(proto_root.rglob("*.proto"))
    if not protos_abs:
        print(f"[WARN] No .proto files found under {proto_root}")
        return 0

    clean_dir(out_dir, dry_run=dry_run)

    # 組裝 --<lang>_out 參數（非 C# 一次跑完；C# 下面會分批）
    def build_out_arg(target_dir: Path) -> str:
        if lang == "go":
            return f"{flag}={GO_OUT_OPTS}:{target_dir}"
        elif lang == "c":
            return (
                f"{flag}={target_dir}"
                if not NANOPB_OUT_OPTS
                else f"{flag}={NANOPB_OUT_OPTS}:{target_dir}"
            )
        else:
            return f"{flag}={target_dir}"

    # 特例：Go 需要分三批、固定順序（enums -> types -> root）
    if lang == "go":
        # 以相對路徑分類
        rels = [p.relative_to(proto_root) for p in protos_abs]

        enums_list = [
            r.as_posix()
            for r in rels
            if len(r.parts) >= 2 and r.parts[0] == "types" and r.parts[1] == "enums"
        ]
        types_top_list = [
            r.as_posix()
            for r in rels
            if len(r.parts) == 2 and r.parts[0] == "types"  # maxdepth=1
        ]
        root_top_list = [r.as_posix() for r in rels if len(r.parts) == 1]

        batches = [
            ("types/enums", enums_list),
            ("types", types_top_list),
            (".", root_top_list),
        ]

        rc_any = 0
        for tag, lst in batches:
            if not lst:
                continue
            out_arg = build_out_arg(out_dir)
            cmd = ["protoc", f"-I={proto_root}", out_arg] + lst
            print(f"# [go] batch: {tag} ({len(lst)} files)")
            rc = sh(cmd, dry_run=dry_run)
            if rc != 0:
                rc_any = rc
                break
        return rc_any

    # 特例：C# 分父資料夾分批（為了檔案分層）
    if lang == "csharp":
        from collections import defaultdict

        groups = defaultdict(list)
        for p in protos_abs:
            rel = p.relative_to(proto_root)
            parent = rel.parent.as_posix() or "."
            groups[parent].append(rel.as_posix())

        rc_any = 0
        for parent, rel_list in sorted(groups.items()):
            target_dir = out_dir if parent == "." else out_dir / parent
            if not dry_run:
                target_dir.mkdir(parents=True, exist_ok=True)
            out_arg = build_out_arg(target_dir)
            cmd = ["protoc", f"-I={proto_root}", out_arg] + rel_list
            rc = sh(cmd, dry_run=dry_run)
            if rc != 0:
                rc_any = rc
                break
        return rc_any

    # 其它語言：一次性呼叫
    rels = [str(p.relative_to(proto_root).as_posix()) for p in protos_abs]
    out_arg = build_out_arg(out_dir)
    cmd = ["protoc", f"-I={proto_root}", out_arg] + rels
    return sh(cmd, dry_run=dry_run)


def protoc_many(
    proto_root: Path, langs, out_base: Path, spec: str, ver: str | None, dry_run=False
):
    """
    針對多個語言呼叫 protoc。
    out_base/<lang>_out/<spec>/<ver?> 為輸出路徑。
    """
    for lang in langs:
        sub = spec.lower() if ver is None else f"{spec.lower()}/{ver}"
        lang_out = out_base / f"{lang}_out" / sub
        rc = protoc_lang(proto_root, lang, lang_out, dry_run=dry_run)
        if rc != 0:
            sys.exit(rc)


def handle_ocpi(versions, skip_clean, only_clean, dry_run, langs):
    if not versions:
        versions = OCPI_VERSIONS
    for ver in versions:
        in_dir = RESOURCES / "OCPI" / ver
        out_dir = OUTPUT_PROTO / "OCPI" / ver
        if not in_dir.exists():
            print(f"[WARN] OCPI {ver} schema dir not found: {in_dir}")
            continue
        if not skip_clean:
            clean_dir(out_dir, dry_run=dry_run)
        if not only_clean:
            rc = json_to_proto(in_dir, out_dir, dry_run=dry_run)
            if rc != 0:
                sys.exit(rc)
            protoc_many(out_dir, langs, OUTPUT_GEN_ROOT, "ocpi", ver, dry_run=dry_run)


def handle_hl7(versions, skip_clean, only_clean, dry_run, langs):
    if not versions:
        versions = HL7_VERSIONS
    for ver in versions:
        in_dir = RESOURCES / "HL7" / ver
        out_dir = OUTPUT_PROTO / "HL7" / ver
        if not in_dir.exists():
            print(f"[WARN] HL7 schema dir not found: {in_dir}")
            return
        if not skip_clean:
            clean_dir(out_dir, dry_run=dry_run)
        if not only_clean:
            rc = json_to_proto(in_dir, out_dir, dry_run=dry_run)
            if rc != 0:
                sys.exit(rc)
            protoc_many(out_dir, langs, OUTPUT_GEN_ROOT, "hl7", ver, dry_run=dry_run)


def handle_ocpp(versions, skip_clean, only_clean, dry_run, langs):
    if not versions:
        versions = OCPP_VERSIONS
    for ver in versions:
        in_dir = RESOURCES / "OCPP" / ver
        out_dir = OUTPUT_PROTO / "OCPP" / ver
        if not in_dir.exists():
            print(f"[WARN] OCPP {ver} schema dir not found: {in_dir}")
            continue
        if not skip_clean:
            clean_dir(out_dir, dry_run=dry_run)
        if not only_clean:
            rc = json_to_proto(in_dir, out_dir, dry_run=dry_run)
            if rc != 0:
                sys.exit(rc)
            protoc_many(out_dir, langs, OUTPUT_GEN_ROOT, "ocpp", ver, dry_run=dry_run)


def parse_args():
    p = argparse.ArgumentParser(
        description="Schema -> proto -> code generation orchestrator"
    )

    group = p.add_mutually_exclusive_group(required=True)

    group.add_argument("--all", action="store_true", help="Run OCPI, HL7, OCPP")

    group.add_argument(
        "--ocpi",
        nargs="*",
        metavar="VER",
        help=f"Run OCPI (versions: {', '.join(OCPI_VERSIONS)}). Omit to run all.",
    )

    group.add_argument(
        "--ocpp",
        nargs="*",
        metavar="VER",
        help=f"Run OCPP (versions: {', '.join(OCPP_VERSIONS)}). Omit to run all.",
    )

    group.add_argument(
        "--hl7",
        nargs="*",
        metavar="VER",
        help=f"Run HL7 (versions: {', '.join(HL7_VERSIONS)}). Omit to run all.",
    )

    supported = ["c", "cpp", "java", "python", "csharp", "go", "ruby"]
    p.add_argument(
        "--langs",
        nargs="+",
        metavar="LANG",
        choices=sorted(supported),
        required=False,
        default=[],
        help=(
            "Languages to generate with protoc. "
            "Required unless --only-clean is provided. "
            f"Supported: {', '.join(sorted(supported))}."
        ),
    )

    p.add_argument(
        "--skip-clean",
        action="store_true",
        help="Do not remove proto output dirs before generation",
    )

    p.add_argument(
        "--only-clean",
        action="store_true",
        help="Only clean output dirs, do not generate",
    )

    p.add_argument(
        "--dry-run", action="store_true", help="Print actions without executing"
    )

    return p.parse_args()


def main():
    args = parse_args()

    if args.all:
        handle_ocpi(
            OCPI_VERSIONS, args.skip_clean, args.only_clean, args.dry_run, args.langs
        )

        handle_hl7(
            HL7_VERSIONS, args.skip_clean, args.only_clean, args.dry_run, args.langs
        )

        handle_ocpp(
            OCPP_VERSIONS, args.skip_clean, args.only_clean, args.dry_run, args.langs
        )

        return

    if isinstance(args.ocpi, list):
        versions = args.ocpi if len(args.ocpi) > 0 else OCPI_VERSIONS
        handle_ocpi(
            versions, args.skip_clean, args.only_clean, args.dry_run, args.langs
        )
        return

    if isinstance(args.hl7, list):
        versions = args.hl7 if len(args.hl7) > 0 else HL7_VERSIONS
        handle_hl7(versions, args.skip_clean, args.only_clean, args.dry_run, args.langs)
        return

    if isinstance(args.ocpp, list):
        versions = args.ocpp if len(args.ocpp) > 0 else OCPP_VERSIONS
        handle_ocpp(
            versions, args.skip_clean, args.only_clean, args.dry_run, args.langs
        )
        return


if __name__ == "__main__":
    main()
