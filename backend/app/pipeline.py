"""Pure Python Async Pipeline Orchestrator.

Sequentially executes the 7 explicit research stages:
1. Planning (stage1_planning.py)
2. Discovery (stage2_discovery.py)
3. Retrieval (stage3_retrieval.py)
4. Analysis (stage4_analysis.py)
5. Cross-Source Analysis (stage5_cross_analysis.py)
6. Synthesis (stage6_synthesis.py)
7. Validation (stage7_validation.py)

Includes the clarification pause and the bounded validation repair loop without
requiring LangGraph.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from app.config import Settings, get_settings
from app.models import (
    ResearchState,
    RunStatus,
    new_state,
)
from app.stage1_planning import run_planning
from app.stage2_discovery import run_discovery
from app.stage3_retrieval import run_retrieval
from app.stage4_analysis import run_analysis
from app.stage5_cross_analysis import run_cross_analysis
from app.stage6_synthesis import run_synthesis
from app.stage7_validation import run_validation

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[RunStatus, ResearchState], Awaitable[None]]


async def execute_research_pipeline(
    state: ResearchState,
    settings: Settings,
    on_progress: ProgressCallback | None = None,
) -> ResearchState:
    """Run all 7 stages in order, reporting progress after each stage."""

    async def report(status: RunStatus):
        state["status"] = status
        if on_progress:
            await on_progress(status, state)

    try:
        # -------------------------------------------------------------
        # Stage 1: Planning
        # -------------------------------------------------------------
        await report(RunStatus.PLANNING)
        plan = await asyncio.to_thread(
            run_planning,
            state["research_question"],
            settings,
            state.get("clarification_response"),
        )
        state["plan"] = plan

        if plan.needs_clarification:
            await report(RunStatus.AWAITING_CLARIFICATION)
            return state

        # -------------------------------------------------------------
        # Stage 2: Discovery
        # -------------------------------------------------------------
        await report(RunStatus.DISCOVERY)
        sources, provider_errors = await run_discovery(plan, settings)
        state["sources"] = sources
        state["provider_errors"] = provider_errors

        # -------------------------------------------------------------
        # Stage 3: Retrieval
        # -------------------------------------------------------------
        await report(RunStatus.RETRIEVAL)
        retrieved_docs = await run_retrieval(sources, settings)
        state["retrieved_documents"] = retrieved_docs

        # -------------------------------------------------------------
        # Stage 4: Analysis
        # -------------------------------------------------------------
        await report(RunStatus.ANALYSIS)
        source_analyses = await run_analysis(sources, retrieved_docs, plan)
        state["source_analyses"] = source_analyses

        # -------------------------------------------------------------
        # Stage 5: Cross-Source Analysis
        # -------------------------------------------------------------
        await report(RunStatus.CROSS_ANALYSIS)
        cross_analysis = await asyncio.to_thread(run_cross_analysis, source_analyses, plan)
        state["cross_source_analysis"] = cross_analysis

        # -------------------------------------------------------------
        # Stages 6 & 7: Synthesis & Validation Loop
        # -------------------------------------------------------------
        repair_feedback: list[str] | None = None
        max_attempts = max(1, settings.max_validation_repair_attempts)

        for attempt in range(1, max_attempts + 1):
            state["validation_attempts"] = attempt

            # Stage 6: Synthesis
            await report(RunStatus.SYNTHESIS)
            report_doc = await asyncio.to_thread(
                run_synthesis,
                plan,
                sources,
                source_analyses,
                cross_analysis,
                repair_feedback,
            )
            state["report"] = report_doc

            # Stage 7: Validation
            await report(RunStatus.VALIDATION)
            validation_result = await asyncio.to_thread(
                run_validation,
                report_doc,
                sources,
                source_analyses,
                attempt,
            )
            state["validation"] = validation_result

            if validation_result.passed:
                break

            # Collect errors to guide the next repair attempt
            repair_feedback = [i.description for i in validation_result.issues if i.severity == "error"]
            if not repair_feedback:
                break

        await report(RunStatus.COMPLETED)
        return state

    except asyncio.CancelledError:
        logger.info("Research run %s was cancelled.", state.get("run_id"))
        state["status"] = RunStatus.CANCELLED
        if on_progress:
            await on_progress(RunStatus.CANCELLED, state)
        raise

    except Exception as exc:
        logger.exception("Research run %s encountered an error: %s", state.get("run_id"), exc)
        state["status"] = RunStatus.FAILED
        state["errors"] = [*state.get("errors", []), str(exc)]
        if on_progress:
            await on_progress(RunStatus.FAILED, state)
        return state


# ---------------------------------------------------------------------------
# Background Task & Run Lifecycle Management
# ---------------------------------------------------------------------------

class RunManager:
    """Manages asynchronous background execution of research runs."""

    def __init__(self):
        self._tasks: dict[str, asyncio.Task] = {}

    def launch(
        self,
        run_id: str,
        initial_state: ResearchState,
        on_progress: ProgressCallback,
    ) -> asyncio.Task:
        settings = get_settings()

        async def _wrapper():
            try:
                await execute_research_pipeline(initial_state, settings, on_progress)
            finally:
                self._tasks.pop(run_id, None)

        task = asyncio.create_task(_wrapper())
        self._tasks[run_id] = task
        return task

    def cancel(self, run_id: str) -> bool:
        task = self._tasks.get(run_id)
        if task and not task.done():
            task.cancel()
            return True
        return False

    def is_running(self, run_id: str) -> bool:
        task = self._tasks.get(run_id)
        return task is not None and not task.done()


run_manager = RunManager()
