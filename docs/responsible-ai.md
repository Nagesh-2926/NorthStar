# Responsible use and safeguards

This ML layer is an early-support decision aid. Its output is a score and a review band, not a statement that a student will fail, withdraw, or is a dropout. Do not make an adverse decision, restrict opportunity, or contact a student solely from a model output. A coordinator reviews observed records, circumstances, and student preferences before offering support.

## Interpreting outputs

- The binary label combines historical Fail and Withdrawn outcomes; the score is not a calibrated probability until separately calibrated and validated.
- A false negative can miss a chance to offer support; a false positive can create needless contact, stigma, or staff burden. Current thresholds favor recall and produce thousands of false positives in the held-out presentation. Thresholds need an explicit capacity and harm review.
- VLE clicks measure recorded interactions. They do not establish attendance, attention, effort, understanding, or intent.
- Tree feature importance is a cohort-level model association. It does not explain an individual's outcome or establish causation.
- Clusters are cohort-relative, arbitrary IDs. They must not be converted into deficit labels or student-facing categories.

## Controls required before deployment

Use purpose limitation, data minimization, access controls, encryption, retention limits, audit logs, and secure handling of pseudonymous student IDs. Keep raw and derived historical OULAD files and model artifacts access-restricted; do not import historical source learners into live student accounts. The FastAPI backend enforces JWT authentication, student ownership, and coordinator/student roles; frontend route hiding remains a usability measure. Do not expose model files, database credentials, or LLM provider keys to React.

Before any live pilot, validate calibration and errors on the intended institution and recent cohorts, inspect results by relevant groups under governance, review feedback/appeals, monitor data and performance drift, and provide a human override and documented intervention rationale. Do not automate outreach or adverse actions from scores. Current study-plan generation is user-requested, advisory, privacy-minimized, and falls back to local supportive content when a provider fails or returns unsafe output. The LLM receives a coarse review band and limited academic/engagement context, not names, account identifiers, demographics, or raw notes; its content is not a deterministic statement of model output.
