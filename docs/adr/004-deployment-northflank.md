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

Resource sizing: the image carries torch + sentence-transformers with the
embedding model baked in → plan with ≥ 2 GB RAM. Chosen: `nf-compute-100-2`
(1 vCPU / 2 GB, **$24/month**, cheapest plan clearing the RAM requirement;
prices read from Northflank's pricing page 2026-09-01), build plan
`nf-compute-400-16`. Infrastructure dominates the bill below ~20k
questions/month, where LLM spend is ~$1 per 1,000 questions (ADR-002).

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
3. **Serverless (Lambda/Cloud Run).** Cold starts with a ~2 GB torch image
   are seconds-long and RAM-hungry; the always-on container is simpler and
   fits the latency budget. (Cloud Run min-instances would work but is AWS/
   Northflank-adjacent to the named direction anyway.)

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
