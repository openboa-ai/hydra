# Open Questions and Review Decisions

These questions remain intentionally unresolved. They are the handoff from research to human review.

## Evidence gaps

1. **Cognition/Devin:** no sufficiently detailed public engineering source was found in the first pass. Do not use its product claims as a normative input.
2. **Independent evidence:** the corpus is vendor-heavy. Add independent evaluations, incident reports, and open-source implementations before a major policy claim.
3. **Enterprise adoption:** internal engineering case studies with measurement methodology are still underrepresented.
4. **Runtime portability:** the corpus agrees on semantics but not on a common implementation API.
5. **Observation quality:** preview and telemetry are common in vendor systems, but a minimum OpenBoa observation record is not yet validated on a deployed product.

## Human decisions

1. Accept or reject the working definition of AI-Native SDLC.
2. Keep two current risk lanes or adopt the proposed routine/elevated/human-gate/break-glass taxonomy as a research-derived refinement.
3. Decide whether the public identity migration is exactly openboa-ai-native-sdlc and whether the old name receives an alias, redirect, or only a migration note.
4. Decide whether the Codex GitHub connector policy belongs in the AI-Native SDLC core or in a GitHub adapter profile.
5. Approve the minimum evidence packet required for a goal to enter review and close.
6. Select one Ouroboros or product-repository task for a second application exercise after the Hydra exercise.

## Safe next actions

- Review the 40-source ledger and flag unsupported or overgeneralized claims.
- Replace any product claim that lacks local validation with a hypothesis.
- Add independent sources only where a design decision depends on vendor consensus alone.
- Record decisions in the Issue and a human-gate review packet.
- Do not rename the plugin, update the marketplace manifest, or modify managed markers until approval is recorded.
