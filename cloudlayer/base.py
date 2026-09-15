"""The portability seam.

Eleven methods. Every managed ML platform sells you the same eleven operations under
different names; writing this once is the difference between knowing a product and
knowing the category. `generate` is the newest of them and the one the vendors are
currently busiest renaming.

You implement exactly ONE of aws.py, azure.py, or gcp.py. Lab 1 needs only `upload`,
`download`, and `push_image`. The rest raise NotImplementedError until the lab that
needs them, which is deliberate — do not implement ahead.

Nothing outside cloudlayer/ may import a provider SDK.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from google.cloud import aiplatform, storage


class CloudAdapter(ABC):
    """Provider-neutral interface. The grader only ever calls these."""

    def __init__(self, cfg) -> None:
        self.cfg = cfg

    # --- Lab 1 ---------------------------------------------------------------
    @abstractmethod
    def upload(self, local_path: str, key: str) -> str:
        """Upload a file under BLOB_URI. Returns the full URI of the stored object."""

    @abstractmethod
    def download(self, uri: str, local_path: str) -> None:
        """Fetch an object to a local path. Creates parent directories."""

    @abstractmethod
    def push_image(self, local_tag: str) -> str:
        """Push a locally built image to CONTAINER_REGISTRY. Returns the remote reference,
        which must be digest-pinned (repo@sha256:...), not tag-pinned."""

    # --- Lab 2 ---------------------------------------------------------------
    def submit_training(self, image_uri: str, args: dict[str, Any]) -> str:
        raise NotImplementedError("Lab 2")

    def wait_training(self, job_id: str) -> dict[str, Any]:
        raise NotImplementedError("Lab 2")

    def register_model(self, model_uri: str, name: str) -> str:
        raise NotImplementedError("Lab 2")

    # --- Lab 3 ---------------------------------------------------------------
    def deploy(self, model_ref: str, endpoint: str, instance: str) -> str:
        raise NotImplementedError("Lab 3")

    def invoke(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("Lab 3")

    # --- Lab 4 ---------------------------------------------------------------
    def emit_metric(self, name: str, value: float, unit: str = "None") -> None:
        raise NotImplementedError("Lab 4")

    # --- Lab 5 ---------------------------------------------------------------
    def generate(self, prompt: str, params: dict[str, Any]) -> dict[str, Any]:
        """Call a managed LLM endpoint once. Returns at least:

            {"response": str, "input_tokens": int,
             "output_tokens": int, "latency_ms": int}

        Token counts must be read from the provider's own usage fields. Estimating them
        by counting words produces a cost report built on a number you made up, and
        every provider tokenises differently.

        `params` carries the knobs worth exposing at the seam — `max_output_tokens`
        above all, since output tokens dominate the bill. Provider-specific options
        belong here in Layer 3, never in the caller.
        """
        raise NotImplementedError("Lab 5")

    def teardown(self, tags: dict[str, str]) -> list[str]:
        """Delete every resource carrying these tags. Returns what was deleted.

        Deletion is asynchronous on all three providers — returning successfully does
        not mean the resource is gone. Re-check, and check the bill.
        """
        aiplatform.init(
            project=self.cfg.project_id,
            location=self.cfg.region,
        )

        deleted_resources: list[str] = []

        # Active states eligible for cancellation
        active_states = {
            aiplatform.gapic.JobState.JOB_STATE_PENDING,
            aiplatform.gapic.JobState.JOB_STATE_RUNNING,
            aiplatform.gapic.JobState.JOB_STATE_QUEUED,
        }

        # 1. Cancel Active Custom Jobs (Lab 2)
        try:
            jobs = aiplatform.CustomJob.list()
            for job in jobs:
                # Check if job state is active
                if job.state in active_states:
                    # Match labels in Python instead of using GCP API server-side filter
                    job_labels = getattr(job, "labels", {}) or {}
                    if all(job_labels.get(k) == v for k, v in tags.items()):
                        res_name = job.resource_name
                        job.cancel()
                        deleted_resources.append(f"CustomJob (Cancelled): {res_name}")
        except Exception as e:
            print(f"Error cancelling custom jobs: {e}")

        # 2. Delete Deployed Endpoints (Lab 3)
        try:
            endpoints = aiplatform.Endpoint.list()
            for endpoint in endpoints:
                ep_labels = getattr(endpoint, "labels", {}) or {}
                if all(ep_labels.get(k) == v for k, v in tags.items()):
                    res_name = endpoint.resource_name
                    endpoint.delete(force=True)
                    deleted_resources.append(f"Endpoint: {res_name}")
        except Exception as e:
            print(f"Error deleting endpoints: {e}")

        # 3. Delete Registered Models (Lab 2 / Lab 3)
        try:
            models = aiplatform.Model.list()
            for model in models:
                m_labels = getattr(model, "labels", {}) or {}
                if all(m_labels.get(k) == v for k, v in tags.items()):
                    res_name = model.resource_name
                    model.delete()
                    deleted_resources.append(f"Model: {res_name}")
        except Exception as e:
            print(f"Error deleting models: {e}")

        return deleted_resources


class LocalAdapter(CloudAdapter):
    """Filesystem stand-in so Lab 1 runs before your cloud account is ready.

    Acceptable for developing Lab 1. NOT acceptable for submission — your submitted
    Lab 1 must upload to real object storage and push to a real registry.
    """

    def upload(self, local_path: str, key: str) -> str:
        import shutil
        from pathlib import Path

        dest = Path(self.cfg.data_dir) / "_local_blob" / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local_path, dest)
        return f"local://{dest}"

    def download(self, uri: str, local_path: str) -> None:
        import shutil
        from pathlib import Path

        src = uri.removeprefix("local://")
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, local_path)

    def push_image(self, local_tag: str) -> str:
        raise NotImplementedError(
            "LocalAdapter cannot push images. Implement your provider's adapter for Lab 1 submission."
        )
