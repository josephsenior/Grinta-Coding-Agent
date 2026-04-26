import sys
sys.path.insert(0, '.')
from types import SimpleNamespace
from backend.engine.prompts.prompt_builder import measure_system_prompt_sections

cfg_full = SimpleNamespace(
    autonomy_level="balanced",
    enable_checkpoints=True,
    enable_lsp_query=False,
    enable_internal_task_tracker=True,
    enable_permissions=False,
    enable_meta_cognition=True,
    enable_working_memory=True,
    enable_condensation_request=True,
    enable_think=True,
    enable_terminal=True,
)

mcp_tool_names = [f"tool_{i}" for i in range(17)]
mcp_tool_descriptions = {f"tool_{i}": f"Description of tool {i} for performing action {i}." for i in range(17)}

for model_id, is_windows in [
    ("gpt-4o", False),
    ("gpt-4o", True),
    ("claude-3-5-sonnet-20241022", True),
    ("google/gemini-2.5-flash", True),
]:
    report = measure_system_prompt_sections(
        active_llm_model=model_id,
        is_windows=is_windows,
        config=cfg_full,
        mcp_tool_names=mcp_tool_names,
        mcp_tool_descriptions=mcp_tool_descriptions,
        mcp_server_hints=[],
        function_calling_mode="native",
    )
    print(f"model={model_id} windows={is_windows}: {report['total_tokens']} tokens ({report['total_encoding']}) / {report['total_chars']} chars")
