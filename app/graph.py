from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from app.checkpointer import make_checkpointer
from app.nodes.analyzer import analyze
from app.nodes.approval import approval, route_after_approval
from app.nodes.critic import critique
from app.nodes.executor import execute
from app.nodes.intake import intake
from app.nodes.research import (
    dispatch_research,
    plan_research,
    research_history,
    research_kb,
    research_web,
)
from app.nodes.researcher import propose
from app.nodes.risk import classify, route_after_risk
from app.nodes.sandbox import route_after_sandbox, run_sandbox
from app.nodes.scoring import route_after_scoring, score
from app.state import OpsFlowState

def build_graph(checkpointer: BaseCheckpointSaver | None = None):

    builder = StateGraph(OpsFlowState)

    builder.add_node("intake", intake)
    builder.add_node("analyzer", analyze)
    builder.add_node("plan_research", plan_research)
    builder.add_node("research_kb", research_kb)
    builder.add_node("research_web", research_web)
    builder.add_node("research_history", research_history)
    builder.add_node("propose", propose)
    builder.add_node("critic", critique)
    builder.add_node("scoring", score)
    builder.add_node("risk", classify)
    builder.add_node("sandbox", run_sandbox)
    builder.add_node("approval", approval)
    builder.add_node("executor", execute)

    builder.add_edge(START, "intake")
    builder.add_edge("intake", "analyzer")
    builder.add_edge("analyzer", "plan_research")

    builder.add_conditional_edges(
        "plan_research",
        dispatch_research,
        ["research_kb", "research_web", "research_history"],
    )

    builder.add_edge("research_kb", "propose")
    builder.add_edge("research_web", "propose")
    builder.add_edge("research_history", "propose")

    builder.add_edge("propose", "critic")
    builder.add_edge("critic", "scoring")

    builder.add_conditional_edges(
        "scoring",
        route_after_scoring,
        {"accept": "risk", "refine": "plan_research", "escalate": END},
    )

    builder.add_conditional_edges(
        "risk",
        route_after_risk,
        {"execute": "sandbox", "await_approval": "sandbox", "reject": END},
    )

    builder.add_conditional_edges(
        "sandbox",
        route_after_sandbox,
        {"approval": "approval", "execute": "executor", "retry": "propose", "escalate": END},
    )

    builder.add_conditional_edges(
        "approval",
        route_after_approval,
        {"execute": "executor", "reject": END},
    )

    builder.add_edge("executor", END)

    return builder.compile(checkpointer=checkpointer)

graph = build_graph(make_checkpointer())