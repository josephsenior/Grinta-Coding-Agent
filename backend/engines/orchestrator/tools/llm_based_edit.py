"""LLM-assisted file editing tool configuration for CodeAct."""

from backend.engines.orchestrator.tools.common import (
    create_tool_definition,
    get_path_param,
    get_security_risk_param,
)
from backend.engines.orchestrator.contracts import ChatCompletionToolParam

_FILE_EDIT_DESCRIPTION = 'Edit a file in plain-text format.\n* The assistant can edit files by specifying the file path and providing a draft of the new file content.\n* The draft content doesn\'t need to be exactly the same as the existing file; the assistant may skip unchanged lines using comments like `# ... existing code ...` to indicate unchanged sections.\n* IMPORTANT: For large files (e.g., > 300 lines), specify the range of lines to edit using `start` and `end` (1-indexed, inclusive). The range should be smaller than 300 lines.\n* -1 indicates the last line of the file when used as the `start` or `end` value.\n* Keep at least one unchanged line before the changed section and after the changed section wherever possible.\n* Make sure to set the `start` and `end` to include all the lines in the original file referred to in the draft of the new file content. Failure to do so will result in bad edits.\n* To append to a file, set both `start` and `end` to `-1`.\n* If the file doesn\'t exist, a new file will be created with the provided content.\n* IMPORTANT: Make sure you include all the required indentations for each line of code in the draft, otherwise the edited code will be incorrectly indented.\n* IMPORTANT: Make sure that the first line of the draft is also properly indented and has the required whitespaces.\n* IMPORTANT: NEVER include or make references to lines from outside the `start` and `end` range in the draft.\n* IMPORTANT: Start the content with a comment in the format: #EDIT: Reason for edit\n* IMPORTANT: If you are not appending to the file, avoid setting `start` and `end` to the same value.\n\n**Example 1: general edit for short files**\nFor example, given an existing file `/path/to/file.py` that looks like this:\n(this is the beginning of the file)\n1|class MyClass:\n2|    def __init__(self):\n3|        self.x = 1\n4|        self.y = 2\n5|        self.z = 3\n6|\n7|print(MyClass().z)\n8|print(MyClass().x)\n(this is the end of the file)\n\nThe assistant wants to edit the file to look like this:\n(this is the beginning of the file)\n1|class MyClass:\n2|    def __init__(self):\n3|        self.x = 1\n4|        self.y = 2\n5|\n6|print(MyClass().y)\n(this is the end of the file)\n\nThe assistant may produce an edit action like this:\npath="/path/to/file.txt" start=1 end=-1\ncontent=```\n#EDIT: I want to change the value of y to 2\nclass MyClass:\n    def __init__(self):\n        # ... existing code ...\n        self.y = 2\n\nprint(MyClass().y)\n```\n\n**Example 2: append to file for short files**\nFor example, given an existing file `/path/to/file.py` that looks like this:\n(this is the beginning of the file)\n1|class MyClass:\n2|    def __init__(self):\n3|        self.x = 1\n4|        self.y = 2\n5|        self.z = 3\n6|\n7|print(MyClass().z)\n8|print(MyClass().x)\n(this is the end of the file)\n\nTo append the following lines to the file:\n```python\n#EDIT: I want to print the value of y\nprint(MyClass().y)\n```\n\nThe assistant may produce an edit action like this:\npath="/path/to/file.txt" start=-1 end=-1\ncontent=```\nprint(MyClass().y)\n```\n\n**Example 3: edit for long files**\n\nGiven an existing file `/path/to/file.py` that looks like this:\n(1000 more lines above)\n1001|class MyClass:\n1002|    def __init__(self):\n1003|        self.x = 1\n1004|        self.y = 2\n1005|        self.z = 3\n1006|\n1007|print(MyClass().z)\n1008|print(MyClass().x)\n(2000 more lines below)\n\nThe assistant wants to edit the file to look like this:\n\n(1000 more lines above)\n1001|class MyClass:\n1002|    def __init__(self):\n1003|        self.x = 1\n1004|        self.y = 2\n1005|\n1006|print(MyClass().y)\n(2000 more lines below)\n\nThe assistant may produce an edit action like this:\npath="/path/to/file.txt" start=1002 end=1008\ncontent=```\n#EDIT: I want to change the value of y to 2\n    def __init__(self):\n        # no changes before\n        self.y = 2\n        # self.z is removed\n\n# MyClass().z is removed\nprint(MyClass().y)\n```\n'


def create_llm_based_edit_tool() -> ChatCompletionToolParam:
    """Create the LLM-based file editing tool for the CodeAct agent."""
    return create_tool_definition(
        name="edit_file",
        description=_FILE_EDIT_DESCRIPTION,
        properties={
            "path": get_path_param("The absolute path to the file to be edited."),
            "content": {
                "type": "string",
                "description": "A draft of the new content for the file being edited. Note that the assistant may skip unchanged lines.",
            },
            "start": {
                "type": "integer",
                "description": "The starting line number for the edit (1-indexed, inclusive). Default is 1.",
            },
            "end": {
                "type": "integer",
                "description": "The ending line number for the edit (1-indexed, inclusive). Default is -1 (end of file).",
            },
            "security_risk": get_security_risk_param(),
        },
        required=["path", "content", "security_risk"],
    )
