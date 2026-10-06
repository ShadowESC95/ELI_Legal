from eli_legal.domain.errors import PolicyDenied


class ToolPolicy:
    def require(self, *, tool_id: str, approved_tool_ids: set[str]) -> None:
        if tool_id not in approved_tool_ids:
            raise PolicyDenied(f"tool not approved for matter: {tool_id}")
