"""MCP tools: env_tools (registered on the shared FastMCP)."""

from __future__ import annotations

from insar_agent.mcp._app import *  # noqa: F403  (foundation: imports + constants + mcp)
from insar_agent.mcp._helpers import *  # noqa: F403  (shared helpers)


@mcp.tool()
def insar_probe_host() -> dict:
    """
    Probe local hardware (CPU / memory / GPU) for compute-efficiency advice.

    Read-only, deterministic, structured read of the machine InSAR processing will
    run on, so the param-advisor subagent can ground its num_proc / parallelism
    advice in the actual host (and a server-side num_proc ceiling can reuse it):

        {
            "logical_cpu_count": int,
            "usable_cpu_count": int,        # honors cgroup/affinity limits
            "total_memory_gb": float | None,
            "available_memory_gb": float | None,
            "gpus": [{"name": str, "total_vram_gb": float | None}, ...],
            "suggested_num_proc_upper_bound": int,
            # Locally selectable phase-unwrapping methods (so skills/param-advisor
            # discover them dynamically instead of hardcoding a static enum).
            # ISCE2-builtin methods (snaphu/snaphu2stage/icu) are listed as
            # candidates with a "requires" note (real availability follows ISCE2
            # in the run env — see insar_check_env capable.isce2); standalone GPU
            # unwrappers (e.g. phunwrap) are detected on PATH.
            "unwrap_methods": {
                "<name>": {"available": bool, "source": "isce2-builtin"|"path",
                           "gpu": bool, "requires"|"path": str|None},
                ...
            },
            "unwrap_recommended": str,      # GPU-capable method if a GPU is present, else "snaphu"
        }
    """
    from insar_agent.core.host_probe import probe_host

    try:
        return probe_host()
    except Exception as exc:  # never break the advisory flow on a probe error
        return {"error": "probe_failed", "message": str(exc)}


