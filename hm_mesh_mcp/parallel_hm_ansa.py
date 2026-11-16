"""Coordinator for running HyperMesh background meshing and ANSA meshing together.

This file is used by the HyperMesh panel when the HM+ANSA combined workflow is
started.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any, Optional


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


ROOT = Path(__file__).resolve().parent
RUNS_DIR = ROOT / "runs"


def no_console_kwargs() -> dict[str, Any]:
    if sys.platform.startswith("win"):
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {}


DEFAULT_FILLET_RULES = [
    {"radius": "1.-2.", "width": "1.-2.", "rows": 1},
    {"radius": "2.1-4.", "width": "2.1-4.", "rows": 2},
    {"radius": "4.1-15.", "width": "4.1-15.", "rows": 3},
    {"radius": "15.1-24.", "width": "15.1-24.", "rows": 5},
]


def log(message: str = "") -> None:
    print(message, flush=True)


def wait_for_existing_file(path: Path, label: str = "文件", timeout_seconds: float = 5.0) -> None:
    """Wait briefly for a file produced by a just-started GUI/script to appear."""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if path.exists() and path.is_file():
            return
        time.sleep(0.1)
    if not path.exists():
        raise FileNotFoundError(f"{label}不存在或尚未写入：{path}")


def read_json(path: Path) -> dict[str, Any]:
    wait_for_existing_file(path, "JSON 文件")
    last_error: Optional[Exception] = None
    deadline = time.time() + 3.0
    while time.time() < deadline:
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            last_error = exc
            time.sleep(0.1)
    if last_error is not None:
        raise last_error
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_argv_file(path: Path) -> list[str]:
    wait_for_existing_file(path, "HM 参数文件")
    args = [line.rstrip("\n") for line in path.read_text(encoding="utf-8-sig").splitlines()]
    return [arg for arg in args if arg != ""]


def available_inp_basename(output_dir: Path, stem: str) -> str:
    candidate = stem
    index = 1
    while (output_dir / f"{candidate}.inp").exists():
        candidate = f"{stem}_{index:03d}"
        index += 1
    return candidate


def is_ascii_path(value: Path | str) -> bool:
    try:
        str(value).encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def sanitize_ascii_name(value: str, fallback: str = "ansa_mesh") -> str:
    """Make a conservative ASCII file/folder stem for HyperMesh import paths."""
    normalized = unicodedata.normalize("NFKD", value)
    chars: list[str] = []
    for char in normalized:
        if char.isascii() and (char.isalnum() or char in "._-"):
            chars.append(char)
        elif char.isspace() or char in "()[]{}（）【】":
            chars.append("_")
    cleaned = re.sub(r"_+", "_", "".join(chars)).strip("._-")
    if not cleaned:
        cleaned = fallback
    return cleaned[:80]


def nearest_ascii_parent(path: Path, fallback: Path) -> Path:
    """Return the closest parent whose full path is ASCII-only."""
    candidates = [path.parent, *path.parents]
    for candidate in candidates:
        if is_ascii_path(candidate):
            return candidate
    return fallback


def parallel_safe_ansa_output(
    *,
    desired_output_dir: Path,
    source_step: Path,
    stamp: str,
    project_dir: Path,
) -> tuple[Path, str, str]:
    """Avoid Chinese/non-ASCII ANSA INP paths in HM+ANSA combined import.

    HyperMesh 2020's Abaqus INP importer may fail with "Error creating new
    process" when the import path contains Chinese/non-ASCII characters.  In
    parallel mode, place ANSA's public INP in the nearest ASCII parent directory
    and use an ASCII output basename when needed.
    """
    desired_basename = source_step.stem
    if is_ascii_path(desired_output_dir) and is_ascii_path(desired_basename):
        return desired_output_dir, desired_basename, ""

    ascii_parent = nearest_ascii_parent(desired_output_dir, project_dir)
    safe_stem = sanitize_ascii_name(source_step.stem, fallback=f"ansa_mesh_{stamp}")
    safe_output_dir = ascii_parent / f"{safe_stem}_ANSA_Mesh"
    note = (
        "[ANSA] 检测到并行 ANSA 输出目录或文件名含中文/非 ASCII，"
        f"为保证 HyperMesh 导入稳定，改用英文输出目录：{safe_output_dir}"
    )
    return safe_output_dir, safe_stem, note


def find_python_launcher() -> list[str]:
    py = shutil.which("py.exe") or shutil.which("py")
    if py:
        return [py, "-3"]
    python = shutil.which("python.exe") or shutil.which("python")
    if python:
        return [python]
    raise RuntimeError("未找到 Python。请确认 py.exe 或 python.exe 可用。")


def load_ansa_settings(ansa_base: Path) -> dict[str, Any]:
    settings_path = ansa_base / "settings.json"
    if settings_path.exists():
        try:
            return read_json(settings_path)
        except Exception as exc:
            log(f"[ANSA] 读取 settings.json 失败，将使用默认值：{exc}")
    return {}


def discover_ansa_base(project_dir: Path, requested: str | None = None) -> Path:
    candidates: list[Path] = []
    configured_path = ""
    config_file = project_dir / "ansa_auto_mesh_dir.txt"
    if config_file.exists():
        try:
            configured_path = config_file.read_text(encoding="utf-8-sig").strip()
        except Exception as exc:
            log(f"[ANSA] 读取 ansa_auto_mesh_dir.txt 失败，将继续尝试其它位置：{exc}")
    for raw in [
        requested,
        configured_path,
        os.environ.get("ANSA_AUTO_MESH_DIR"),
        str(project_dir / "ansa_mesh_tool"),
        str(project_dir.parent / "ansa_auto" / "ansa_mesh_tool"),
        str(project_dir.parent.parent / "ansa_auto" / "ansa_mesh_tool"),
        r"E:\ansa_auto\ansa_mesh_tool",
    ]:
        if not raw:
            continue
        try:
            candidate = Path(raw).resolve()
        except Exception:
            continue
        if candidate not in candidates:
            candidates.append(candidate)
    for candidate in candidates:
        if (candidate / "runner.py").exists() and (candidate / "main.xaml").exists():
            return candidate
    tried = "\n".join(f"  - {item}" for item in candidates)
    raise FileNotFoundError(
        "没有找到 ANSA Auto Mesh 工具目录。请设置 ANSA_AUTO_MESH_DIR 或检查 ansa_mesh_tool 位置。\n"
        f"已尝试：\n{tried}"
    )


def bridge_value(bridge: dict[str, Any], settings: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = bridge.get(key)
        if value not in (None, ""):
            return value
    for key in keys:
        value = settings.get(key)
        if value not in (None, ""):
            return value
    return default


def build_ansa_job_config(ansa_base: Path, bridge_state_path: Path, stamp: str, project_dir: Path) -> tuple[Path, Path]:
    bridge = read_json(bridge_state_path)
    settings = load_ansa_settings(ansa_base)

    source_step = Path(str(bridge.get("step_path", ""))).resolve()
    if not source_step.exists():
        raise FileNotFoundError(f"ANSA STEP 不存在：{source_step}")

    output_dir_value = bridge.get("output_path") or bridge.get("output_dir")
    if output_dir_value:
        final_output_dir = Path(str(output_dir_value)).resolve()
    else:
        final_output_dir = source_step.parent / f"{source_step.stem}_ANSA_Mesh"

    final_output_dir, stem, output_path_note = parallel_safe_ansa_output(
        desired_output_dir=final_output_dir,
        source_step=source_step,
        stamp=stamp,
        project_dir=project_dir,
    )
    if output_path_note:
        log(output_path_note)
    final_output_dir.mkdir(parents=True, exist_ok=True)

    output_basename = available_inp_basename(final_output_dir, stem)
    work_root = ansa_base / "work"
    job_dir = work_root / f"{output_basename}_job_{stamp}_parallel"
    job_dir.mkdir(parents=True, exist_ok=True)

    mpar = Path(str(bridge_value(bridge, settings, "mpar_template", "MeshTemplate", default=ansa_base / "templates" / "robot-2mm.ansa_mpar"))).resolve()
    qual = Path(str(bridge_value(bridge, settings, "qual_template", "QualityTemplate", default=ansa_base / "templates" / "subframe.ansa_qual"))).resolve()
    ansa_launcher = Path(str(bridge_value(bridge, settings, "ansa_launcher", "AnsaLauncher", default=""))).resolve()
    target_length = bridge_value(bridge, settings, "target_length", "TargetLength", default=2.0)
    minimum_length = bridge_value(bridge, settings, "minimum_length", "MinimumLength", default=0.5)
    fillet_rules = bridge.get("fillet_rules") or bridge.get("FilletRules") or settings.get("FilletRules") or DEFAULT_FILLET_RULES

    missing = []
    for label, path in [
        ("ANSA launcher", ansa_launcher),
        ("mesh template", mpar),
        ("quality criteria", qual),
    ]:
        if not path.exists():
            missing.append(f"{label}: {path}")
    if missing:
        raise FileNotFoundError("ANSA 配置文件缺失：\n" + "\n".join(missing))

    config = {
        "source_step": str(source_step),
        "mpar_template": str(mpar),
        "qual_template": str(qual),
        "ansa_launcher": str(ansa_launcher),
        "output_dir": str(job_dir),
        "final_output_dir": str(final_output_dir),
        "output_basename": output_basename,
        "parallel_output_path_note": output_path_note,
        "target_length": float(target_length),
        "minimum_length": float(minimum_length),
        "fillet_rules": fillet_rules,
        # Parallel mode should not silently loop through many ANSA restarts.
        # If ANSA fails, report it to the paired HM workflow and stop cleanly.
        "max_crash_retries": int(bridge_value(bridge, settings, "max_crash_retries", "MaxCrashRetries", default=0)),
    }
    config_path = job_dir / "job_config.json"
    write_json(config_path, config)
    return config_path, job_dir


def write_ansa_parallel_state(
    path: Path,
    *,
    active: bool,
    stamp: str,
    job_dir: Path,
    stop_file: Path | None,
    success: bool | None = None,
    message: str = "",
    inp_file: str | None = None,
) -> None:
    data: dict[str, Any] = {
        "active": active,
        "stamp": stamp,
        "job_dir": str(job_dir),
        "runner_log": str(job_dir / "runner.log"),
        "result_json": str(job_dir / "result.json"),
        "stop_file": str(stop_file) if stop_file else "",
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "parallel_hm_ansa.py",
    }
    if success is not None:
        data["success"] = success
    if message:
        data["message"] = message
    if inp_file:
        data["inp_file"] = inp_file
    write_json(path, data)


def read_new_text(path: Path, offset: int) -> tuple[str, int]:
    if not path.exists():
        return "", offset
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        handle.seek(offset)
        text = handle.read()
        return text, handle.tell()


def extract_hm_output_path(log_path: Path) -> str:
    if not log_path.exists():
        return ""
    output = ""
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("Output:"):
            output = line.split(":", 1)[1].strip()
    return output


def hm_final_element_count(log_path: Path) -> int:
    if not log_path.exists():
        return 0
    elems = 0
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.search(r"MCP_FINAL_COUNTS\s+elems=(\d+)", line)
        if match:
            elems = int(match.group(1))
    return elems


def classify_parallel_result(
    *,
    hm_success: bool,
    hm_has_elements: bool,
    ansa_success: bool,
    stop_requested: bool,
    hm_return_code: int | None,
    ansa_return_code: int | None,
    ansa_message: str,
) -> tuple[bool, str, str, list[str], list[str]]:
    """Return workflow success, status, severity, warnings, errors.

    success means the combined workflow has enough usable output to import.
    severity keeps the difference between a clean pass and a pass with warnings.
    """
    warnings: list[str] = []
    errors: list[str] = []
    hm_usable = hm_success or hm_has_elements

    if stop_requested:
        return False, "stopped", "stopped", warnings, ["用户停止了 HM+ANSA 同时划分。"]

    if hm_has_elements and not hm_success:
        warnings.append("HM 后台流程生成了网格，但返回码非 0；按可用网格继续合并。")
    if hm_return_code not in (0, None) and hm_success:
        warnings.append(f"HM 返回码为 {hm_return_code}，但结果被判定可用。")
    if ansa_return_code not in (0, None) and ansa_success:
        warnings.append(f"ANSA 返回码为 {ansa_return_code}，但 result.json 判定成功。")

    if hm_usable and ansa_success:
        if warnings:
            return True, "success_with_warnings", "warning", warnings, errors
        return True, "success", "ok", warnings, errors

    if hm_usable and not ansa_success:
        errors.append("ANSA 未生成可用 INP。")
        if ansa_message:
            errors.append(f"ANSA 信息：{ansa_message}")
        return False, "partial_hm_only", "partial", warnings, errors

    if ansa_success and not hm_usable:
        errors.append("HM 未生成可用网格。")
        return False, "partial_ansa_only", "partial", warnings, errors

    errors.append("HM 和 ANSA 都没有生成可合并的结果。")
    if ansa_message:
        errors.append(f"ANSA 信息：{ansa_message}")
    return False, "failed", "failed", warnings, errors


def summarize_ansa_parts(ansa_result: dict[str, Any]) -> dict[str, Any]:
    """Extract part-level ANSA meshing details for the combined HM popup/report."""
    meshing = ansa_result.get("meshing") if isinstance(ansa_result.get("meshing"), dict) else {}
    geometry = ansa_result.get("geometry") if isinstance(ansa_result.get("geometry"), dict) else {}

    skipped_parts = meshing.get("skipped_parts") or geometry.get("bad_parts") or []
    failed_parts = meshing.get("failed_parts") or []
    if not isinstance(skipped_parts, list):
        skipped_parts = []
    if not isinstance(failed_parts, list):
        failed_parts = []

    return {
        "part_count": meshing.get("part_count"),
        "total_part_count": meshing.get("total_part_count"),
        "skipped_part_count": meshing.get("skipped_part_count", len(skipped_parts) if skipped_parts else 0),
        "skipped_issue_count": meshing.get("skipped_issue_count", len(skipped_parts) if skipped_parts else 0),
        "skipped_parts": skipped_parts,
        "failed_parts": failed_parts,
        "unmapped_failed_count": geometry.get("unmapped_failed_count", 0),
    }


def format_part_issue(item: Any) -> str:
    if not isinstance(item, dict):
        return str(item)
    label = str(item.get("label") or item.get("name") or item.get("key") or "未命名部件")
    error_types = item.get("error_types") or item.get("errors") or []
    if isinstance(error_types, list) and error_types:
        return f"{label}（{', '.join(str(value) for value in error_types)}）"
    error_count = item.get("error_count")
    if error_count:
        return f"{label}（{error_count} 个问题）"
    return label


def write_parallel_report(path: Path, summary: dict[str, Any]) -> None:
    ansa = summary.get("ansa", {}) if isinstance(summary.get("ansa"), dict) else {}
    ansa_skipped = ansa.get("skipped_parts") or []
    ansa_failed = ansa.get("failed_parts") or []
    lines = [
        "HM+ANSA 同时划分报告",
        f"任务ID: {summary.get('task_id', '')}",
        f"状态: {summary.get('status', '')}",
        f"级别: {summary.get('severity', '')}",
        f"成功: {summary.get('success', False)}",
        f"停止: {summary.get('stopped', False)}",
        f"状态文件: {summary.get('state_json', '')}",
        "",
        "[HM]",
        f"  success: {summary.get('hm', {}).get('success')}",
        f"  usable: {summary.get('hm', {}).get('usable')}",
        f"  return_code: {summary.get('hm', {}).get('return_code')}",
        f"  final_elements: {summary.get('hm', {}).get('final_elements')}",
        f"  output_hm_path: {summary.get('hm', {}).get('output_hm_path')}",
        f"  log: {summary.get('hm', {}).get('log')}",
        "",
        "[ANSA]",
        f"  success: {summary.get('ansa', {}).get('success')}",
        f"  return_code: {summary.get('ansa', {}).get('return_code')}",
        f"  inp_file: {summary.get('ansa', {}).get('inp_file')}",
        f"  job_dir: {summary.get('ansa', {}).get('job_dir')}",
        f"  result_json: {summary.get('ansa', {}).get('result_json')}",
        f"  message: {summary.get('ansa', {}).get('message')}",
        f"  parts: meshed={ansa.get('part_count')} / total={ansa.get('total_part_count')}",
        f"  skipped_part_count: {ansa.get('skipped_part_count', 0)}",
        f"  failed_part_count: {len(ansa_failed)}",
        f"  unmapped_geometry_error_count: {ansa.get('unmapped_failed_count', 0)}",
    ]
    if ansa_skipped:
        lines.append("  skipped_parts:")
        for item in ansa_skipped[:30]:
            lines.append(f"    - {format_part_issue(item)}")
        if len(ansa_skipped) > 30:
            lines.append(f"    - ... 还有 {len(ansa_skipped) - 30} 个，详见 result.json")
    if ansa_failed:
        lines.append("  failed_parts:")
        for item in ansa_failed[:30]:
            lines.append(f"    - {format_part_issue(item)}")
        if len(ansa_failed) > 30:
            lines.append(f"    - ... 还有 {len(ansa_failed) - 30} 个，详见 result.json")
    lines.extend([
        "",
        "[合并导入]",
        f"  hm_output_for_import: {summary.get('merge', {}).get('hm_output_for_import')}",
        f"  ansa_inp_for_import: {summary.get('merge', {}).get('ansa_inp_for_import')}",
        "",
        "[Warnings]",
    ])
    warnings = summary.get("warnings") or []
    lines.extend([f"  - {item}" for item in warnings] or ["  无"])
    lines.append("")
    lines.append("[Errors]")
    errors = summary.get("errors") or []
    lines.extend([f"  - {item}" for item in errors] or ["  无"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def new_parallel_state(stamp: str, *, state_path: Path, summary_path: Path, report_path: Path) -> dict[str, Any]:
    return {
        "task_id": stamp,
        "stage": "initializing",
        "severity": "running",
        "success": None,
        "stopped": False,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "hm": {
            "status": "pending",
            "success": None,
            "usable": None,
            "return_code": None,
            "final_elements": None,
        },
        "ansa": {
            "status": "pending",
            "success": None,
            "return_code": None,
            "inp_file": "",
            "message": "",
        },
        "merge": {
            "status": "pending",
            "hm_output_for_import": "",
            "ansa_inp_for_import": "",
        },
        "paths": {
            "state_json": str(state_path),
            "summary_json": str(summary_path),
            "report_txt": str(report_path),
        },
        "warnings": [],
        "errors": [],
        "events": [],
    }


def update_parallel_state(
    state_path: Path,
    state: dict[str, Any],
    *,
    stage: str | None = None,
    severity: str | None = None,
    message: str = "",
) -> None:
    if stage is not None:
        state["stage"] = stage
    if severity is not None:
        state["severity"] = severity
    state["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    if message:
        state["message"] = message
        events = state.setdefault("events", [])
        events.append(
            {
                "time": state["updated_at"],
                "stage": state.get("stage", ""),
                "severity": state.get("severity", ""),
                "message": message,
            }
        )
        if len(events) > 80:
            del events[:-80]
    write_json(state_path, state)


def terminate_process_tree(process: subprocess.Popen[Any] | None, label: str) -> None:
    if process is None or process.poll() is not None:
        return
    pid = process.pid
    log(f"[STOP] Terminating {label} process tree, PID={pid} ...")
    if sys.platform.startswith("win"):
        subprocess.run(
            ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            **no_console_kwargs(),
        )
    else:
        try:
            process.terminate()
            process.wait(timeout=8)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run HM background and ANSA background meshing in parallel.")
    parser.add_argument("--hm-argv-file", required=True)
    parser.add_argument("--ansa-state", required=True)
    parser.add_argument("--ansa-base", default="")
    parser.add_argument("--project-dir", default=str(ROOT))
    parser.add_argument("--stamp", default=time.strftime("%Y%m%d_%H%M%S"))
    parser.add_argument("--stop-file", default="")
    args = parser.parse_args(argv)

    project_dir = Path(args.project_dir).resolve()
    stamp = args.stamp
    runs_dir = project_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    hm_argv_file = Path(args.hm_argv_file).resolve()
    ansa_state = Path(args.ansa_state).resolve()
    ansa_base = discover_ansa_base(project_dir, args.ansa_base)
    hm_log = runs_dir / f"parallel_hm_{stamp}.log"
    ansa_launcher_log = runs_dir / f"parallel_ansa_launcher_{stamp}.log"
    summary_path = runs_dir / f"parallel_summary_{stamp}.json"
    report_path = runs_dir / f"parallel_report_{stamp}.txt"
    state_path = runs_dir / f"parallel_state_{stamp}.json"
    ansa_parallel_state = runs_dir / "ansa_parallel_job.json"
    state = new_parallel_state(stamp, state_path=state_path, summary_path=summary_path, report_path=report_path)
    update_parallel_state(state_path, state, stage="initializing", message="并行协调器启动，正在读取 HM/ANSA 参数。")

    log("=== HM + ANSA parallel meshing ===")
    log(f"Project: {project_dir}")
    log(f"Stamp: {stamp}")
    log(f"Parallel state: {state_path}")
    log("")

    hm_cmd = read_argv_file(hm_argv_file)
    if not hm_cmd:
        raise RuntimeError(f"HM 参数文件为空：{hm_argv_file}")
    ansa_config, ansa_job_dir = build_ansa_job_config(ansa_base, ansa_state, stamp, project_dir)
    ansa_runner = ansa_base / "runner.py"
    if not ansa_runner.exists():
        raise FileNotFoundError(f"ANSA runner.py 不存在：{ansa_runner}")
    ansa_cmd = find_python_launcher() + [str(ansa_runner), str(ansa_config)]
    stop_file = Path(args.stop_file).resolve() if args.stop_file else None
    state["paths"].update(
        {
            "hm_log": str(hm_log),
            "ansa_launcher_log": str(ansa_launcher_log),
            "ansa_job_dir": str(ansa_job_dir),
            "ansa_runner_log": str(ansa_job_dir / "runner.log"),
            "ansa_result_json": str(ansa_job_dir / "result.json"),
            "stop_file": str(stop_file) if stop_file else "",
        }
    )
    update_parallel_state(state_path, state, stage="configured", message="HM/ANSA 参数读取完成，准备启动两个后台任务。")
    write_ansa_parallel_state(
        ansa_parallel_state,
        active=True,
        stamp=stamp,
        job_dir=ansa_job_dir,
        stop_file=stop_file,
        message="ANSA 后台任务已由 HM+ANSA 同时划分启动。",
    )

    log("[HM] Starting HyperMesh background meshing...")
    log(f"[HM] Log: {hm_log}")
    log("[ANSA] Starting ANSA no-GUI meshing...")
    log(f"[ANSA] Job: {ansa_job_dir}")
    log(f"[ANSA] Launcher log: {ansa_launcher_log}")
    log("")

    hm_attempt = 1
    hm_max_attempts = 2

    def start_hm_process(attempt: int):
        mode = "w" if attempt == 1 else "a"
        with hm_log.open(mode, encoding="utf-8", errors="replace") as hm_out:
            if attempt > 1:
                hm_out.write(f"\n=== HM retry attempt {attempt}/{hm_max_attempts} ===\n")
            return subprocess.Popen(
                hm_cmd,
                cwd=str(project_dir),
                stdout=hm_out,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                **no_console_kwargs(),
            )

    hm_process = start_hm_process(hm_attempt)
    state["hm"].update({"status": "running", "pid": hm_process.pid, "attempt": hm_attempt})
    with ansa_launcher_log.open("w", encoding="utf-8", errors="replace") as ansa_out:
        ansa_process = subprocess.Popen(
            ansa_cmd,
            cwd=str(ansa_base),
            stdout=ansa_out,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            **no_console_kwargs(),
        )
    state["ansa"].update({"status": "running", "pid": ansa_process.pid})
    update_parallel_state(state_path, state, stage="running", message="HM 与 ANSA 后台任务已启动。")

    offsets = {
        "hm": 0,
        "ansa_runner": 0,
        "ansa_launcher": 0,
    }
    ansa_runner_log = ansa_job_dir / "runner.log"
    stop_requested = False

    def handle_stop_signal(signum: int, frame: Any) -> None:
        nonlocal stop_requested
        stop_requested = True
        log(f"[STOP] Received signal {signum}; will stop HM and ANSA children.")

    try:
        signal.signal(signal.SIGTERM, handle_stop_signal)
        signal.signal(signal.SIGINT, handle_stop_signal)
    except Exception:
        pass

    hm_done = False
    ansa_done = False
    stopping_state_written = False
    while True:
        if not stop_requested and stop_file and stop_file.exists():
            stop_requested = True
            log(f"[STOP] Stop file detected: {stop_file}")
        if stop_requested:
            if not stopping_state_written:
                state["stopped"] = True
                if not hm_done:
                    state["hm"]["status"] = "stopping"
                if not ansa_done:
                    state["ansa"]["status"] = "stopping"
                update_parallel_state(state_path, state, stage="stopping", severity="stopped", message="收到停止请求，正在终止 HM/ANSA 子进程。")
                stopping_state_written = True
            terminate_process_tree(hm_process, "HM")
            terminate_process_tree(ansa_process, "ANSA")

        for key, tag, path in [
            ("hm", "HM", hm_log),
        ]:
            text, offsets[key] = read_new_text(path, offsets[key])
            if text:
                for line in text.splitlines():
                    log(f"[{tag}] {line}")
        for key, path in [
            ("ansa_runner", ansa_runner_log),
            ("ansa_launcher", ansa_launcher_log),
        ]:
            _text, offsets[key] = read_new_text(path, offsets[key])

        if not hm_done and hm_process.poll() is not None:
            log(f"[HM] Finished with return code {hm_process.returncode}.")
            if hm_process.returncode != 0 and hm_attempt < hm_max_attempts and not stop_requested:
                hm_attempt += 1
                log(f"[HM] First HM background run failed; retrying once automatically (attempt {hm_attempt}/{hm_max_attempts}).")
                state["hm"].update({"status": "retrying", "return_code": hm_process.returncode, "attempt": hm_attempt})
                update_parallel_state(state_path, state, stage="running", severity="running", message=f"HM 第一次后台运行返回 {hm_process.returncode}，自动重试一次。")
                hm_process = start_hm_process(hm_attempt)
                state["hm"].update({"status": "running", "pid": hm_process.pid, "return_code": None, "attempt": hm_attempt})
                update_parallel_state(state_path, state, stage="running", severity="running", message=f"HM 重试已启动，attempt={hm_attempt}。")
                continue
            hm_done = True
            hm_done_elems = hm_final_element_count(hm_log)
            hm_done_usable = hm_process.returncode == 0 or hm_done_elems > 0
            if stop_requested:
                hm_done_status = "stopped"
            elif hm_process.returncode == 0:
                hm_done_status = "success"
            elif hm_done_usable:
                hm_done_status = "warning"
            else:
                hm_done_status = "failed"
            state["hm"].update(
                {
                    "status": hm_done_status,
                    "success": hm_process.returncode == 0,
                    "usable": hm_done_usable,
                    "return_code": hm_process.returncode,
                    "final_elements": hm_done_elems,
                }
            )
            update_parallel_state(state_path, state, stage="running", message=f"HM 阶段结束：{hm_done_status}，elements={hm_done_elems}。")
            if hm_process.returncode != 0 and not stop_requested:
                log("[HM] HM background run failed, but ANSA will continue independently.")
        if not ansa_done and ansa_process.poll() is not None:
            ansa_done = True
            log(f"[ANSA] Finished with return code {ansa_process.returncode}. See ANSA Auto Mesh window for ANSA progress.")
            state["ansa"].update(
                {
                    "status": "finished_waiting_result" if not stop_requested else "stopped",
                    "return_code": ansa_process.returncode,
                }
            )
            update_parallel_state(state_path, state, stage="running", message=f"ANSA 进程结束，return_code={ansa_process.returncode}，等待读取 result.json。")
            if ansa_process.returncode != 0 and not hm_done and not stop_requested:
                log("[ANSA] ANSA run failed, but HM will continue independently.")

        if hm_done and ansa_done:
            break
        time.sleep(2.0)

    for key, tag, path in [
        ("hm", "HM", hm_log),
    ]:
        text, offsets[key] = read_new_text(path, offsets[key])
        if text:
            for line in text.splitlines():
                log(f"[{tag}] {line}")
    for key, path in [
        ("ansa_runner", ansa_runner_log),
        ("ansa_launcher", ansa_launcher_log),
    ]:
        _text, offsets[key] = read_new_text(path, offsets[key])

    ansa_result_path = ansa_job_dir / "result.json"
    ansa_result: dict[str, Any] = {}
    if ansa_result_path.exists():
        try:
            ansa_result = read_json(ansa_result_path)
        except Exception as exc:
            ansa_result = {"success": False, "message": f"读取 ANSA result.json 失败：{exc}"}
    else:
        ansa_result = {"success": False, "message": "ANSA 未生成 result.json"}

    hm_success = hm_process.returncode == 0
    ansa_success = bool(ansa_result.get("success"))
    ansa_message = str(ansa_result.get("message") or "")
    ansa_part_summary = summarize_ansa_parts(ansa_result)
    write_ansa_parallel_state(
        ansa_parallel_state,
        active=False,
        stamp=stamp,
        job_dir=ansa_job_dir,
        stop_file=stop_file,
        success=ansa_success and not stop_requested,
        message=str(ansa_result.get("message") or ("任务已停止" if stop_requested else "")),
        inp_file=str(ansa_result.get("inp_file") or ""),
    )
    hm_output_path = extract_hm_output_path(hm_log)
    hm_final_elems = hm_final_element_count(hm_log)
    hm_has_elements = hm_final_elems > 0
    hm_usable = hm_success or hm_has_elements
    overall_success, status, severity, warnings, errors = classify_parallel_result(
        hm_success=hm_success,
        hm_has_elements=hm_has_elements,
        ansa_success=ansa_success,
        stop_requested=stop_requested,
        hm_return_code=hm_process.returncode,
        ansa_return_code=ansa_process.returncode,
        ansa_message=ansa_message,
    )
    ansa_skipped_count = int(ansa_part_summary.get("skipped_part_count") or 0)
    ansa_failed_count = len(ansa_part_summary.get("failed_parts") or [])
    if ansa_success and (ansa_skipped_count > 0 or ansa_failed_count > 0):
        details = []
        if ansa_skipped_count > 0:
            details.append(f"{ansa_skipped_count} 个部件未进入 Batch Mesh")
        if ansa_failed_count > 0:
            details.append(f"{ansa_failed_count} 个部件 Batch Mesh 失败")
        warnings.append("ANSA 部分部件未划分：" + "，".join(details) + "。")
        if severity == "ok":
            status = "success_with_warnings"
            severity = "warning"
            overall_success = True
    if hm_usable and ansa_success:
        merge_status = "outputs_ready"
    elif hm_usable or ansa_success:
        merge_status = "partial_outputs_ready"
    elif stop_requested:
        merge_status = "stopped"
    else:
        merge_status = "failed"
    state["success"] = overall_success
    state["stopped"] = stop_requested
    state["warnings"] = warnings
    state["errors"] = errors
    state["hm"].update(
        {
            "status": "success" if hm_success else ("warning" if hm_usable else ("stopped" if stop_requested else "failed")),
            "success": hm_success,
            "usable": hm_usable,
            "has_elements": hm_has_elements,
            "final_elements": hm_final_elems,
            "return_code": hm_process.returncode,
            "log": str(hm_log),
            "output_hm_path": hm_output_path,
        }
    )
    state["ansa"].update(
        {
            "status": "success" if ansa_success else ("stopped" if stop_requested else "failed"),
            "success": ansa_success,
            "return_code": ansa_process.returncode,
            "job_dir": str(ansa_job_dir),
            "result_json": str(ansa_result_path),
            "inp_file": str(ansa_result.get("inp_file") or ""),
            "message": ansa_message,
            **ansa_part_summary,
        }
    )
    state["merge"].update(
        {
            "status": merge_status,
            "hm_output_for_import": hm_output_path if hm_usable else "",
            "ansa_inp_for_import": str(ansa_result.get("inp_file") or "") if ansa_success else "",
        }
    )
    update_parallel_state(state_path, state, stage=status, severity=severity, message=f"并行流程结束：{status}。")
    summary = {
        "task_id": stamp,
        "success": overall_success,
        "status": status,
        "severity": severity,
        "stopped": stop_requested,
        "warnings": warnings,
        "errors": errors,
        "report_txt": str(report_path),
        "state_json": str(state_path),
        "hm": {
            "success": hm_success,
            "usable": hm_usable,
            "has_elements": hm_has_elements,
            "final_elements": hm_final_elems,
            "return_code": hm_process.returncode,
            "log": str(hm_log),
            "output_hm_path": hm_output_path,
        },
        "ansa": {
            "success": ansa_success,
            "return_code": ansa_process.returncode,
            "job_dir": str(ansa_job_dir),
            "result_json": str(ansa_result_path),
            "inp_file": ansa_result.get("inp_file"),
            "message": ansa_message,
            **ansa_part_summary,
        },
        "merge": {
            "hm_output_for_import": hm_output_path if hm_usable else "",
            "ansa_inp_for_import": str(ansa_result.get("inp_file") or "") if ansa_success else "",
        },
    }
    write_json(summary_path, summary)
    write_parallel_report(report_path, summary)

    log("")
    log("=== Parallel summary ===")
    log(f"HM success: {hm_success}")
    log(f"HM usable: {hm_usable}")
    log(f"HM final elements: {hm_final_elems}")
    log(f"ANSA success: {ansa_success}")
    log(f"Parallel status: {status}")
    log(f"Parallel severity: {severity}")
    if hm_output_path:
        log(f"Output: {hm_output_path}")
    if ansa_result.get("inp_file"):
        log(f"ANSA INP: {ansa_result.get('inp_file')}")
    log(f"Parallel state: {state_path}")
    log(f"Parallel summary: {summary_path}")
    log(f"Parallel report: {report_path}")
    for warning in warnings:
        log(f"Warning: {warning}")
    for error in errors:
        log(f"Error: {error}")
    if stop_requested:
        log("Stopped: True")
    log(f"Success: {summary['success']}")
    return 0 if summary["success"] else 2


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except Exception as exc:
        log(f"[ERROR] Parallel coordinator failed: {exc}")
        try:
            parser = argparse.ArgumentParser(add_help=False)
            parser.add_argument("--project-dir", default=str(ROOT))
            parser.add_argument("--stamp", default=time.strftime("%Y%m%d_%H%M%S"))
            parser.add_argument("--stop-file", default="")
            args, _unknown = parser.parse_known_args(argv)
            project_dir = Path(args.project_dir).resolve()
            runs_dir = project_dir / "runs"
            runs_dir.mkdir(parents=True, exist_ok=True)
            stop_file = Path(args.stop_file).resolve() if args.stop_file else None
            write_ansa_parallel_state(
                runs_dir / "ansa_parallel_job.json",
                active=False,
                stamp=args.stamp,
                job_dir="",
                stop_file=stop_file,
                success=False,
                message=f"HM+ANSA 并行协调器异常退出：{exc}",
            )
            write_json(
                runs_dir / f"parallel_summary_{args.stamp}.json",
                {
                    "task_id": args.stamp,
                    "success": False,
                    "status": "failed",
                    "severity": "failed",
                    "stopped": False,
                    "warnings": [],
                    "errors": [str(exc)],
                    "error": str(exc),
                },
            )
            state_path = runs_dir / f"parallel_state_{args.stamp}.json"
            summary_path = runs_dir / f"parallel_summary_{args.stamp}.json"
            report_path = runs_dir / f"parallel_report_{args.stamp}.txt"
            state = new_parallel_state(args.stamp, state_path=state_path, summary_path=summary_path, report_path=report_path)
            state["success"] = False
            state["severity"] = "failed"
            state["errors"] = [str(exc)]
            state["hm"]["status"] = "unknown"
            state["ansa"]["status"] = "unknown"
            state["merge"]["status"] = "failed"
            update_parallel_state(state_path, state, stage="failed", severity="failed", message=f"并行协调器异常退出：{exc}")
            write_parallel_report(
                report_path,
                {
                    "task_id": args.stamp,
                    "success": False,
                    "status": "failed",
                    "severity": "failed",
                    "stopped": False,
                    "state_json": str(state_path),
                    "warnings": [],
                    "errors": [str(exc)],
                    "hm": {},
                    "ansa": {},
                    "merge": {},
                },
            )
            log(f"Parallel state: {state_path}")
            log(f"Parallel report: {report_path}")
        except Exception:
            pass
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
