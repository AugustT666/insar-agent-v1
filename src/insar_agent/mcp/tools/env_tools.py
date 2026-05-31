"""MCP tools: env_tools (registered on the shared FastMCP)."""

from __future__ import annotations

from insar_agent.mcp._app import *  # noqa: F403  (foundation: imports + constants + mcp)
from insar_agent.mcp._helpers import *  # noqa: F403  (shared helpers)


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

    # Check MCP registration via claude mcp list
    mcp_status: dict = {"registered": False, "server_name": "insar-mcp-server"}
    try:
        result = subprocess.run(
            ["claude", "mcp", "list"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and "insar-mcp-server" in result.stdout:
            mcp_status["registered"] = True
            # Extract actual connected server name(s).
            # Each line format: "<server-name>: <command> - ✓ Connected"
            # Server names may contain colons (e.g. plugin:foo:bar), so split on ": " not ":"
            connected_insar: list[str] = []
            for line in result.stdout.splitlines():
                if "insar" in line.lower() and "✓" in line:
                    parts = line.split(": ", 1)
                    if parts:
                        connected_insar.append(parts[0].strip())
            if connected_insar:
                # Prefer the plugin-namespaced form so agents use the correct name
                # in readMcpResource / listMcpResources calls.
                plugin_form = [s for s in connected_insar if s.startswith("plugin:")]
                mcp_status["server_name"] = plugin_form[0] if plugin_form else connected_insar[0]
        mcp_status["raw_output"] = result.stdout.strip()[:500]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        mcp_status["error"] = "claude CLI not found or timed out"

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
