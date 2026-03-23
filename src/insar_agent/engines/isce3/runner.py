from __future__ import annotations


def build_workflow_command(workflow: str, runconfig_path: str) -> list[str]:
    return ["python", "-m", f"nisar.workflows.{workflow}", runconfig_path]
