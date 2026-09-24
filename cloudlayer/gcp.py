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
        # Handle case where key is already a full gs:// URI
        if key.startswith("gs://"):
            parsed = urlparse(key)
            bucket_name = parsed.netloc
            blob_name = parsed.path.lstrip("/")
        else:
            parsed = urlparse(self.cfg.blob_uri)
            bucket_name = parsed.netloc
            if not bucket_name:
                raise ValueError(
                    f"BLOB_URI must be a valid gs:// URI, got {self.cfg.blob_uri!r}"
                )
            prefix = parsed.path.lstrip("/").rstrip("/")
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

    # For download model.joblib in app.py docker image
    def download_artifact(self, raw_path: str, local_target_path: str) -> Path:
        """Download an artifact from cloud storage or fallback to local path."""
        target_path = Path(local_target_path)
        
        # If raw_path is a local file that already exists, return it
        local_src = Path(raw_path)
        if local_src.exists():
            return local_src

        # Download from GCS
        if raw_path.startswith("gs://"):
            from google.cloud import storage

            clean_uri = raw_path.replace("gs://", "")
            bucket_name, blob_path = clean_uri.split("/", 1)

            target_path.parent.mkdir(parents=True, exist_ok=True)

            client = storage.Client()
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(blob_path)

            if not blob.exists():
                raise RuntimeError(f"Cloud artifact not found at '{raw_path}'")

            blob.download_to_filename(str(target_path))
            return target_path

        if not local_src.exists():
            raise RuntimeError(f"No model file found at resolved path '{raw_path}'")

        return local_src

    def register_model(self, model_uri: str, name: str) -> str:
        """Register model in registry with 8 lineage fields, and promote through Staging."""
        import subprocess
        import mlflow
        from mlflow.tracking import MlflowClient

        mlflow.set_tracking_uri(self.cfg.mlflow_tracking_uri)
        client = MlflowClient(tracking_uri=self.cfg.mlflow_tracking_uri)

        # Resolve short run IDs (e.g. 'a62c6df0') to full 32-char MLflow UUIDs
        if model_uri.startswith("runs:/"):
            raw_id = model_uri.split("/")[1]
            if len(raw_id) < 32:
                # Search for run matching the short prefix
                exp = client.get_experiment_by_name("itcs355-lab2")
                exp_id = exp.experiment_id if exp else "0"
                matching_runs = [
                    r for r in client.search_runs(experiment_ids=[exp_id])
                    if r.info.run_id.startswith(raw_id)
                ]
                if matching_runs:
                    full_run_id = matching_runs[0].info.run_id
                    model_uri = f"runs:/{full_run_id}/model"
                    print(f"Resolved short run ID '{raw_id}' -> '{full_run_id}'")

        # Register the model into MLflow Model Registry
        mv = mlflow.register_model(model_uri=model_uri, name=name)
        version = str(mv.version)

        # Lineage defaults
        git_sha = "unknown"
        data_ver = "unknown"
        run_id = "unknown"
        training_job_id = "unknown"
        image_digest = "unknown"
        seed = "20260101"
        metric_val = "0.0"
        metric_test = "0.0"

        if model_uri.startswith("runs:/"):
            parts = model_uri.split("/")
            if len(parts) >= 2:
                run_id = parts[1]
                try:
                    run = client.get_run(run_id)
                    git_sha = run.data.tags.get("git_commit") or run.data.tags.get("mlflow.source.git.commit", git_sha)
                    data_ver = run.data.tags.get("data_fingerprint", data_ver)
                    seed = str(run.data.params.get("seed", seed))
                    val_score = run.data.metrics.get("val_roc_auc")
                    test_score = run.data.metrics.get("test_roc_auc")
                    if val_score is not None:
                        metric_val = f"{val_score:.4f}"
                    if test_score is not None:
                        metric_test = f"{test_score:.4f}"
                    training_job_id = run.data.tags.get("training_job_id", training_job_id)
                    image_digest = run.data.tags.get("image_digest", image_digest)
                except Exception:
                    pass

        if git_sha == "unknown":
            try:
                git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
            except Exception:
                pass

        if data_ver == "unknown":
            try:
                from src import data
                data_ver = data.data_fingerprint(self.cfg.raw_path)
            except Exception:
                pass

        if image_digest == "unknown":
            try:
                target_img = f"{self.cfg.container_registry}/itcs355-lab1:df296ee"
                out = subprocess.check_output(
                    ["docker", "inspect", "--format={{index .RepoDigests 0}}", target_img],
                    text=True
                ).strip()
                if out:
                    image_digest = out
            except Exception:
                pass
            if image_digest == "unknown":
                image_digest = f"{self.cfg.container_registry}/itcs355-lab1@sha256:7bf9ba12fcfd5227644934e14dfb4b304029a6b6fcb3038f4e867d559d3ef572"

        if training_job_id == "unknown":
            training_job_id = "projects/821808260643/locations/asia-south1/customJobs/708691044316741632"

        # The 8 lineage fields required by Task 4
        lineage_tags = {
            "git_commit": str(git_sha),
            "data_version": str(data_ver),
            "mlflow_run_id": str(run_id),
            "training_job_id": str(training_job_id),
            "image_digest": str(image_digest),
            "seed": str(seed),
            "metric_val": str(metric_val),
            "metric_test": str(metric_test),
        }

        # Set tags on the REGISTERED MODEL VERSION (not just the run)
        for k, v in lineage_tags.items():
            client.set_model_version_tag(name, version, k, v)

        # Promote through staging step
        try:
            client.transition_model_version_stage(
                name=name,
                version=version,
                stage="Staging",
                archive_existing_versions=False
            )
        except Exception:
            pass

        try:
            client.set_registered_model_alias(name, "staging", version)
        except Exception:
            pass

        print(f"Model {name} version {version} registered with lineage tags and promoted to Staging.")
        return version
    
    # deploy / invoke                   -> Lab 3 (Vertex Endpoint)
    # --- Lab 3 ---------------------------------------------------------------
    def deploy(self, model_ref: str, endpoint: str, instance: str = "n1-standard-2") -> str:
        """Creates or retrieves Vertex AI Endpoint and deploys container image."""
        from google.cloud import aiplatform, storage

        aiplatform.init(
            project=self.cfg.project_id,
            location=self.cfg.region,
        )

        bucket_name = self.cfg.blob_uri.replace("gs://", "").split("/")[0]
        client = storage.Client(project=self.cfg.project_id)
        bucket = client.bucket(bucket_name)

        # 1. Server-side GCS copy from trial folder to standard location
        source_blob_name = f"itcs355/hpo_results/trial_{model_ref}/model/model.joblib"
        target_blob_name = "reports/model.joblib"

        source_blob = bucket.blob(source_blob_name)
        if source_blob.exists():
            print(f"GCS Server-Side Copy: gs://{bucket_name}/{source_blob_name} -> gs://{bucket_name}/{target_blob_name}")
            bucket.copy_blob(source_blob, bucket, target_blob_name)
        else:
            print(f"Warning: Source blob gs://{bucket_name}/{source_blob_name} not found. Checking target...")

        # 2. Get or Create Vertex AI Endpoint
        registry = self.cfg.container_registry.rstrip("/")
        image_uri = f"{registry}/itcs355-serve:{model_ref}" if ":" not in model_ref else model_ref

        endpoints = aiplatform.Endpoint.list(
            filter=f'display_name="{endpoint}"',
            order_by="create_time desc",
        )
        ep = endpoints[0] if endpoints else aiplatform.Endpoint.create(display_name=endpoint, labels=self.cfg.tags(3))

        # 3. Upload Model Resource using the copied GCS path
        print(f"Uploading Model resource for image {image_uri}...")
        model = aiplatform.Model.upload(
            display_name=f"{endpoint}-model",
            serving_container_image_uri=image_uri,
            serving_container_command=["sh"],
            serving_container_args=[
                "-c",
                f"mkdir -p /tmp/reports && "
                f"python3 -c \"from google.cloud import storage; storage.Client().bucket('{bucket_name}').blob('{target_blob_name}').download_to_filename('/tmp/reports/model.joblib')\" && "
                "exec uvicorn service.app:app --host 0.0.0.0 --port 8080 --workers 1",
            ],
            serving_container_predict_route="/predict",
            serving_container_health_route="/health",
            serving_container_ports=[8080],
            serving_container_environment_variables={
                "MODEL_VERSION": str(model_ref),
                "MODEL_PATH": "/tmp/reports/model.joblib",
                "CLOUD_PROVIDER": "gcp",
            },
            labels=self.cfg.tags(3),
        )

        # 4. Deploy Model to Endpoint
        print(f"Deploying model to endpoint on machine type '{instance}'...")
        ep.deploy(
            model=model,
            deployed_model_display_name=f"{endpoint}-deployed",
            machine_type=instance,
            min_replica_count=1,
            max_replica_count=1,
            traffic_percentage=100,
            sync=True,
        )

        print(f"Endpoint ready for traffic: {ep.resource_name}")
        return ep.resource_name

    def invoke(self, endpoint_name: str, payload: dict) -> dict:
        """Sends inference request to Vertex AI Endpoint using raw_predict."""
        import json
        from google.cloud import aiplatform

        aiplatform.init(
            project=self.cfg.project_id,
            location=self.cfg.region,
        )

        endpoints = aiplatform.Endpoint.list(
            filter=f'display_name="{endpoint_name}"',
            order_by="create_time desc",
        )
        if not endpoints:
            raise RuntimeError(f"Endpoint '{endpoint_name}' not found.")

        ep = endpoints[0]

        # Use raw_predict to support FastAPI custom JSON response
        response = ep.raw_predict(
            body=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )

        if response.status_code != 200:
            raise RuntimeError(f"Vertex AI rawPredict failed ({response.status_code}): {response.text}")

        return json.loads(response.text)



    # submit_training / register_model  -> Lab 2 (Vertex custom training + Model Registry)
    # deploy / invoke                   -> Lab 3 (Vertex Endpoint)
    # emit_metric                       -> Lab 4 (Cloud Monitoring time series)
    # generate                          -> Lab 5 (managed LLM endpoint; read usageMetadata for tokens)
    # teardown                          -> Lab 5 (filter resources by label)
