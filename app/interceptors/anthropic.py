import httpx
from typing import Optional, Any

class AnthropicInterceptor:
    """Wraps an AsyncAnthropic client instance to intercept messages completion calls

    and asynchronously ingest high-fidelity traces into evo_prompt.
    """
    def __init__(self, client: Any, server_url: str = "http://127.0.0.1:8000", prompt_version_id: Optional[str] = None):
        self._client = client
        self.server_url = server_url
        self.prompt_version_id = prompt_version_id
        
        # Monkey patch client.messages.create
        self._original_create = client.messages.create
        client.messages.create = self._intercepted_create

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
                
        # Call original Anthropic completions call
        response = await self._original_create(*args, **kwargs)
        
        try:
            # Safe parsing of Anthropic content blocks
            llm_response = ""
            tool_calls = []
            
            content_blocks = getattr(response, "content", [])
            for block in content_blocks:
                block_type = getattr(block, "type", "text")
                if block_type == "text":
                    llm_response += getattr(block, "text", "")
                elif block_type == "tool_use":
                    tool_calls.append({
                        "tool_name": getattr(block, "name", ""),
                        "arguments": getattr(block, "input", {}),
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
                    "interceptor": "AnthropicInterceptor"
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
            print(f"[!] Anthropic Interceptor Exception captured: {e}")
            
        return response
