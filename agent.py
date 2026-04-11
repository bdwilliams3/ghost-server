import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from google import genai
from google.genai import types

client = genai.Client()

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
                    tools=[types.Tool(function_declarations=gemini_tools)]
                )
            )

            ans = await chat.send_message("List all pods across all namespaces")

            for part in ans.candidates[0].content.parts:
                if part.function_call:
                    fc = part.function_call
                    result = await session.call_tool(fc.name, dict(fc.args))
                    print(f"Tool: {fc.name}\nResult: {result.content[0].text}")
                elif part.text:
                    print(part.text)

asyncio.run(run())