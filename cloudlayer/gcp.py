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

from google.cloud import storage

from cloudlayer.base import CloudAdapter


class GcpAdapter(CloudAdapter):
    def upload(self, local_path: str, key: str) -> str:
        """Upload a file under BLOB_URI.

        Returns:
            gs://bucket/prefix/key
        """
        parsed = urlparse(self.cfg.blob_uri)

        if parsed.scheme != "gs":
            raise ValueError(
                f"BLOB_URI must use gs://, got {self.cfg.blob_uri!r}"
            )

        bucket_name = parsed.netloc
        prefix = parsed.path.lstrip("/").rstrip("/")

        blob_name = f"{prefix}/{key}" if prefix else key

        bucket = self.client.bucket(bucket_name)
        blob = bucket.blob(blob_name)

        blob.upload_from_filename(local_path)

        return f"gs://{bucket_name}/{blob_name}"
        #raise NotImplementedError("TODO Lab 1: blob.upload_from_filename, return the gs:// URI")

    def download(self, uri: str, local_path: str) -> None:
        """Download a GCS object to a local path."""
        parsed = urlparse(uri)

        if parsed.scheme != "gs":
            raise ValueError(
                f"URI must use gs://, got {uri!r}"
            )

        bucket_name = parsed.netloc
        blob_name = parsed.path.lstrip("/")

        if not bucket_name or not blob_name:
            raise ValueError(f"Invalid GCS URI: {uri!r}")

        Path(local_path).parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        bucket = self.client.bucket(bucket_name)
        blob = bucket.blob(blob_name)

        blob.download_to_filename(local_path)
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

    # submit_training / register_model  -> Lab 2 (Vertex custom training + Model Registry)
    # deploy / invoke                   -> Lab 3 (Vertex Endpoint)
    # emit_metric                       -> Lab 4 (Cloud Monitoring time series)
    # generate                          -> Lab 5 (managed LLM endpoint; read usageMetadata for tokens)
    # teardown                          -> Lab 5 (filter resources by label)
