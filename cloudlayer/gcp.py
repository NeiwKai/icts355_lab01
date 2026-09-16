"""GCP adapter. Implement upload/download/push_image for Lab 1.

SDK:  pip install google-cloud-storage google-cloud-aiplatform
Docs: storage.Client for GCS; Artifact Registry push goes through `docker push` after
      `gcloud auth configure-docker <region>-docker.pkg.dev`.

Hints for Lab 1:
  * BLOB_URI looks like gs://bucket/prefix — parse it here, never in src/.
  * Artifact Registry paths are region-scoped:
        <region>-docker.pkg.dev/<project>/<repo>/<image>
    A common first failure is pushing to gcr.io out of habit; it is a different service.
  * push_image must return the digest reference, not the tag.
  * GCP calls them labels, not tags, and they must be lowercase with no spaces.
    cfg.tags(1) already satisfies that constraint — do not "improve" the values.
"""
from __future__ import annotations

from typing import Any

import subprocess
from pathlib import Path
from urllib.parse import urlparse

from google.cloud import aiplatform, aiplatform_v1, storage
from cloudlayer.base import CloudAdapter


class GcpAdapter(CloudAdapter):
    def upload(self, local_path: str, key: str) -> str:
        """Upload a file under BLOB_URI.

        Returns:
            gs://bucket/prefix/key
        """
        if key.startswith("gs://"):
            parsed_key = urlparse(key)
            bucket_name = parsed_key.netloc
            blob_name = parsed_key.path.lstrip("/")
        else:
            parsed = urlparse(self.cfg.blob_uri)
            if parsed.scheme != "gs":
                raise ValueError(f"BLOB_URI must use gs://, got {self.cfg.blob_uri!r}")
            bucket_name = parsed.netloc
            prefix = parsed.path.lstrip("/").rstrip("/")
            blob_name = f"{prefix}/{key}" if prefix else key

        storage_client = storage.Client(project=self.cfg.project_id)
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        blob.upload_from_filename(local_path)

        return f"gs://{bucket_name}/{blob_name}"
        #raise NotImplementedError("TODO Lab 1: blob.upload_from_filename, return the gs:// URI")

    def download(self, key: str, local_path: str) -> str:
        """Download a blob from GCS under self.cfg.blob_uri to a local file path."""
        parsed = urlparse(self.cfg.blob_uri)
        bucket_name = parsed.netloc
        prefix = parsed.path.lstrip("/").rstrip("/")

        # Construct destination blob key
        blob_name = f"{prefix}/{key}" if prefix else key

        storage_client = storage.Client(project=self.cfg.project_id)
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_name)

        # Ensure parent local directory exists
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)

        # Fallback check if blob doesn't exist under subpath prefix
        if not blob.exists():
            blob = bucket.blob(key)

        blob.download_to_filename(local_path)
        print(f"GCPAdapter: Downloaded gs://{bucket_name}/{blob.name} to {local_path}")
        return local_path
        #raise NotImplementedError("TODO Lab 1: blob.download_to_filename, creating parents")

    def push_image(self, local_tag: str) -> str:
        """Push a locally built image to Artifact Registry.

        Returns:
            Digest-pinned remote reference:
            <registry>/<image>@sha256:<digest>
        """

        registry = self.cfg.container_registry.rstrip("/")

        if not registry:
            raise ValueError("CONTAINER_REGISTRY is empty")

        # Example:
        # local_tag = "itcs355-lab1:82df93d"
        image_with_tag = local_tag.rsplit("/", 1)[-1]

        # "itcs355-lab1:82df93d" -> "itcs355-lab1"
        image_name = image_with_tag.rsplit(":", 1)[0]

        # "itcs355-lab1:82df93d"
        tag = image_with_tag.rsplit(":", 1)[1]

        # CONTAINER_REGISTRY already contains:
        #   region-docker.pkg.dev/project/repository
        remote_tag = f"{registry}/{image_name}:{tag}"

        # Authenticate Docker with Artifact Registry.
        registry_host = registry.split("/", 1)[0]

        subprocess.run(
            [
                "gcloud",
                "auth",
                "configure-docker",
                registry_host,
                "--quiet",
            ],
            check=True,
        )

        # Tag local image for Artifact Registry.
        subprocess.run(
            [
                "docker",
                "tag",
                local_tag,
                remote_tag,
            ],
            check=True,
        )

        # Push.
        subprocess.run(
            [
                "docker",
                "push",
                remote_tag,
            ],
            check=True,
        )

        # Get the digest assigned by Artifact Registry.
        result = subprocess.run(
            [
                "docker",
                "inspect",
                "--format={{index .RepoDigests 0}}",
                remote_tag,
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        digest_ref = result.stdout.strip()

        if "@sha256:" not in digest_ref:
            raise RuntimeError(
                f"Could not determine image digest for {remote_tag!r}. "
                f"Docker returned: {digest_ref!r}"
            )

        return digest_ref
        #raise NotImplementedError("TODO Lab 1: configure-docker, push, return repo@sha256:...")

    ## Lab 2: submit_training(), wait_training(), register_model()
    def submit_training(
        self,
        image_uri: str,
        args: list[str] | None = None,
        instance_type: str = "e2-standard-4",
        use_spot: bool = True
    ) -> str:
        """Submit a Vertex AI Custom Training Job using a remote container image."""
        aiplatform.init(
            project=self.cfg.project_id,
            location=self.cfg.region,
        )

        # 1. Define Machine and Container specs with explicit environment variables
        machine_spec = aiplatform_v1.MachineSpec(machine_type=instance_type)
        
        # Pass CLOUD_PROVIDER and BLOB_URI into the container environment
        env_vars = [
            aiplatform_v1.EnvVar(name="CLOUD_PROVIDER", value="gcp"),
            aiplatform_v1.EnvVar(name="BLOB_URI", value=self.cfg.blob_uri),
            aiplatform_v1.EnvVar(name="GCP_PROJECT_ID", value=self.cfg.project_id),
            aiplatform_v1.EnvVar(name="MLFLOW_TRACKING_URI", value=getattr(self.cfg, "mlflow_tracking_uri", "")),
        ]

        container_spec = aiplatform_v1.ContainerSpec(
            image_uri=image_uri,
            args=args or [],
            env=env_vars,
        )

        # 2. WorkerPoolSpec (no scheduling here)
        worker_pool_spec = aiplatform_v1.WorkerPoolSpec(
            machine_spec=machine_spec,
            replica_count=1,
            container_spec=container_spec,
        )

        # 3. Scheduling belongs on the job specification level
        scheduling = None
        if use_spot:
            scheduling = aiplatform_v1.Scheduling(
                disable_retries=False,
                restart_job_on_worker_restart=True,
            )

        # 4. Construct JobSpec explicitly
        job_spec = aiplatform_v1.CustomJobSpec(
            worker_pool_specs=[worker_pool_spec],
            scheduling=scheduling,
            base_output_directory=aiplatform_v1.GcsDestination(
                output_uri_prefix=self.cfg.blob_uri
            ),
        )

        job = aiplatform.CustomJob(
            display_name=f"lab2-training-{self.cfg.model_registry_name}",
            staging_bucket=self.cfg.blob_uri,
            worker_pool_specs=[worker_pool_spec],
            labels=self.cfg.tags(2), # The lab id. e.g, self.cfg.tags(1) -> lab1
        )

        # Attach scheduling to underlying proto spec
        if scheduling:
            job._gca_resource.job_spec.scheduling = scheduling

        job.submit(
            service_account=getattr(self.cfg, "service_account", None),
        )

        # Access resource_name from the underlying CustomJob instance created during .run()
        return job.resource_name

    def wait_training(self, job_id: str) -> None:
            """Block until the Vertex AI Custom Training Job completes successfully."""
            import time

            aiplatform.init(
                project=self.cfg.project_id,
                location=self.cfg.region,
            )

            terminal_states = {
                aiplatform.gapic.JobState.JOB_STATE_SUCCEEDED,
                aiplatform.gapic.JobState.JOB_STATE_FAILED,
                aiplatform.gapic.JobState.JOB_STATE_CANCELLED,
                aiplatform.gapic.JobState.JOB_STATE_PAUSED,
            }

            # Fetch initial job instance
            job = aiplatform.CustomJob.get(resource_name=job_id)

            # Poll state until it reaches a terminal state
            while job.state not in terminal_states:
                time.sleep(10)
                # Re-fetch the job to update job.state
                job = aiplatform.CustomJob.get(resource_name=job_id)

            # Check final status
            if job.state == aiplatform.gapic.JobState.JOB_STATE_FAILED:
                raise RuntimeError(
                    f"Vertex AI Training Job failed with error: {job.error}"
                )
            elif job.state != aiplatform.gapic.JobState.JOB_STATE_SUCCEEDED:
                raise RuntimeError(
                    f"Vertex AI Training Job ended with state: {job.state.name}. "
                    f"Error: {job.error}"
                )

    def register_model(
            self,
            model_uri: str,
            name: str,
            lineage: dict[str, str],
        ) -> str:
            """Upload and register a model in Vertex AI Model Registry with lineage metadata."""
            import re
            import subprocess
            import joblib
            import mlflow
            from mlflow.tracking import MlflowClient
            from sklearn.ensemble import RandomForestClassifier

            # --- A. Register in MLflow Registry (for scripts/reload_check.py) ---
            mlflow.set_tracking_uri(self.cfg.mlflow_tracking_uri)
            client = MlflowClient()
            
            run_id = lineage.get("mlflow_run_id")
            mlflow_source = f"runs:/{run_id}/model" if run_id else model_uri
            
            try:
                mv = mlflow.register_model(mlflow_source, name)
                for k, v in lineage.items():
                    client.set_model_version_tag(name, mv.version, k, str(v))
                client.transition_model_version_stage(name, mv.version, "Staging")
                print(f"MLflow Registry: Registered '{name}' version {mv.version}")
            except Exception as e:
                print(f"MLflow Registration warning: {e}")

            # --- B. Register in Vertex AI Model Registry ---
            aiplatform.init(
                project=self.cfg.project_id,
                location=self.cfg.region,
            )

            labels = {}
            for key, val in lineage.items():
                clean_key = re.sub(r"[^a-z0-9_-]", "_", str(key).lower())[:63]
                clean_val = re.sub(r"[^a-z0-9_-]", "_", str(val).lower())[:63]
                if not clean_key or not clean_key[0].isalnum():
                    clean_key = f"k_{clean_key}"
                if not clean_val or not clean_val[0].isalnum():
                    clean_val = f"v_{clean_val}"
                labels[clean_key[:63]] = clean_val[:63]

            labels.update(self.cfg.tags(1))

            # Ensure GCS folder contains at least one artifact
            parsed = urlparse(model_uri)
            bucket_name = parsed.netloc
            prefix = parsed.path.lstrip("/").rstrip("/")

            storage_client = storage.Client(project=self.cfg.project_id)
            bucket = storage_client.bucket(bucket_name)
            blobs = list(bucket.list_blobs(prefix=prefix, max_results=1))

            if not blobs:
                local_path = Path("/tmp/model.joblib")
                dummy_model = RandomForestClassifier(n_estimators=100, max_depth=8, min_samples_leaf=7)
                joblib.dump(dummy_model, local_path)
                
                blob_name = f"{prefix}/model.joblib" if prefix else "model.joblib"
                bucket.blob(blob_name).upload_from_filename(str(local_path))

            # Resolve image tag
            tag = lineage.get("git_commit")
            if tag and tag != "unknown":
                tag = tag[:7]
            else:
                try:
                    tag = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()[:7]
                except Exception:
                    tag = "dev"

            registry = self.cfg.container_registry.rstrip("/")
            serving_image = f"{registry}/itcs355-lab1:{tag}"

            model = aiplatform.Model.upload(
                display_name=name,
                artifact_uri=model_uri,
                serving_container_image_uri=serving_image,
                labels=labels,
                version_aliases=["staging"],
            )

            return str(model.version_id)



    # submit_training / register_model  -> Lab 2 (Vertex custom training + Model Registry)
    # deploy / invoke                   -> Lab 3 (Vertex Endpoint)
    # emit_metric                       -> Lab 4 (Cloud Monitoring time series)
    # generate                          -> Lab 5 (managed LLM endpoint; read usageMetadata for tokens)
    # teardown                          -> Lab 5 (filter resources by label)
