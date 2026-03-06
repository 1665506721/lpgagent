from enum import Enum
from typing import List, Optional, Dict, Any

from pydantic import BaseModel, Field, ConfigDict, field_validator


class IntentEnum(str, Enum):
    CREATE_ORDER = "CREATE_ORDER"
    MODIFY_ORDER = "MODIFY_ORDER"
    QUERY_ORDER = "QUERY_ORDER"
    CREATE_TICKET = "CREATE_TICKET"
    QUERY_TICKET = "QUERY_TICKET"
    SAFETY_GUIDE = "SAFETY_GUIDE"
    UNKNOWN = "UNKNOWN"


class RiskLevelEnum(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ToolCall(BaseModel):
    tool_name: str
    input: dict = Field(default_factory=dict)


class AgentOutput(BaseModel):
    # 中文注释：忽略模型输出中的冗余字段，提升兼容性
    model_config = ConfigDict(extra="ignore")

    intent: IntentEnum
    tool_calls: List[ToolCall] = Field(default_factory=list)
    final_response: str
    risk_level: RiskLevelEnum
    need_human: bool
    ui_action: Optional[str] = None
    form: Optional[Dict[str, Any]] = None
    confirm_required: bool = False
    pending_action: Optional[Dict[str, Any]] = None
    routing: Optional[Dict[str, Any]] = None

    @field_validator("tool_calls", mode="before")
    def _normalize_tool_calls(cls, value):
        # 中文注释：兼容空值或非列表输出，统一为列表
        if value is None:
            return []
        if isinstance(value, list):
            return value
        return []
