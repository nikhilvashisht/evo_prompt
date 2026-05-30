import json
import httpx
from typing import Optional, Any, Dict

class OpenAIInterceptor:
    """Wraps an AsyncOpenAI client instance to intercept chat completion calls

    and asynchronously ingest high-fidelity traces into evo_prompt.
    """
    def __init__(self, client: Any, server_url: str = "http://127.0.0.1:8000", prompt_version_id: Optional[str] = None):
        self._client = client
        self.server_url = server_url
        self.prompt_version_id = prompt_version_id
        
        # Monkey patch client.chat.completions.create
        self._original_create = client.chat.completions.create
        client.chat.completions.create = self._intercepted_create

    async def _intercepted_create(self, *args, **kwargs) -> Any:
        messages = kwargs.get("messages", [])
        
        # Extract user query
        user_query = ""
        for msg in reversed(messages):
            if isinstance(msg, dict) and msg.get("role") == "user":
                user_query = msg.get("content", "")
                break
            elif hasattr(msg, "role") and getattr(msg, "role") == "user":
                user_query = getattr(msg, "content", "")
                break
                
        # Call original OpenAI API completions call
        response = await self._original_create(*args, **kwargs)
        
        try:
            # Safe parsing of OpenAI response object
            choice = response.choices[0]
            message_obj = choice.message
            llm_response = getattr(message_obj, "content", "") or ""
            
            tool_calls_raw = getattr(message_obj, "tool_calls", []) or []
            tool_calls = []
            
            for tc in tool_calls_raw:
                # Capture standard tool parameters
                tc_name = getattr(tc.function, "name", "")
                tc_args_str = getattr(tc.function, "arguments", "{}")
                try:
                    tc_args = json.loads(tc_args_str)
                except Exception:
                    tc_args = {"raw_arguments": tc_args_str}
                    
                tool_calls.append({
                    "tool_name": tc_name,
                    "arguments": tc_args,
                    "result": None,
                    "error": None
                })
                
            # Asynchronously POST trace payload to our local ingestion backend
            trace_payload = {
                "prompt_version_id": self.prompt_version_id,
                "user_query": str(user_query),
                "llm_response": str(llm_response),
                "tool_calls": tool_calls,
                "metadata": {
                    "model": kwargs.get("model", "unknown"),
                    "temperature": kwargs.get("temperature", 1.0),
                    "interceptor": "OpenAIInterceptor"
                }
            }
            
            async with httpx.AsyncClient() as http_client:
                await http_client.post(
                    f"{self.server_url}/api/traces",
                    json=trace_payload,
                    timeout=3.0
                )
        except Exception as e:
            # Suppress interceptor errors to prevent user's main application from breaking
            print(f"[!] OpenAI Interceptor Exception captured: {e}")
            
        return response
