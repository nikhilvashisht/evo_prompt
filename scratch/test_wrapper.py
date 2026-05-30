import asyncio
from unittest.mock import AsyncMock, MagicMock
from backend.app.interceptors import OpenAIInterceptor

# Mock AsyncOpenAI Client
class MockAsyncOpenAI:
    def __init__(self):
        self.chat = MagicMock()
        self.chat.completions = MagicMock()
        
        # Async mock for completions create
        async_create = AsyncMock()
        
        # Setup mock response matching OpenAI SDK structure
        mock_choice = MagicMock()
        mock_choice.message = MagicMock()
        mock_choice.message.content = "Here is your quick summary: I don't know how to query the target database since the connection is inactive."
        
        # Mock tool call
        mock_tool = MagicMock()
        mock_tool.function = MagicMock()
        mock_tool.function.name = "query_database"
        mock_tool.function.arguments = '{"table": "users", "limit": 10}'
        mock_choice.message.tool_calls = [mock_tool]
        
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        
        async_create.return_value = mock_response
        self.chat.completions.create = async_create

async def run_simulation():
    print("=" * 60)
    print("      MOCK OPENAI INTERCEPTOR SIMULATION RUNNER")
    print("=" * 60)
    
    # 1. Initialize Mock client
    mock_client = MockAsyncOpenAI()
    
    # 2. Hook interceptor (assumes local FastAPI server is running on localhost:8000)
    print("[*] Wrapping client with OpenAIInterceptor...")
    OpenAIInterceptor(mock_client, server_url="http://127.0.0.1:8000", prompt_version_id="seed-v1")
    
    # 3. Trigger mock completions call
    print("[*] Triggering mock client completions call...")
    try:
        response = await mock_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a database query assistant."},
                {"role": "user", "content": "Fetch details for the first 10 user rows."}
            ],
            temperature=0.7
        )
        print("[+] Mock Completions Completed.")
        print(f"[+] Returned Content: '{response.choices[0].message.content}'")
        print("[+] Interceptor has fired trace post. Check trace console dashboard!")
    except Exception as e:
        print(f"[-] Execution issue: {e}")

if __name__ == "__main__":
    asyncio.run(run_simulation())
