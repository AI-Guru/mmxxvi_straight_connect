import gradio as gr
from langchain_anthropic import ChatAnthropic
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.graph import MessagesState, StateGraph, START
from langgraph.prebuilt import ToolNode, tools_condition

from src.config import build_mcp_json

_agent = None
_mcp_client = None


async def _get_agent():
    global _agent, _mcp_client
    if _agent is not None:
        return _agent

    mcp_config = build_mcp_json()
    servers = {
        name: {"transport": "http", "url": cfg["url"]}
        for name, cfg in mcp_config["mcpServers"].items()
    }

    _mcp_client = MultiServerMCPClient(servers)
    tools = await _mcp_client.get_tools()

    model = ChatAnthropic(model="claude-sonnet-4-5-20250929")

    def call_model(state: MessagesState):
        return {"messages": model.bind_tools(tools).invoke(state["messages"])}

    builder = StateGraph(MessagesState)
    builder.add_node("agent", call_model)
    builder.add_node("tools", ToolNode(tools))
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", tools_condition)
    builder.add_edge("tools", "agent")

    _agent = builder.compile()
    return _agent


async def chat(message, history):
    agent = await _get_agent()

    messages = []
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": message})

    result = await agent.ainvoke({"messages": messages})
    return result["messages"][-1].content


demo = gr.ChatInterface(fn=chat, title="Straight Connect")


def main():
    demo.launch()


if __name__ == "__main__":
    main()
