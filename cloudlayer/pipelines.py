"""Lab 5 — compile pipeline/pipeline.yaml into your provider's pipeline service.

This module is Layer 3, so provider SDKs are allowed here and nowhere else. The DAG stays
in YAML; only the translation lives here. That separation is what you argue for or against
in Lab 5 Task 4.

Implement ONE compile function, for your provider.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

SPEC = Path(__file__).resolve().parents[1] / "pipeline" / "pipeline.yaml"


def load_spec(path: Path = SPEC) -> dict[str, Any]:
    """Read the neutral DAG and expand ${VAR} references from the environment."""
    raw = path.read_text()
    for key, value in os.environ.items():
        raw = raw.replace(f"${{{key}}}", value)
    return yaml.safe_load(raw)


def compile_aws(spec: dict[str, Any]):
    """SageMaker Pipelines."""
    raise NotImplementedError("TODO Lab 5: build a sagemaker.workflow.pipeline.Pipeline")


def compile_azure(spec: dict[str, Any]):
    """Azure ML Pipelines."""
    raise NotImplementedError("TODO Lab 5: build an azure.ai.ml pipeline job")


def compile_gcp(spec: dict[str, Any], output_path: str = "pipeline/pipeline_vertex.json"):
    """Vertex AI Pipelines (Kubeflow Pipelines v2 Compiler)."""
    from kfp import compiler, dsl, components

    pipeline_name = spec.get("name", "itcs355-training-pipeline")
    steps = {step["name"]: step for step in spec.get("steps", [])}

    # Factory for standard container components built via component YAML text (bypasses Python decorators completely)
    def create_container_component(step_cfg: dict[str, Any]):
        name = step_cfg["name"].replace("-", "_")
        image = step_cfg["image"]
        cmd = step_cfg["command"]

        component_yaml = f"""
name: {name}
implementation:
  container:
    image: {image}
    command: {cmd}
"""
        return components.load_component_from_text(component_yaml)

    # Factory for evaluation component emitting an explicit string parameter output
    def create_eval_component(step_cfg: dict[str, Any]):
        name = step_cfg["name"].replace("-", "_")
        image = step_cfg["image"]
        cmd = step_cfg["command"]

        component_yaml = f"""
name: {name}
outputs:
  - {{name: gate_decision, type: String}}
implementation:
  container:
    image: {image}
    command: {cmd}
    args:
      - --output-gate-file
      - {{outputPath: gate_decision}}
"""
        return components.load_component_from_text(component_yaml)

    @dsl.pipeline(name=pipeline_name)
    def kfp_dag():
        executed_tasks = {}

        # 1. Ingest
        if "ingest" in steps:
            comp = create_container_component(steps["ingest"])
            executed_tasks["ingest"] = comp()

        # 2. Validate
        if "validate" in steps:
            comp = create_container_component(steps["validate"])
            task = comp()
            if "ingest" in executed_tasks:
                task.after(executed_tasks["ingest"])
            executed_tasks["validate"] = task

        # 3. Train
        if "train" in steps:
            comp = create_container_component(steps["train"])
            task = comp()
            if "validate" in executed_tasks:
                task.after(executed_tasks["validate"])
            executed_tasks["train"] = task

        # 4. Evaluate
        if "evaluate" in steps:
            comp = create_eval_component(steps["evaluate"])
            task = comp()
            if "train" in executed_tasks:
                task.after(executed_tasks["train"])
            executed_tasks["evaluate"] = task

        # 5 & 6. Conditional Gate: Register and Deploy Staging
        if "evaluate" in executed_tasks and "register" in steps:
            eval_task = executed_tasks["evaluate"]

            # Gate condition evaluation on task output string
            with dsl.If(eval_task.outputs["gate_decision"] == "pass", name="gate-passed-condition"):
                reg_comp = create_container_component(steps["register"])
                reg_task = reg_comp()

                if "deploy_staging" in steps:
                    dep_comp = create_container_component(steps["deploy_staging"])
                    dep_comp().after(reg_task)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    compiler.Compiler().compile(
        pipeline_func=kfp_dag,
        package_path=output_path,
    )
    print(f"✅ Successfully compiled neutral DAG to Vertex AI KFP spec: {output_path}")
    return output_path


COMPILERS = {"aws": compile_aws, "azure": compile_azure, "gcp": compile_gcp}


def compile_for(provider: str, spec: dict[str, Any] | None = None):
    spec = spec or load_spec()
    try:
        return COMPILERS[provider.lower()](spec)
    except KeyError:
        raise ValueError(f"No pipeline compiler for {provider!r}") from None
