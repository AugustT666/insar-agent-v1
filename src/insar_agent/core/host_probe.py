"""Engine-agnostic local hardware probe for compute-efficiency advice.

Read-only introspection of the host the InSAR processing will run on: logical /
usable CPU count, total / available memory, and GPUs. The param-advisor subagent
calls this (so its num_proc / parallelism advice is grounded in the real machine)
and a server-side num_proc ceiling can reuse the same numbers.

Best-effort and POSIX-friendly: every probe degrades to ``None`` / ``[]`` rather
than raising, so an advisory flow never breaks on an unsupported host.
"""
from __future__ import annotations

import os
import shutil
import subprocess


def _logical_cpu_count() -> int:
    return os.cpu_count() or 1


def _usable_cpu_count() -> int:
    """CPUs actually available to this process — honors cgroup/affinity limits."""
    try:
        return len(os.sched_getaffinity(0))  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return _logical_cpu_count()


def _total_memory_gb() -> float | None:
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return round(pages * page_size / (1024 ** 3), 1)
    except (ValueError, OSError, AttributeError):
        return None


def _available_memory_gb() -> float | None:
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return round(int(line.split()[1]) / (1024 ** 2), 1)
    except (OSError, ValueError, IndexError):
        pass
    return None


def _detect_gpus() -> list[dict]:
    smi = shutil.which("nvidia-smi")
    if not smi:
        return []
    try:
        out = subprocess.run(
            [smi, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    gpus: list[dict] = []
    for line in out.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2 and parts[0]:
            try:
                vram = round(float(parts[1]) / 1024, 1)
            except ValueError:
                vram = None
            gpus.append({"name": parts[0], "total_vram_gb": vram})
    return gpus


def _suggest_num_proc_upper_bound(usable_cpus: int, total_memory_gb: float | None) -> int:
    """Conservative ceiling: half the usable cores, capped by a memory budget."""
    by_cpu = max(1, usable_cpus // 2)
    if total_memory_gb is None:
        return min(by_cpu, 4)
    if total_memory_gb >= 64:
        return by_cpu
    if total_memory_gb >= 32:
        return min(by_cpu, 8)
    if total_memory_gb >= 16:
        return min(by_cpu, 4)
    return min(by_cpu, 2)


# Phase-unwrapping methods, two classes:
#  - ISCE2-builtin (snaphu, snaphu2stage, icu): ship with ISCE2; their real
#    availability is tied to ISCE2 being importable in the chosen run conda_env,
#    which a host-level probe cannot confirm — listed as candidates with the
#    requirement noted (insar_check_env reports capable.isce2 per env).
#  - standalone (phunwrap): separate executables; detected on PATH.
_ISCE2_UNWRAP_REQUIRES = "requires ISCE2 in the run conda_env (see insar_check_env capable.isce2)"


def _detect_unwrap_methods() -> dict:
    """Engine-agnostic catalog of locally selectable phase-unwrapping methods.

    Avoids hardcoding the method list in every workflow skill: skills call
    insar_probe_host and present whatever is available here.
    """
    methods: dict = {
        name: {"available": True, "source": "isce2-builtin", "gpu": False,
               "requires": _ISCE2_UNWRAP_REQUIRES}
        for name in ("snaphu", "snaphu2stage", "icu")
    }
    # Standalone GPU-capable unwrapper(s) discovered on PATH.
    phunwrap = shutil.which("phunwrap")
    methods["phunwrap"] = {
        "available": phunwrap is not None,
        "source": "path",
        "gpu": True,
        "path": phunwrap,
    }
    return methods


def _recommend_unwrap_method(methods: dict, has_gpu: bool) -> str:
    """Default unwrap method: a GPU-capable available method when a GPU is present,
    otherwise snaphu (robust, mature default). Scene-specific tuning (cost mode,
    ntiles, low-coherence robustness) is left to the param-advisor subagent.
    """
    if has_gpu:
        for name, info in methods.items():
            if info.get("gpu") and info.get("available"):
                return name
    return "snaphu"


def probe_host() -> dict:
    logical = _logical_cpu_count()
    usable = _usable_cpu_count()
    total_mem = _total_memory_gb()
    gpus = _detect_gpus()
    unwrap_methods = _detect_unwrap_methods()
    return {
        "logical_cpu_count": logical,
        "usable_cpu_count": usable,
        "total_memory_gb": total_mem,
        "available_memory_gb": _available_memory_gb(),
        "gpus": gpus,
        "suggested_num_proc_upper_bound": _suggest_num_proc_upper_bound(usable, total_mem),
        "unwrap_methods": unwrap_methods,
        "unwrap_recommended": _recommend_unwrap_method(unwrap_methods, has_gpu=bool(gpus)),
    }
