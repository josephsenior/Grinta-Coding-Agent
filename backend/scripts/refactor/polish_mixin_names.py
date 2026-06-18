"""One-shot polish: TUI mixin class names + file_editor mixin filenames."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT.parent

CLASS_REPLACEMENTS: list[tuple[str, str]] = [
    ('_AppRendererEventProcessorMixin', 'RendererEventProcessorMixin'),
    ('_AppRendererActionHandlersMixin', 'RendererActionHandlersMixin'),
    ('_AppRendererDisplayMixin', 'RendererDisplayMixin'),
    ('_AppRendererLiveMixin', 'RendererLiveMixin'),
    ('_AppRendererTerminalMixin', 'RendererTerminalMixin'),
    ('_AppRendererThinkingMixin', 'RendererThinkingMixin'),
    ('_AppScreenActionsMixin', 'ScreenActionsMixin'),
    ('_AppScreenCommunicateMixin', 'ScreenCommunicateMixin'),
    ('_AppScreenInputMixin', 'ScreenInputMixin'),
    ('_AppScreenLifecycleMixin', 'ScreenLifecycleMixin'),
    ('_AppScreenMessagesMixin', 'ScreenMessagesMixin'),
    ('_AppScreenSettingsMixin', 'ScreenSettingsMixin'),
    ('_AppScreenStateMixin', 'ScreenStateMixin'),
    ('_AppScreenWelcomeMixin', 'ScreenWelcomeMixin'),
    ('_FileEditorOpsMixin', 'FileEditorOpsMixin'),
    ('_FileEditorRollbackMixin', 'FileEditorRollbackMixin'),
    ('_FileEditorViewMixin', 'FileEditorViewMixin'),
]

IMPORT_REPLACEMENTS: list[tuple[str, str]] = [
    (
        'backend.execution.utils._file_editor_ops_mixin',
        'backend.execution.utils.file_editor.file_editor_ops_mixin',
    ),
    (
        'backend.execution.utils._file_editor_rollback_mixin',
        'backend.execution.utils.file_editor.file_editor_rollback_mixin',
    ),
    (
        'backend.execution.utils._file_editor_view_mixin',
        'backend.execution.utils.file_editor.file_editor_view_mixin',
    ),
]

FILE_RENAMES: list[tuple[str, str]] = [
    (
        'execution/utils/_file_editor_ops_mixin.py',
        'execution/utils/file_editor_ops_mixin.py',
    ),
    (
        'execution/utils/_file_editor_rollback_mixin.py',
        'execution/utils/file_editor_rollback_mixin.py',
    ),
    (
        'execution/utils/_file_editor_view_mixin.py',
        'execution/utils/file_editor_view_mixin.py',
    ),
]


def _rename_files() -> None:
    for old_rel, new_rel in FILE_RENAMES:
        src = ROOT / old_rel
        dst = ROOT / new_rel
        if src.exists():
            if dst.exists():
                raise RuntimeError(f'both exist: {old_rel} and {new_rel}')
            src.rename(dst)
            print(f'renamed {old_rel} -> {new_rel}')


def _rewrite_tree() -> None:
    skip = {'polish_mixin_names.py'}
    for base in [ROOT, REPO / 'docs']:
        if not base.exists():
            continue
        for path in base.rglob('*.py'):
            if path.name in skip:
                continue
            if 'site-packages' in path.parts:
                continue
            text = path.read_text(encoding='utf-8')
            new_text = text
            for old, new in IMPORT_REPLACEMENTS:
                new_text = new_text.replace(old, new)
            for old, new in CLASS_REPLACEMENTS:
                new_text = new_text.replace(old, new)
            if new_text != text:
                path.write_text(new_text, encoding='utf-8')
                print(f'updated {path.relative_to(REPO)}')


def main() -> None:
    _rename_files()
    _rewrite_tree()
    print('mixin polish complete')


if __name__ == '__main__':
    main()