def _discover_conda_envs() -> list[tuple[str, str]]:
    """Return list of (env_name, env_path) for all local conda envs.

    Runs ``conda env list --json`` and parses the ``envs`` paths.
    The base/root env (whose path has no ``envs/<name>`` suffix) is labeled "base".
    Returns an empty list if conda is not found or the command fails.
    """
    try:
        result = subprocess.run(
            ["conda", "env", "list", "--json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return []
        data = json.loads(result.stdout)
        envs_paths: list[str] = data.get("envs", [])
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return []

    named: list[tuple[str, str]] = []
    for path in envs_paths:
        p = Path(path)
        # The base/root env path does not contain an "envs" component; its
        # basename is typically "base", "miniconda3", "anaconda3", etc.
        # We detect it by checking whether its parent is named "envs".
        if p.parent.name == "envs":
            env_name = p.name
        else:
            env_name = "base"
        named.append((env_name, path))
    return named


# Combined probe: one subprocess call per env, avoids multiple conda-run invocations.
_COMBINED_PROBE = (
    "import json, sys;"
    "caps = {'isce2': None, 'isce3': None, 'mintpy': None};"
    "exec(\"\"\"try:\\n import isce\\n caps['isce2'] = str(getattr(isce, '__version__', 'installed'))\\nexcept Exception: pass\"\"\");"
    "exec(\"\"\"try:\\n import isce3\\n caps['isce3'] = str(getattr(isce3, '__version__', 'installed'))\\nexcept Exception: pass\"\"\");"
    "exec(\"\"\"try:\\n import mintpy\\n caps['mintpy'] = str(getattr(mintpy, '__version__', 'installed'))\\nexcept Exception: pass\"\"\");"
    "print(json.dumps(caps))"
)


def _probe_env_capabilities(env_name: str) -> dict[str, str | None]:
    """Run the combined capability probe in the given conda env.

    Returns a dict with keys isce2/isce3/mintpy, values are version strings or None.
    Tolerates all errors (timeout, import failure, bad JSON) → returns all-None.
    """
    null_caps: dict[str, str | None] = {"isce2": None, "isce3": None, "mintpy": None}
    try:
        result = subprocess.run(
            ["conda", "run", "-n", env_name, "--no-capture-output",
             "python", "-c", _COMBINED_PROBE],
            capture_output=True,
            text=True,
            timeout=30,
            env=_conda_safe_env(),
        )
        if result.returncode != 0:
            return null_caps
        # The probe prints JSON on the last line (conda may emit prefix noise before it).
        for line in reversed(result.stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                return json.loads(line)
        return null_caps
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return null_caps


@mcp.tool()
def insar_check_env() -> dict:
    """
    Check the project environment status: conda envs, MCP registration, and skills.

    Discovers ACTUAL local conda environments (not a hardcoded list) and probes
    each one for ISCE2, ISCE3, and MintPy capabilities in a single subprocess call.

    Returns:
        {
            "envs": {"<env_name>": {"status": "ok"|"missing", "version": ...}, ...},
            "discovered_envs": {
                "<real_env_name>": {"isce2": "<ver>"|null, "isce3": ..., "mintpy": ...},
                ...
            },
            "capable": {
                "isce2": ["<env_names_that_have_isce2>"],
                "isce3": [...],
                "mintpy": [...],
            },
            "mcp": {"registered": bool, "server_name": str},
            "skills": {"installed": [...], "missing": [...]},
            "install_hints": {cap: "conda create ..." for caps with no capable env},
        }
    """
    # --- Real conda env discovery ---
    env_list = _discover_conda_envs()

    discovered_envs: dict[str, dict[str, str | None]] = {}
    capable: dict[str, list[str]] = {"isce2": [], "isce3": [], "mintpy": []}

    for env_name, _env_path in env_list:
        if env_name == "base":
            # Skip base env — it typically doesn't have InSAR packages
            continue
        caps = _probe_env_capabilities(env_name)
        discovered_envs[env_name] = caps
        for cap in ("isce2", "isce3", "mintpy"):
            if caps.get(cap) is not None:
                capable[cap].append(env_name)

    # Build install_hints only for capabilities with no capable env.
    _cap_install_hints = {
        "isce2": "conda create -n <your_env_name> -c conda-forge isce2 -y",
        "isce3": "conda create -n <your_env_name> -c conda-forge isce3 -y",
        "mintpy": "conda create -n <your_env_name> -c conda-forge mintpy -y",
    }
    install_hints: dict[str, str] = {
        cap: hint
        for cap, hint in _cap_install_hints.items()
        if not capable.get(cap)
    }

    # --- Legacy per-env status block (kept for backward compat, based on hardcoded names) ---
    # These probe the well-known env names that may or may not exist on this machine.
    # Authoritative signal is discovered_envs / capable above.
    _legacy_envs_to_check = {
        "isce3gpu": {
            "probe": "import isce3; print(isce3.__version__)",
            "install": "conda create -n isce3gpu -c conda-forge isce3 cudatoolkit -y",
        },
        "isce3": {
            "probe": "import isce3; print(isce3.__version__)",
            "install": "conda create -n isce3 -c conda-forge isce3 -y",
        },
        "mintpy": {
            "probe": "import mintpy; print(mintpy.__version__)",
            "install": "conda create -n mintpy -c conda-forge mintpy -y",
        },
        "isce2": {
            "probe": "import isce; print(isce.__version__)",
            "install": "conda create -n isce2 -c conda-forge isce2 -y",
        },
    }

    env_results: dict[str, dict] = {}

    for env_name, cfg in _legacy_envs_to_check.items():
        try:
            result = subprocess.run(
                ["conda", "run", "-n", env_name, "--no-capture-output",
                 "python", "-c", cfg["probe"]],
                capture_output=True,
                text=True,
                timeout=30,
                env=_conda_safe_env(),
            )
            if result.returncode == 0:
                version = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "unknown"
                env_results[env_name] = {"status": "ok", "version": version}
            else:
                env_results[env_name] = {"status": "missing", "error": result.stderr.strip()[:200]}
        except FileNotFoundError:
            env_results[env_name] = {"status": "missing", "error": "conda not found in PATH"}
        except subprocess.TimeoutExpired:
            env_results[env_name] = {"status": "timeout", "error": "probe timed out after 30s"}

    # Determine MCP registration. This tool only executes because the agent
    # reached the insar MCP server, so "registered" must not hinge on a fresh
    # `claude mcp list`: under inline `--plugin-dir` loading the session-only
    # server is invisible to a new CLI process (and `claude` may be off PATH).
    mcp_status: dict = {"registered": False, "server_name": "insar-mcp-server"}

    # Signal 1 (reliable under plugin loading): Claude Code exports
    # CLAUDE_PLUGIN_ROOT into plugin-spawned MCP server processes, for both
    # inline `--plugin-dir` and marketplace installs. Its presence means we ARE
    # the connected plugin server, exposed as plugin:<plugin>:<server>.
    if os.environ.get("CLAUDE_PLUGIN_ROOT"):
        mcp_status["registered"] = True
        mcp_status["server_name"] = "plugin:insar-agent-plugin:insar-mcp-server"
        mcp_status["detected_via"] = "plugin_runtime"

    # Signal 2 (best-effort name refinement): `claude mcp list` resolves the
    # exact registered name for installs the CLI can see (project .mcp.json or
    # marketplace). A miss here never downgrades registration; it simply cannot
    # see session-only plugin servers.
    try:
        result = subprocess.run(
            ["claude", "mcp", "list"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        mcp_status["raw_output"] = result.stdout.strip()[:500]
        if result.returncode == 0 and "insar-mcp-server" in result.stdout:
            # Each line: "<server-name>: <command> - ✔ Connected". Server names
            # may contain colons (plugin:foo:bar), so split on ": " and match the
            # stable "Connected" text rather than a specific check glyph.
            connected_insar: list[str] = []
            for line in result.stdout.splitlines():
                if "insar-mcp-server" in line and "connect" in line.lower():
                    name = line.split(": ", 1)[0].strip()
                    if name:
                        connected_insar.append(name)
            if connected_insar:
                mcp_status["registered"] = True
                # Prefer the plugin-namespaced form so agents use the correct name
                # in readMcpResource / listMcpResources calls.
                plugin_form = [s for s in connected_insar if s.startswith("plugin:")]
                mcp_status["server_name"] = plugin_form[0] if plugin_form else connected_insar[0]
                mcp_status["detected_via"] = "claude_mcp_list"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        mcp_status["probe_error"] = "claude CLI not reachable from MCP server; used runtime signal"

    # Check installed/configured skills for both Claude Code and OpenCode clients.
    expected_skills = [
        "insar-agent", "env-setup", "data-prep", "data-prep-nisar", "data-prep-sentinel",
        "d-insar-isce3", "stack-insar-isce3", "param-advisor", "mintpy",
        "d-insar-isce2", "stack-insar-isce2",
    ]
    claude_installed_skills: list[str] = []
    try:
        result = subprocess.run(
            ["claude", "plugin", "list"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        raw = result.stdout
        # When the insar-agent plugin is installed, all sub-skills are accessible
        # via the Skill tool even though they don't appear individually in plugin list.
        # Check for the plugin entry ("insar-agent-plugin") rather than each sub-skill name.
        if "insar-agent-plugin" in raw:
            claude_installed_skills = list(expected_skills)
        else:
            claude_installed_skills = [s for s in expected_skills if s in raw]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    repo_root = Path(__file__).resolve().parents[3]
    opencode_sources = _configured_opencode_skill_sources(repo_root)
    opencode_installed_skills = [
        skill
        for skill in expected_skills
        if any((source / skill / "SKILL.md").exists() for source in opencode_sources)
    ]
    installed_skills = sorted(set(claude_installed_skills) | set(opencode_installed_skills))
    missing_skills = [s for s in expected_skills if s not in installed_skills]

    skills_status = {
        "installed": installed_skills,
        "missing": missing_skills,
        "claude": {
            "installed": claude_installed_skills,
            "missing": [s for s in expected_skills if s not in claude_installed_skills],
        },
        "opencode": {
            "configured_sources": [str(source) for source in opencode_sources],
            "installed": opencode_installed_skills,
            "missing": [s for s in expected_skills if s not in opencode_installed_skills],
        },
    }
    if missing_skills:
        skills_status["hint"] = (
            "Configure OpenCode skills.sources for /home/august/insar-agent/skills, "
            "or install the Claude Code project plugin when using Claude Code."
        )

    return {
        "envs": env_results,
        "discovered_envs": discovered_envs,
        "capable": capable,
        "mcp": mcp_status,
        "skills": skills_status,
        "install_hints": install_hints,
    }
