"""Handlers for workflow and orchestration tools."""

import logging

from core.models import TaskPlan

logger = logging.getLogger("fleet.handlers.workflow")


async def handle_decompose_directive(params, db, cred_mgr, config, **ctx):
    orchestration = ctx.get("orchestration_engine")
    directive = params.get("directive", "")
    plan = await orchestration.decompose_directive(directive)
    return plan.model_dump()


async def handle_execute_task_plan(params, db, cred_mgr, config, **ctx):
    orchestration = ctx.get("orchestration_engine")
    plan_data = params.get("plan", {})
    plan = TaskPlan(**plan_data)
    results = await orchestration.execute_task_plan(plan)
    return {
        "directive": plan.directive,
        "results": {
            str(k): v.model_dump() for k, v in results.items()
        },
        "total_steps": len(plan.steps),
        "completed": len(results),
    }


async def handle_list_workflows(params, db, cred_mgr, config, **ctx):
    workflow = ctx.get("workflow_engine")
    return {"workflows": workflow.list_workflows()}


async def handle_execute_workflow(params, db, cred_mgr, config, **ctx):
    workflow = ctx.get("workflow_engine")
    name = params.get("workflow_name", "")
    return await workflow.execute_workflow(name)
