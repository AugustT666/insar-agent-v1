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
        }
    """
    from insar_agent.core.host_probe import probe_host

    try:
        return probe_host()
    except Exception as exc:  # never break the advisory flow on a probe error
        return {"error": "probe_failed", "message": str(exc)}


@mcp.tool()
def insar_check_env() -> dict:
    """
    Check the project environment status: conda envs, MCP registration, and skills.

    Probes each expected conda environment by attempting to import its key package.
    Also checks MCP server registration and installed Claude Code skills.

    Returns:
        {
            "envs": {"isce3": {"status": "ok"|"missing", "version": ...}, ...},
            "mcp": {"registered": bool, "server_name": str},
            "skills": {"installed": [...], "missing": [...]},
            "install_hints": {env_name: "conda install ..." for missing envs},
        }
    """
    envs_to_check = {
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
    install_hints: dict[str, str] = {}

    for env_name, cfg in envs_to_check.items():
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
                install_hints[env_name] = cfg["install"]
        except FileNotFoundError:
            env_results[env_name] = {"status": "missing", "error": "conda not found in PATH"}
            install_hints[env_name] = cfg["install"]
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
        "mcp": mcp_status,
        "skills": skills_status,
        "install_hints": install_hints,
    }
