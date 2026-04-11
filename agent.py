import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from google import genai
from google.genai import types

client = genai.Client()

async def call_tools(session, response):
    results = []
    for part in response.candidates[0].content.parts:
        if part.function_call:
            fc = part.function_call
            result = await session.call_tool(fc.name, dict(fc.args))
            results.append(types.Part.from_function_response(
                name=fc.name,
                response={"result": result.content[0].text}
            ))
    return results

async def run():
    async with streamablehttp_client("http://localhost:8000/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()

            gemini_tools = [
                types.FunctionDeclaration(
                    name=t.name,
                    description=t.description,
                    parameters=t.inputSchema
                )
                for t in tools.tools
            ]

            chat = client.aio.chats.create(
                model="gemini-2.5-flash",
                config=types.GenerateContentConfig(
                    tools=[types.Tool(function_declarations=gemini_tools)],
                    system_instruction="You are a Kubernetes cluster assistant for a KIND cluster. Use the available tools to answer questions about the cluster state, logs, and events. Be concise."
                )
            )

            print("Ghost Cluster Agent ready. Type 'exit' to quit.\n")

            while True:
                user_input = input("You: ").strip()
                if user_input.lower() in ("exit", "quit"):
                    break
                if not user_input:
                    continue

                response = await chat.send_message(user_input)

                while any(part.function_call for part in response.candidates[0].content.parts):
                    tool_results = await call_tools(session, response)
                    response = await chat.send_message(tool_results)

                print(f"\nAgent: {response.text}\n")

asyncio.run(run())
