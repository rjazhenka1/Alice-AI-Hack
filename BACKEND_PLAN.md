# EventOps AI Backend Agent Plan

## Scope and constraints

- Target files for implementation:
  - `eventops/backend/app/agent/alice.py`
  - `eventops/backend/app/agent/tools.py`
  - `eventops/backend/app/agent/router.py`
  - `eventops/backend/app/api/agent.py`
- Integration boundary with notifier:
  - `eventops/backend/app/notifier.py` is treated as an external module owned by another backend developer.
  - Agent side only uses notifier queue contract.
- Contracts to preserve:
  - `AGENTS.md`
  - `openapi.yaml`
  - `eventops/backend/app/schemas.py`

---

## Baseline architecture decision

Use **two-layer orchestration** as default behavior:

1. LLM tool-calling layer (intent + tool invocation chain).
2. Router normalization layer that produces strict API output contract.

This aligns with `AgentCommandResponse` and reduces parse fragility compared to JSON-only generation.

---

## Prompt subsystem requirements

`eventops/backend/app/agent/prompts.py` must define policies and templates that force these outcomes:

1. **Unambiguous operational request** → tool call chain + user-readable confirmation.
2. **Need clarification** → no guessing, ask follow-up question and wait for next user turn.
3. **Unclear/insufficient request** → no tool side effects, safe helpful response.

Mandatory prompt blocks:

- Role routing hints from `role.ai_prompt`.
- Event context summary (event, zones, roles, free staff count).
- Visibility and disclosure policy for final user output.
- Confidence policy:
  - low confidence => ask clarification.
- Tool usage policy:
  - do not create tickets when intent is unclear.

Guardrails dependency notes:

- Guardrails in AI Studio are preview and optional policy layer.
- One moderation rule per model instance.
- Guardrail-triggered `content_filter` or `incomplete` must be handled by router as safe response, no API crash.

Verifier dependency notes:

- Optional second LLM pass may rewrite unsafe draft outputs.
- Verifier does not replace backend authorization and visibility checks.

---

## Variant A — text-first only

### A1. `eventops/backend/app/api/agent.py`

Implementation steps:

1. Validate incoming payload for text-first release:
   - require non-empty `text`.
   - reject empty payload with meaningful HTTP error.
2. Resolve current authenticated staff and event scope.
3. Call router service entrypoint with normalized text.
4. Return strict `AgentCommandResponse` schema-compatible payload.

Testing points:

- accepts valid text request.
- rejects empty text.
- preserves auth and event scoping.

Readiness criteria:

- responses always match `AgentCommandResponse`.
- no direct tool execution in API layer.

Prompt dependencies:

- API layer passes clean user text exactly once per turn.

### A2. `eventops/backend/app/agent/router.py`

Implementation steps:

1. Load/create `AgentSession` by `(event_id, staff_id)`.
2. Maintain rolling context with max 20 messages.
3. Build prompt context:
   - event summary.
   - role prompt snippets.
   - visibility-safe ticket context for current user-facing branch.
4. Execute two-layer run:
   - call LLM with tools.
   - execute tool handlers when requested.
   - re-query for final assistant response if needed.
   - normalize to one of actions: `ticket_created`, `question_asked`, `task_assigned`, `answered`.
5. Persist updated session context.
6. Handle guardrail outcomes:
   - map `content_filter` or incomplete status to safe assistant response.

Testing points:

- action mapping stability.
- session trim to 20 messages.
- no side effects on unclear intent branch.
- safe fallback on model moderation block.

Readiness criteria:

- all 3 canonical scenarios reproducible.
- no contract drift in action/message fields.

Prompt dependencies:

- router depends on deterministic policy sections in prompts.

### A3. `eventops/backend/app/agent/tools.py`

Implementation steps:

1. Define tool registry and schemas for:
   - `get_free_staff`
   - `create_ticket`
   - `assign_staff`
   - `get_ticket_list`
   - `send_notification`
   - `ask_clarification`
2. Add argument validation and event ownership checks.
3. Add idempotency protections for repeated model retries.
4. Enforce business safeguards:
   - no assignment on unclear intent path.
   - explicit confirmation boundary for side effects where required.
5. Integrate notifier handoff only via queue contract.

Testing points:

- each tool happy path.
- each tool invalid-args path.
- idempotent behavior under retry.

