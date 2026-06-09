import logging
from typing import Any

import database
from core.event_bus import bus
from core.events import ConsensusRequested, ConsensusEvaluated

log = logging.getLogger(__name__)


class ConsensusEngine:
    def __init__(self, event_bus=None):
        self.bus = event_bus or bus

    async def evaluate(
        self,
        operation: str,
        votes: dict[str, str],
        override_token: str | None = None,
        rationale: str = "",
        details: dict[str, Any] | None = None,
    ) -> str:
        """
        Evaluate E5 consensus based on the votes of council roles (SA, SRE, META, AC).
        """
        # Emit ConsensusRequested event
        try:
            req_event = ConsensusRequested(
                operation=operation,
                requester="ConsensusEngine",
                details=details or {},
            )
            await self.bus.emit(req_event)
        except Exception as e:
            log.error(f"Failed to emit ConsensusRequested event: {e}", exc_info=True)

        # Normalize role keys and verdicts to uppercase
        sa_verdict = votes.get("sa", votes.get("SA", "BLOCK")).upper()
        sre_verdict = votes.get("sre", votes.get("SRE", "BLOCK")).upper()
        meta_verdict = votes.get("meta", votes.get("META", "BLOCK")).upper()
        ac_verdict = votes.get("ac", votes.get("AC", "BLOCK")).upper()

        all_verdicts = [sa_verdict, sre_verdict, meta_verdict, ac_verdict]

        # Check override tokens first
        if override_token in ("[creative_violation]", "[documentation_only]"):
            final_verdict = "GO"
            rationale_prefix = f"[OVERRIDE: {override_token}] "
            final_rationale = rationale_prefix + rationale
        else:
            final_rationale = rationale
            # Check for critical operations
            if operation in (
                "disable_circuit_breaker",
                "schema_upgrade",
                "key_rotation",
            ):
                # Critical E5: Requires all roles to vote GO or WARN (any single BLOCK fails consensus)
                if any(v == "BLOCK" for v in all_verdicts):
                    final_verdict = "BLOCK"
                else:
                    final_verdict = "GO"
            else:
                # Standard E5: Requires majority (at least 3 roles vote GO or WARN)
                go_warn_count = sum(1 for v in all_verdicts if v in ("GO", "WARN"))
                if go_warn_count >= 3:
                    final_verdict = "GO"
                else:
                    final_verdict = "BLOCK"

        # Write to DB
        try:
            await database.insert_consensus_audit_log(
                operation=operation,
                sa_verdict=sa_verdict,
                sre_verdict=sre_verdict,
                meta_verdict=meta_verdict,
                ac_verdict=ac_verdict,
                final_verdict=final_verdict,
                override_token=override_token,
                rationale=final_rationale,
                details=details or {},
            )
        except Exception as e:
            log.error(f"Failed to insert consensus audit log: {e}", exc_info=True)

        # Emit ConsensusEvaluated event
        try:
            event = ConsensusEvaluated(
                operation=operation,
                sa_verdict=sa_verdict,
                sre_verdict=sre_verdict,
                meta_verdict=meta_verdict,
                ac_verdict=ac_verdict,
                final_verdict=final_verdict,
                override_token=override_token,
                rationale=final_rationale,
            )
            await self.bus.emit(event)
        except Exception as e:
            log.error(f"Failed to emit ConsensusEvaluated event: {e}", exc_info=True)

        return final_verdict
