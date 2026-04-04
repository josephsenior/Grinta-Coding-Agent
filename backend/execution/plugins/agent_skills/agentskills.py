"""Aggregate agent skill functions and documentation helpers."""

from inspect import signature

from backend.execution.plugins.agent_skills import file_ops, file_reader
from backend.execution.plugins.agent_skills.file_editor import file_editor
from backend.execution.plugins.agent_skills.utils.dependency import import_functions

FILE_OPS_EXPORTS = [
    'find_file',
    'goto_line',
    'open_file',
    'scroll_down',
    'scroll_up',
    'search_dir',
    'search_file',
]
FILE_READER_EXPORTS = [
    'parse_audio',
    'parse_docx',
    'parse_image',
    'parse_latex',
    'parse_pdf',
    'parse_pptx',
    'parse_video',
]

import_functions(
    module=file_ops, function_names=FILE_OPS_EXPORTS, target_globals=globals()
)
import_functions(
    module=file_reader, function_names=FILE_READER_EXPORTS, target_globals=globals()
)
exported_names = FILE_OPS_EXPORTS + FILE_READER_EXPORTS
try:
    from backend.execution.plugins.agent_skills import repo_ops

    REPO_OPS_EXPORTS = [
        'explore_tree_structure',
        'get_entity_contents',
        'search_code_snippets',
    ]
    import_functions(
        module=repo_ops, function_names=REPO_OPS_EXPORTS, target_globals=globals()
    )
    exported_names += REPO_OPS_EXPORTS
except ImportError:
    pass
DOCUMENTATION = ''
for func_name in exported_names:
    func = globals()[func_name]
    cur_doc = func.__doc__ or 'No documentation available'
    cur_doc = '\n'.join(filter(None, (x.strip() for x in cur_doc.split('\n'))))
    cur_doc = '\n'.join(' ' * 4 + x for x in cur_doc.split('\n'))
    fn_signature = f'{func.__name__}{signature(func)!s}'
    DOCUMENTATION += f'{fn_signature}:\n{cur_doc}\n\n'
__all__ = ['file_editor']
