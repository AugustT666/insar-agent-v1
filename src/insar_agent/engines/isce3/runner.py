from __future__ import annotations


def build_workflow_command(
    workflow: str,
    runconfig_path: str,
    conda_env: str | None = None,
) -> list[str]:
    """
    Build the command list to execute an ISCE3 NISAR workflow.

    Per the SKILL.md constraint, workflows are always invoked as:
        python -m nisar.workflows.<workflow> <runconfig_path>

    When a conda_env is specified, wraps with `conda run`:
        conda run -n <env> --no-capture-output python -m nisar.workflows.<workflow> <runconfig_path>
    """
    inner = ["python", "-m", f"nisar.workflows.{workflow}", runconfig_path]
    if conda_env:
        return ["conda", "run", "-n", conda_env, "--no-capture-output"] + inner
    return inner
