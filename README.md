# ITCS355 Lab 1 — Reproducible Training

> **Course materials live in [`course/`](course/README.md)** — syllabus, slides, the faculty
> specification, all five lab handouts, and the project brief. Every document is Markdown and
> renders on GitHub, diagrams included. New to the repo? Start with the
> [portability reference](course/reference/cloud-portability-reference.md).
> Keep this block when you edit the rest of this file; it is not part of the Lab 1 deliverable.

Predicting machine failure within 7 days from sensor readings. The model is not the point;
whether a stranger can reproduce it is.

> **This README is graded.** A grader with Docker and nothing else from your setup runs one
> command and compares the result against the claim below. Edit every `<...>` and delete the
> instruction blocks marked **REPLACE** before submitting.

---

## Reproduce

```bash
time(mkdir -p reports && chmod 777 reports && make setup && make reproduce && make verify)
```

expected test_roc_auc: 0.8482 ± 0.010; make verify 

Runtime: about 40 seconds on 4 cores. No cloud account or credentials needed for this command —
that is deliberate, and it is why a grader can run it.


---

## The problem

240 machines, 25 readings each, 6 sensor features, binary target `failed_within_7d` with a
positive rate near 12%.

Machines have persistent characteristics — a hot-running machine reads hot in every row. So the
train/validation/test split is **grouped by `machine_id`**: every reading from one machine lands
in exactly one partition. Splitting row-wise instead lets the model memorise the machine and
reports a validation score that will never survive production. `tests/test_data.py` asserts this
property holds, and Lab 4 turns it into a CI gate.

Bringing your own dataset is allowed. Replace `scripts/make_dataset.py`, update the schema in
`src/data.py`, and keep every test passing.

---

## Layout

```
src/          Layer 1 — provider-neutral. No SDKs, no bucket names, no absolute paths.
cloudlayer/   Layer 3 — the only place a provider SDK may be imported.
scripts/      Dataset generation, cloud check, portability audit, metric verification.
tests/        Data contract tests and split property tests.
```

`src/config.py` is the single point of environment knowledge. Everything else reads from it.
`make portability-audit` enforces the rule; it fails the build if a provider string appears in
`src/` or `tests/`.

---

## Setup

```bash
cp cloud.env.example cloud.env      # fill in, never commit
make setup
make cloud-check                    # eight slots, all PASS
make data                           # generate the dataset
make test                           # 10 tests, all passing
```

Post your `make cloud-check` output in the course channel before Session 1.

---

## What you must finish

Four `TODO` markers are left in the repo deliberately. Each is a graded decision, not busywork.

| Where | What |
|---|---|
| `requirements.txt` | Regenerate with `pip-compile --generate-hashes` |
| `Dockerfile` | Pin the base image by digest; add `--require-hashes` |
| `cloudlayer/<your provider>.py` | Implement `upload`, `download`, `push_image` |
| This README | The reproducibility trade-off question below |

Then:

```bash
make image-push        # image reaches your registry, digest-pinned
dvc init && dvc remote add -d storage ${BLOB_URI}/dvc
dvc add data/raw && dvc push
```

Run five or more tracked runs varying something meaningful — not five identical runs with
different seeds.

---

## Reproducibility trade-off

I would drop the digest-pinned base image because if removing the base-image digest and use
python:3.11-slim instead, the experiment will probably still run, but the Docker build is no
longer fully reproducible. The tag can point to a different base image later, potentially 
changing the OS, system libraries, or Python environment.

Three things pin your build: hashed dependencies, a digest-pinned base image, and controlled
seeds. Under real time pressure you would keep some and drop others.

Which would you drop first, and what specifically breaks when you do? There is a defensible
answer, and we compare answers in Session 2. An answer that refuses to choose scores zero.

---

## Notes for the grader

There was a problem with Makefile on `make reproduce`. It is impossible to get the operation done
because it will run `python` first.
```bash
╰─± make -n reproduce
python scripts/make_dataset.py --seed 20260101
docker buildx build --platform linux/amd64 -t itcs355-lab1:0e83005 --load .
docker run --rm \
	  -v "$PWD/data:/app/data:ro" \
	  -v "$PWD/reports:/app/reports" \
	  -e MLFLOW_TRACKING_URI=sqlite:////app/reports/mlflow.db \
	  itcs355-lab1:0e83005 --seed 20260101 --metrics-out /app/reports/metrics.json
```
Which the python script require additional library to be installed first such as `numpy`.
It is impossible to not run `make setup` first to install additional required packages.

There was also a permission issue that on MacOS haven't stump on this, but on another machine
Gentoo Linux, there was a permission with `reports` that require write access for docker.
So the `mkdir -p reports && chmod 777 reports` is required.

Task5 outputs are in `reports/task5_runs.txt`. The script use to test is in `scripts/lab1_task5.sh`.

---

## Checklist before you submit

- [x] `make reproduce` works from a fresh clone, on a machine that is not yours
- [x] `make verify` passes against your claim line
- [x] `make test` — all tests pass
- [x] `make portability-audit` — clean
- [x] Image builds for `linux/amd64` and is pushed, digest-pinned
- [x] `dvc push` completed; a grader can `dvc pull`
- [x] Five or more tracked runs with params, metrics, data fingerprint, and commit SHA
- [x] Every **REPLACE** block above is gone (the course-materials block at the top stays)
- [x] `git log -p | grep -i -E "secret|password|AKIA|BEGIN PRIVATE"` returns nothing

That last check is not optional. A credential in Git history is an automatic deduction in this
course, and rotating it is your responsibility, not the grader's.
