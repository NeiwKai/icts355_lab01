TASK 4
## Model Governance & Stage Promotion

### Authorized Roles
In a production deployment environment, **individual Data Scientists and ML Engineers are strictly prohibited from directly promoting models to Production**. 

Model promotions must be executed via automated gatekeeping or dedicated governance roles:
* **Staging Promotion:** Triggered automatically by the **CI/CD Pipeline Service Principal** upon successful completion of unit tests, lineage tagging checks, and model registration.
* **Production Promotion:** Requires explicit sign-off from an **MLOps Lead / Technical Product Owner** or a **Compliance / Risk Lead** via an approved Pull Request / Change Advisory Board (CAB) review.

---

### Required Evidence for Promotion Approval
Before any model version is granted promotion from `Staging` to `Production`, the following four mandatory artifacts must be presented:

1. **Complete Lineage Audit:** Verification that all 8 governance tags (`git_commit`, `data_version`, `mlflow_run_id`, `training_job_id`, `image_digest`, `seed`, `metric_val`, `metric_test`) exist and are non-empty.
2. **Performance Baseline & Regression Report:** Automated proof that `metric_val` and `metric_test` meet or exceed target threshold requirements without degrading relative to the active production model.
3. **Reproducibility Verification:** Passing execution log verifying that rebuilding from the specified `git_commit`, `data_version`, and `image_digest` reproduces identical evaluation metrics.
4. **Security & Data Compliance Checks:** Zero high/critical vulnerability findings on the container (`image_digest`) via container scanning (e.g., Trivy/GCP Artifact Analysis) and verified compliance with data privacy/fairness standards.
