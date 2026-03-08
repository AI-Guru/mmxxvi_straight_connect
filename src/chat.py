import asyncio
import os

import gradio as gr
from langchain.chat_models import init_chat_model
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.graph import MessagesState, StateGraph, START
from langgraph.prebuilt import ToolNode, tools_condition

from src.config import build_mcp_json

_agent = None
_mcp_client = None


async def _startup():
    """Connect to MCP servers, list tools, test the chat model, build the agent."""
    global _agent, _mcp_client

    # Connect to MCP servers and list tools
    mcp_config = build_mcp_json()
    servers = {
        name: {"transport": "http", "url": cfg["url"]}
        for name, cfg in mcp_config["mcpServers"].items()
    }

    print("\nConnecting to MCP servers...")
    _mcp_client = MultiServerMCPClient(servers, tool_name_prefix=True)

    # Get tools per server to show which account they belong to
    all_tools = []
    for name in servers:
        server_tools = await _mcp_client.get_tools(server_name=name)
        print(f"\n  {name} ({servers[name]['url']})")
        for tool in server_tools:
            print(f"    - {tool.name}: {tool.description.splitlines()[0]}")
        all_tools.extend(server_tools)

    print(f"\n  Total: {len(all_tools)} tools")

    # Test the chat model
    chat_model = os.environ.get("CHAT_MODEL", "openai:gpt-4o")
    print(f"\nTesting chat model: {chat_model}")
    model = init_chat_model(chat_model)
    response = model.invoke("Say 'hello' and nothing else.")
    print(f"  Model response: {response.content}")

    # Build the agent
    def call_model(state: MessagesState):
        return {"messages": model.bind_tools(all_tools).invoke(state["messages"])}

    builder = StateGraph(MessagesState)
    builder.add_node("agent", call_model)
    builder.add_node("tools", ToolNode(all_tools))
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", tools_condition)
    builder.add_edge("tools", "agent")

    _agent = builder.compile()
    print("\nAgent ready.\n")


async def chat(message, history):
    messages = []
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": message})

    result = await _agent.ainvoke({"messages": messages})
    return result["messages"][-1].content


demo = gr.ChatInterface(fn=chat, title="Straight Connect")


def main():
    asyncio.run(_startup())
    demo.launch()


if __name__ == "__main__":
    main()
