from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from textual import events, work

from backend.cli.event_rendering.panels import task_panel_signature
from backend.cli.tui.constants import _tui_logger
from backend.cli.tui.dialogs import (  # noqa: F401
    GrintaAddMCPDialog,
    GrintaAddSkillDialog,
    GrintaConfirmDialog,
)
from backend.cli.tui.widgets.small import (
    InputBar,
)
from backend.cli.tui.widgets.collapsible import SidebarRow
from backend.core.interaction_modes import (
    AGENT_MODE,
    VISIBLE_INTERACTION_MODES,
    is_chat_mode,
    normalize_interaction_mode,
)


class ScreenSettingsMixin:
    """Settings-related methods of GrintaScreen."""

    def on_focus(self, event: events.Focus) -> None:
        if event.control and event.control.id == 'input':
            try:
                self.query_one('#input-bar', InputBar).remove_class('-blurred')
            except Exception:
                pass

    def on_blur(self, event: events.Blur) -> None:
        if event.control and event.control.id == 'input':
            try:
                self.query_one('#input-bar', InputBar).add_class('-blurred')
            except Exception:
                pass

    def on_resize(self, event: events.Resize) -> None:
        self._resize_input_bar()

    def _apply_autonomy_level(self, new_level: str) -> None:
        level = self._visible_autonomy_level(new_level)
        if level not in {'conservative', 'balanced', 'full'}:
            return
        previous = self._current_autonomy_level()
        if previous == level and self._hud.state.autonomy_level == level:
            return
        controller = self._controller
        if controller is not None:
            ac = getattr(controller, 'autonomy_controller', None)
            if ac is not None:
                ac.autonomy_level = level
        agent_config = self._active_agent_config()
        if agent_config is not None:
            try:
                agent_config.autonomy_level = level
            except Exception:
                pass
        try:
            setattr(self._config, 'autonomy_level', level)
        except Exception:
            pass
        self._hud.update_autonomy(level)
        self._render_hud_bar()
        if previous != level:
            self.notify(f'Autonomy: {level}', severity='information', timeout=2.0)

    def _apply_hud_reasoning_effort(self, effort_value: str) -> None:
        if getattr(self, '_hud_reasoning_syncing', False):
            return
        effort = str(effort_value or '').strip().lower()
        from backend.cli.settings import (
            get_current_model,
            get_current_provider,
            get_persisted_reasoning_effort,
            update_model,
        )
        from backend.core.config import load_app_config

        if effort == get_persisted_reasoning_effort().strip().lower():
            return
        try:
            update_model(
                get_current_model(self._config),
                provider=get_current_provider(self._config),
                reasoning_effort=effort or None,
            )
        except Exception as exc:
            self.notify(
                f'Reasoning update failed: {type(exc).__name__}',
                severity='error',
                timeout=3.0,
            )
            return
        self._config = load_app_config()
        runtime_status = self._apply_llm_config_to_active_session(self._config)
        self._render_hud_bar()
        label = effort or 'default'
        self.notify(
            f'Reasoning: {label} ({runtime_status})',
            severity='information',
            timeout=2.5,
        )

    def _propagate_mode_to_agent(self, mode: str) -> None:
        agent_config = self._active_agent_config()
        if agent_config is not None:
            agent_config.mode = mode
        controller = self._controller
        if controller is None:
            return
        self._apply_mode_to_controller(controller, mode)
        self._update_mode_extra_data(controller, mode)

    def _apply_mode_to_controller(self, controller, mode: str) -> None:
        agent = getattr(controller, 'agent', None)
        if agent is None:
            return
        running_config = getattr(agent, 'config', None)
        if running_config is not None:
            running_config.mode = mode
        planner = getattr(agent, 'planner', None)
        planner_config = getattr(planner, '_config', None)
        if planner_config is not None:
            planner_config.mode = mode
        if planner is not None and hasattr(planner, 'build_toolset'):
            try:
                agent.tools = planner.build_toolset()
            except Exception:
                _tui_logger.debug(
                    'Failed to rebuild toolset on mode change', exc_info=True
                )

    def _update_mode_extra_data(self, controller, mode: str) -> None:
        state = getattr(controller, 'state', None)
        extra_data = getattr(state, 'extra_data', None) if state is not None else None
        if not isinstance(extra_data, dict):
            return
        if is_chat_mode(mode):
            extra_data.pop('active_run_mode', None)
        else:
            extra_data['active_run_mode'] = mode

    def _apply_mode(self, new_mode: str) -> None:
        mode = normalize_interaction_mode(new_mode, default='')
        if mode not in set(VISIBLE_INTERACTION_MODES):
            return
        self._propagate_mode_to_agent(mode)
        self._render_hud_bar()
        self._update_input_identity(mode)
        self._toggle_autonomy_tabs_visibility(mode)
        self.notify(f'Mode: {mode}', severity='information', timeout=2.0)

    def _apply_llm_config_to_active_session(self, config) -> str:
        controller = self._controller
        if controller is None:
            return 'saved for new sessions'
        try:
            state = controller.get_agent_state()
        except Exception:
            state = None
        if 'RUNNING' in str(state).upper():
            self._pending_llm_config_apply = True
            return 'saved; active run keeps current model until it is idle'

        agent = getattr(controller, 'agent', None)
        if agent is None:
            return 'saved; no active agent to update'
        registry = getattr(agent, 'llm_registry', None)
        if registry is None:
            return 'saved; active session has no LLM registry'

        llm_config = config.get_llm_config()
        try:
            registry.config = copy.deepcopy(config)
            registry.agent_to_llm_config = registry.config.get_agent_to_llm_config_map()
        except Exception:
            _tui_logger.debug(
                'Failed to refresh registry config during model switch',
                exc_info=True,
            )
        replace_llm = getattr(registry, 'replace_llm', None)
        if callable(replace_llm):
            llm = replace_llm('agent', llm_config)
        else:
            service_to_llm = getattr(registry, 'service_to_llm', None)
            if isinstance(service_to_llm, dict):
                service_to_llm.pop('agent', None)
            llm = registry.get_llm('agent', llm_config)

        set_llm = getattr(agent, 'set_llm', None)
        if callable(set_llm):
            set_llm(llm)
        else:
            setattr(agent, 'llm', llm)

        running_config = getattr(agent, 'config', None)
        if running_config is not None:
            try:
                running_config.llm_config = llm_config
            except Exception:
                _tui_logger.debug(
                    'Failed to update active agent config LLM during model switch',
                    exc_info=True,
                )

        planner = getattr(agent, 'planner', None)
        planner_config = getattr(planner, '_config', None)
        if planner_config is not None:
            try:
                planner_config.llm_config = llm_config
            except Exception:
                _tui_logger.debug(
                    'Failed to update planner config LLM during model switch',
                    exc_info=True,
                )
        if planner is not None and hasattr(planner, 'build_toolset'):
            try:
                agent.tools = planner.build_toolset()
            except Exception:
                _tui_logger.debug(
                    'Failed to rebuild toolset after model switch',
                    exc_info=True,
                )

        self._refresh_prompt_managers_after_llm_switch(agent, registry)

        try:
            agent_name = getattr(getattr(agent, 'config', None), 'name', None)
            controller.agent_to_llm_config['agent'] = llm_config
            if isinstance(agent_name, str) and agent_name.strip():
                controller.agent_to_llm_config[agent_name.strip()] = llm_config
        except Exception:
            _tui_logger.debug(
                'Failed to update controller agent_to_llm_config after model switch',
                exc_info=True,
            )
        self._pending_llm_config_apply = False
        return 'applied to active session'

    def _refresh_prompt_managers_after_llm_switch(
        self, agent: Any, registry: Any
    ) -> None:
        prompt_managers = []
        for attr in ('_prompt_manager', 'prompt_manager'):
            try:
                value = getattr(agent, attr, None)
            except Exception:
                value = None
            if value is not None and value not in prompt_managers:
                prompt_managers.append(value)
        memory_manager = getattr(agent, 'memory_manager', None)
        conversation_memory = getattr(memory_manager, 'conversation_memory', None)
        prompt_manager = getattr(conversation_memory, 'prompt_manager', None)
        if prompt_manager is not None and prompt_manager not in prompt_managers:
            prompt_managers.append(prompt_manager)

        for prompt_manager in prompt_managers:
            for attr, value in (
                ('_app_config', getattr(registry, 'config', None)),
                ('app_config', getattr(registry, 'config', None)),
                ('_config', getattr(agent, 'config', None)),
                ('config', getattr(agent, 'config', None)),
            ):
                if value is None:
                    continue
                try:
                    setattr(prompt_manager, attr, value)
                except Exception:
                    pass

    def _toggle_autonomy_tabs_visibility(self, mode: str) -> None:
        mode = normalize_interaction_mode(mode)
        try:
            autonomy_tabs = self.query_one('#hud-autonomy')
            autonomy_tabs.display = mode == AGENT_MODE
            self.query_one('#hud-label-autonomy').display = mode == AGENT_MODE
        except Exception:
            pass

    def on_sidebar_row_selected(self, event: Any) -> None:
        """Handle SidebarRow selected events and notify the user."""
        if not isinstance(event, SidebarRow.Selected):
            return
        item_id = event.item_id
        if not item_id:
            return
        if item_id.startswith('task:'):
            task_id = item_id.split(':', 1)[1]
            desc = 'Unknown task'
            tasks = task_panel_signature(
                self._renderer._task_list if self._renderer else []
            )
            for tid, _status, description in tasks:
                if tid == task_id:
                    desc = description or desc
                    break
            try:
                from backend.cli.tui.widgets.collapsible import CollapsibleSection

                section = self.query_one('#sidebar-tasks', CollapsibleSection)
                section.expand()
            except Exception:
                pass
            try:
                display = self._get_display()
                display.force_scroll_end()
            except Exception:
                pass
            self.notify(
                f'Following live activity · {desc}',
                severity='info',
                timeout=2.5,
            )
        elif item_id.startswith('mcp:'):
            mcp_name = item_id.split(':', 1)[1]
            self.notify(
                f'MCP Server: {mcp_name}  |  Press Delete to remove',
                severity='info',
                timeout=3.0,
            )
        elif item_id.startswith('skill:'):
            skill_name = item_id.split(':', 1)[1]
            self.notify(
                f'Playbook Skill: {skill_name}.md  |  Press Delete to remove',
                severity='info',
                timeout=3.0,
            )

    async def on_sidebar_row_delete_requested(self, event: Any) -> None:
        """Handle SidebarRow delete events."""
        if not isinstance(event, SidebarRow.DeleteRequested) or not event.item_id:
            return
        item_id = event.item_id
        if item_id.startswith('skill:'):
            skill_name = item_id[6:]
            self.run_worker(self._confirm_delete_skill(skill_name), exclusive=True)
        elif item_id.startswith('mcp:'):
            mcp_name = item_id.split(':', 1)[1]
            self.run_worker(self._confirm_delete_mcp(mcp_name), exclusive=True)

    async def _confirm_delete_skill(self, skill_name: str) -> None:
        result = await self.app.push_screen_wait(
            GrintaConfirmDialog(
                title='Delete Skill',
                body=f'Are you sure you want to delete {skill_name}.md?',
                options=[('cancel', 'Cancel'), ('delete', 'Delete')],
            )
        )
        if result == 'delete':
            self._delete_skill(skill_name)

    async def _confirm_delete_mcp(self, mcp_name: str) -> None:
        result = await self.app.push_screen_wait(
            GrintaConfirmDialog(
                title='Delete MCP Server',
                body=f"Are you sure you want to remove the server '{mcp_name}'?",
                options=[('cancel', 'Cancel'), ('delete', 'Remove')],
            )
        )
        if result == 'delete':
            self._delete_mcp_server(mcp_name)

    def _delete_skill(self, name: str) -> None:
        if not name.endswith('.md'):
            name += '.md'
        skill_path = Path.home() / '.grinta' / 'skills' / name
        try:
            if skill_path.exists():
                skill_path.unlink()
                self.notify(f'Skill deleted: {name}', severity='information')
                self._last_sidebar_state = None
            else:
                self.notify(f'Skill not found: {name}', severity='warning')
        except Exception as e:
            self.notify(f'Failed to delete skill: {e}', severity='error')

    def _delete_mcp_server(self, name: str) -> None:
        from backend.integrations.mcp.native_backends import is_user_visible_mcp_server

        if not is_user_visible_mcp_server(name):
            self.notify(
                f"'{name}' is a bundled internal backend and cannot be removed.",
                severity='warning',
            )
            return
        from backend.cli.settings import remove_mcp_server

        try:
            remove_mcp_server(name)
            self.notify(f'MCP Server removed: {name}', severity='information')
            self._last_sidebar_state = None
        except Exception as e:
            self.notify(f'Failed to remove MCP server: {e}', severity='error')

    @work
    async def on_collapsible_section_action_clicked(self, event: Any) -> None:
        """Handle [+] Add clicks on sidebar sections."""
        if not event.control:
            return

        if event.control.id == 'sidebar-skills':
            result = await self.app.push_screen_wait(GrintaAddSkillDialog())
            if result:
                self._create_skill(result['name'], result['content'])
        elif event.control.id == 'sidebar-mcp':
            result = await self.app.push_screen_wait(GrintaAddMCPDialog())
            if result:
                self._add_mcp_server(result['name'], result['command'])

    def _create_skill(self, name: str, content: str) -> None:
        skills_dir = Path.home() / '.grinta' / 'skills'
        skills_dir.mkdir(parents=True, exist_ok=True)
        if not name.endswith('.md'):
            name += '.md'
        skill_path = skills_dir / name
        try:
            skill_path.write_text(content, encoding='utf-8')
            self.notify(f'Skill created: {name}', severity='information')
            self._last_sidebar_state = None  # Force full refresh next tick
        except Exception as e:
            self.notify(f'Failed to create skill: {e}', severity='error')

    def _add_mcp_server(self, name: str, command: str) -> None:
        from backend.cli.settings import add_mcp_server

        try:
            add_mcp_server(name, command=command)
            self.notify(f'MCP Server added: {name}', severity='information')
            self._last_sidebar_state = None  # Force full refresh next tick
        except Exception as e:
            self.notify(f'Failed to add MCP server: {e}', severity='error')
