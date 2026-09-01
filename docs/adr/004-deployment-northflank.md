# ADR-004: Deployment on Northflank with git-driven IaC

- **Status:** Accepted
- **Date:** 2026-09-01

## Context

Deployment is mandatory: public URL for UI + API, container-level visibility
for reviewers, IaC ("a new deployment from the repository must be possible
without manual steps"), secrets in environment, reproducible builds,
idempotent deploys. The recruiter explicitly named the direction: "Amazon or
Northflank". Time budget for the whole assignment is 6–8 hours.

## Decision

Deploy to **Northflank**: one service built from the repo's Dockerfile
(multi-stage: frontend build → Python runtime), deployment defined as a
committed Northflank template file, CI (GitHub Actions) running
tests → lint → build → deploy → smoke check on `/health` → eval run against
prod. Reviewers get container-level access via an invitation to the
Northflank project (roles supported) — recorded in README.

Resource sizing — **revised once, after measurement** (see below). Deployed
plan: `nf-compute-20` (0.2 vCPU / 512 MB, **$5.41/month**), build plan
`nf-compute-800-8`, both as committed in `northflank-template.json`. Prices
read from Northflank's pricing page 2026-09-01. Infrastructure dominates the
bill below ~5,300 questions/month, where LLM spend is ~$1 per 1,000
questions (ADR-002).

### Revision: 2 GB → 512 MB

This ADR originally specified `nf-compute-100-2` (1 vCPU / 2 GB, $24/month)
on the assumption that the image needed ≥ 2 GB of RAM. That assumption was
wrong in an instructive way, and the deploy is what proved it.

The first deployment on 512 MB was OOM-killed at startup (exit 137) — but the
cause was not the model's size. Two things were making memory usage far
larger than the work required: embedding the whole corpus in a single batch
peaked at 1381 MB, and ONNX Runtime sized its thread pool from the *host's*
core count rather than the container's CPU limit, with a separate allocation
arena per thread. Bounding the batch to 4 and pinning `EMBEDDING_THREADS=1`
brought the peak to 345 MB, verified under a hard 512 MB limit with the full
golden set passing.

The rule this follows: fix the cause, then size the plan to the measurement.
Buying a $24 plan would have hidden a real bug — and the bug would have
resurfaced on any host with more cores.

Build plans deserve a separate note: Northflank's smallest *build* plan is
8 vCPU, and every build plan exceeds the free Developer Sandbox allowance.
The free tier therefore cannot host this service at all — not because of the
application, but because it cannot build it.

## Alternatives considered

1. **AWS (ECS/Fargate + Terraform).** Maximum control and the most
   "industrial" answer; rejected for this budget: ECS + IAM + ECR + ALB
   plumbing realistically costs 2–3 hours of the 6–8 available and none of
   it is graded higher than a working, reproducible deploy elsewhere.
   The assignment explicitly examines practices, not infrastructure spend.
2. **Fly.io / Render / Railway.** Comparable developer experience; not among
   the directions named by the recruiter, and Northflank's project-level
   dashboard access maps directly onto the "container-level visibility"
   requirement.
3. **Serverless (Lambda/Cloud Run).** Cold starts have to load the embedding
   model before the first answer; the always-on container avoids paying that
   per scale-from-zero, and the assignment's latency budget is already spent
   on the LLM call. Worth revisiting now that the image is 1.05 GB rather
   than multi-GB — the original objection was mostly about image weight.

## Consequences

- Statelessness (ADR-002) makes repeat deploys of the same revision a no-op
  by construction; verified and stated in README.
- If the torch image is too heavy for the platform in practice, the recorded
  fallback is switching embeddings to an API provider via env (ADR-002 alt 5)
  — slim image, no code change.
- Secrets: Northflank secret groups + GitHub Actions secrets; repo carries
  `.env.example` only. `LLM_API_KEY` enters as a template *argument* at run
  time, so the committed template holds a placeholder, not a key.
- Template format verified against the current Northflank API (`apiVersion`
  v1.2), created and accepted by `POST /v1/templates`; two schema constraints
  the docs do not spell out were found by the API rejecting the payload:
  `description` is capped at 200 characters and restricted to a character set
  that excludes `=`.
- **Known blocker at time of writing:** the template run fails at resource
  creation with "Please complete your account by adding a default payment
  method" — Northflank requires a card on file even for free-tier projects.
  Every step before that (GitHub app installation scoped to this single
  repository, template creation, run submission) succeeds. This is an account
  action, not a code or configuration change.

## Revisit when

- Requirements arrive for VPC/private networking, managed queues/DBs, or
  org-standard AWS infrastructure → Terraform on AWS becomes the right cost.
- Image size or RAM pushes past the platform plan limits → embeddings via
  API (documented fallback) or a heavier plan.
