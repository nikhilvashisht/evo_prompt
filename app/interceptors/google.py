import httpx
from typing import Optional, Any

class GoogleGenAIInterceptor:
    """Wraps a Google GenAI client instance to intercept Async models.generate_content calls

    and asynchronously ingest high-fidelity traces into evo_prompt.
    """
    def __init__(self, client: Any, server_url: str = "http://127.0.0.1:8000", prompt_version_id: Optional[str] = None):
        self._client = client
        self.server_url = server_url
        self.prompt_version_id = prompt_version_id
        
        # Monkey patch client.aio.models.generate_content
        if hasattr(client, "aio") and hasattr(client.aio, "models"):
            self._original_generate = client.aio.models.generate_content
            client.aio.models.generate_content = self._intercepted_generate
        else:
            print("[!] Google GenAI Interceptor: Could not find client.aio.models. Ensure Async client is initialized.")

    async def _intercepted_generate(self, *args, **kwargs) -> Any:
        contents = kwargs.get("contents")
        user_query = ""
        
        # Grab text of input prompt
        if contents:
            user_query = str(contents)
        elif len(args) > 1:
            user_query = str(args[1])
        elif len(args) == 1:
            user_query = str(args[0])

        # Call original Google Async GenAI completions call
        response = await self._original_generate(*args, **kwargs)
        
        try:
            llm_response = getattr(response, "text", "") or ""
            tool_calls = []
            
            candidates = getattr(response, "candidates", [])
            for candidate in candidates:
                parts = getattr(getattr(candidate, "content", None), "parts", [])
                for part in parts:
                    function_call = getattr(part, "function_call", None)
                    if function_call:
                        # Capture name and arguments dict
                        tc_name = getattr(function_call, "name", "")
                        tc_args = dict(getattr(function_call, "args", {}))
                        
                        tool_calls.append({
                            "tool_name": tc_name,
                            "arguments": tc_args,
                            "result": None,
                            "error": None
                        })
                        
            trace_payload = {
                "prompt_version_id": self.prompt_version_id,
                "user_query": str(user_query),
                "llm_response": str(llm_response),
                "tool_calls": tool_calls,
                "metadata": {
                    "model": kwargs.get("model", "unknown"),
                    "interceptor": "GoogleGenAIInterceptor"
                }
            }
            
            async with httpx.AsyncClient() as http_client:
                await http_client.post(
                    f"{self.server_url}/api/traces",
                    json=trace_payload,
                    timeout=3.0
                )
        except Exception as e:
            # Suppress interceptor errors
            print(f"[!] Google GenAI Interceptor Exception captured: {e}")
            
        return response