Readiness criteria:

- tool outputs are serializable and safe for LLM context.
- side effects only happen in allowed branches.

Prompt dependencies:

- prompt tool descriptions must match actual handler semantics.

### A4. `eventops/backend/app/agent/alice.py`

Implementation steps:

1. Build async AI client wrapper.
2. Configure timeout to 15 seconds.
3. Add structured logging:
   - latency.
   - model status.
   - tool-calling metadata.
4. Add robust error handling and safe fallback messages.
5. Support tool-call roundtrip data structures used by router.

Testing points:

- timeout behavior.
- network error fallback.
- tool call payload roundtrip integrity.

Readiness criteria:

- no uncaught upstream exceptions leak to API.
- logs are enough for incident triage.

Prompt dependencies:

- client must preserve system and user roles unchanged.

### A5. Notifier integration boundary

Implementation steps:

1. Use notifier queue payload contract only.
2. Trigger queueing from confirm/assignment-safe branch.
3. Do not modify notifier worker implementation.

Testing points:

- notification job enqueued with correct `telegram_id` and message text.

Readiness criteria:

- agent integration does not break notifier ownership boundary.

---

## Variant B — full text plus audio_base64 via SpeechKit

### B1. API expansion in `eventops/backend/app/api/agent.py`

Implementation steps:

1. Accept dual input:
   - `text`
   - `audio_base64`
2. Validate exactly one effective command source.
3. Route audio to STT adapter and obtain normalized text.
4. Reuse same router flow as Variant A.

Testing points:

- text path unchanged.
- audio path produces normalized text.
- invalid dual-empty or dual-conflict payload handled.

Readiness criteria:

- contract compatibility preserved.

Prompt dependencies:

- prompts receive normalized text only.

### B2. STT adapter in `eventops/backend/app/agent/alice.py`

Implementation steps:

1. Add SpeechKit transcription adapter.
2. Decode base64 audio safely.
3. Apply transcription options suitable for short command utterances.
4. Return normalized text and metadata to router.

Testing points:

- valid wav/ogg decode.
- bad base64 handling.
- empty transcription fallback.

Readiness criteria:

- stable transcription for short operational commands.

Prompt dependencies:

- pre-normalization step to reduce STT noise before intent routing.

### B3. Router adjustments in `eventops/backend/app/agent/router.py`

Implementation steps:

1. Save transcript text in session context as user message.
2. Tag message metadata source as text or audio.
3. Reuse same two-layer orchestration and action mapping.

Testing points:

- continuity of multi-turn context after audio command.

Readiness criteria:

- no branching logic divergence from text-first behaviors.

---

## Risk register

1. Duplicate side effects from retries.
   - Mitigation: idempotency keys or duplicate-check rules in tool handlers.
2. Unauthorized confidential disclosure in final user output.
   - Mitigation: output-stage visibility filtering in router and API-level auth checks.
3. Guardrail moderation false positives.
   - Mitigation: safe fallback text and explicit handling of incomplete content_filter responses.
4. Variant B latency increase and STT noise.
   - Mitigation: normalize transcript and keep clarification-first behavior on ambiguity.

---

## Test strategy

### Unit tests

- prompt builder blocks composition.
- router action normalization.
- session trim logic.
- tool argument validation and idempotency checks.

### Integration tests

- POST agent command text path.
- POST agent confirm path and assignment side effects.
- notifier queue enqueue from allowed branch.

### Contract tests

- all responses validate against `AgentCommandResponse`.
- command request validation for text-first and dual-input modes.

### Prompt regression tests

Golden scenarios:

1. clear operational request -> create/assign flow.
2. clarification-needed request -> question_asked.
3. unclear request -> answered without side effects.

---

## Definition of Done

1. All canonical scenarios from AGENTS are stable and repeatable.
2. No unauthorized confidential data shown to users without access.
3. API outputs remain OpenAPI/schema compatible.
4. Timeout, guardrail, and upstream error branches return safe user responses.
5. Logs include latency and orchestration trace sufficient for debugging.

---

## Suggested dependency pins

- `yandex-ai-studio-sdk>=0.20.0,<0.21.0`

Notes:

- Version band is aligned with current docs and release line.
- Keep pin narrow for hackathon stability and reproducibility.
