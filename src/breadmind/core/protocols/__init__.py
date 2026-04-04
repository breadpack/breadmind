"""프로토콜 정의 (계약만, 구현 없음)."""
from breadmind.core.protocols.provider import (
    Attachment, Message, LLMResponse, TokenUsage, ToolCallRequest, CacheStrategy, ProviderProtocol,
)
from breadmind.core.protocols.prompt import (
    PromptBlock, PromptContext, CompactResult, PromptProtocol,
)
from breadmind.core.protocols.tool import (
    ToolDefinition, ToolSchema, ToolCall, ToolResult, ToolFilter, ExecutionContext, ToolProtocol,
)
from breadmind.core.protocols.memory import (
    Episode, KGTriple, MemoryProtocol,
)
from breadmind.core.protocols.agent import (
    AgentContext, AgentResponse, AgentProtocol,
)
from breadmind.core.protocols.runtime import (
    UserInput, AgentOutput, Progress, RuntimeProtocol,
)

__all__ = [
    "Attachment", "Message", "LLMResponse", "TokenUsage", "ToolCallRequest", "CacheStrategy", "ProviderProtocol",
    "PromptBlock", "PromptContext", "CompactResult", "PromptProtocol",
    "ToolDefinition", "ToolSchema", "ToolCall", "ToolResult", "ToolFilter", "ExecutionContext", "ToolProtocol",
    "Episode", "KGTriple", "MemoryProtocol",
    "AgentContext", "AgentResponse", "AgentProtocol",
    "UserInput", "AgentOutput", "Progress", "RuntimeProtocol",
]
