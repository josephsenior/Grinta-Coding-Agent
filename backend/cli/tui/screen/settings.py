from __future__ import annotations

import copy
from typing import Any

from textual import events, work

from backend.cli.event_rendering.panels import task_panel_signature
from backend.cli.tui.constants import _tui_logger
from backend.cli.tui.dialogs import (  # noqa: F401
    GrintaManageMCPDialog,
    GrintaManageSkillsDialog,
)
from backend.cli.tui.widgets.collapsible import CollapsibleSection, SidebarRow
from backend.cli.tui.widgets.small import (
    InputBar,
)
from backend.core.interaction_modes import (
    AGENT_MODE,
    VISIBLE_INTERACTION_MODES,
    normalize_interaction_mode,
)


class ScreenSettingsMixin:
    """Settings-related methods of GrintaScreen."""

    def _refresh_sidebar(self) -> None:
        renderer = self._renderer
        if renderer is None:
            return
        renderer.invalidate_sidebar()
        renderer._refresh_display()

    def _reload_mcp_config_and_refresh_sidebar(self) -> None:
        from backend.core.config import load_app_config
        from backend.integrations.mcp.native_backends import (
            count_user_visible_mcp_servers,
        )

        self._config = load_app_config()
        self._hud.update_mcp_servers(count_user_visible_mcp_servers(self._config))
        self._render_hud_bar()
        self._refresh_sidebar()

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
        if getattr(self, '_hud_autonomy_syncing', False):
            return
        level = self._visible_autonomy_level(new_level)
        if level not in {'conservative', 'balanced', 'full'}:
            return
        from backend.cli.settings import (
            get_persisted_autonomy_level,
            update_autonomy_level,
        )

        agent_name = self._active_agent_name()
        persisted = get_persisted_autonomy_level(agent_name)
        runtime = self._runtime_autonomy_level()
        if (
            runtime == level
            and self._hud.state.autonomy_level == level
            and level == persisted
        ):
            return
        if level != persisted:
            update_autonomy_level(level, agent_name)
        agent_config = self._active_agent_config()
        if agent_config is not None:
            try:
                agent_config.autonomy_level = level
            except Exception:
                pass
        controller = self._controller
        if controller is not None:
            ac = getattr(controller, 'autonomy_controller', None)
            if ac is not None:
                ac.autonomy_level = level
            from backend.cli.settings.mode_runtime import apply_autonomy_to_controller

            apply_autonomy_to_controller(controller)
        try:
            setattr(self._config, 'autonomy_level', level)
        except Exception:
            pass
        self._hud.update_autonomy(level)
        self._render_hud_bar()
        try:
            from backend.core.logging.session_event_logger import (
                emit_session_context_if_changed,
            )

            emit_session_context_if_changed()
        except Exception:
            pass
        if runtime != level or persisted != level:
            from backend.core.autonomy import autonomy_runtime_notice

            self.notify(
                autonomy_runtime_notice(level),
                severity='information',
                timeout=3.0,
            )
            renderer = self._renderer
            if renderer is not None and hasattr(renderer, 'add_system_message'):
                renderer.add_system_message(
                    autonomy_runtime_notice(level), title='autonomy'
                )

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
        try:
            from backend.core.logging.session_event_logger import (
                emit_session_context_if_changed,
            )

            emit_session_context_if_changed()
        except Exception:
            pass
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
        from backend.cli.settings.mode_runtime import (
            apply_interaction_mode_to_controller,
        )

        apply_interaction_mode_to_controller(controller, mode)

    def _update_mode_extra_data(self, controller, mode: str) -> None:
        from backend.cli.settings.mode_runtime import sync_active_run_mode_extra_data

        sync_active_run_mode_extra_data(controller, mode)

    def _apply_mode(self, new_mode: str) -> None:
        mode = normalize_interaction_mode(new_mode, default='')
        if mode not in set(VISIBLE_INTERACTION_MODES):
            return
        from backend.cli.settings import (
            get_persisted_interaction_mode,
            update_interaction_mode,
        )

        agent_name = self._active_agent_name()
        persisted = get_persisted_interaction_mode(agent_name)
        previous = self._active_interaction_mode()
        if previous == mode and mode == persisted:
            return
        if mode != persisted:
            update_interaction_mode(mode, agent_name)
        self._propagate_mode_to_agent(mode)
        self._render_hud_bar()
        self._update_input_identity(mode)
        self._toggle_autonomy_tabs_visibility(mode)
        self._hud.update_interaction_mode(mode)
        if previous != mode or mode != persisted:
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

    def on_sidebar_row_toggle_requested(self, event: Any) -> None:
        if not isinstance(event, SidebarRow.ToggleRequested) or not event.item_id:
            return
        if event.item_id.startswith('mcp:'):
            mcp_name = event.item_id.split(':', 1)[1]
            self.run_worker(self._toggle_mcp_server(mcp_name), exclusive=True)

    def on_collapsible_section_feature_toggle_changed(self, event: Any) -> None:
        if not isinstance(event, CollapsibleSection.FeatureToggleChanged):
            return
        section_id = getattr(event.control, 'id', None)
        enabled = bool(event.enabled)
        if section_id == 'sidebar-mcp':
            self.run_worker(self._toggle_mcp_master(enabled), exclusive=True)
        elif section_id == 'sidebar-lsp':
            self.run_worker(self._toggle_lsp_query(enabled), exclusive=True)
        elif section_id == 'sidebar-dap':
            self.run_worker(self._toggle_debugger(enabled), exclusive=True)

    async def _toggle_mcp_master(self, enabled: bool) -> None:
        from backend.cli.settings.mcp import set_mcp_master_enabled
        from backend.core.config import load_app_config

        try:
            set_mcp_master_enabled(enabled)
        except Exception as exc:
            self.notify(
                f'Failed to update MCP: {exc}',
                severity='error',
                timeout=3.0,
            )
            self._refresh_sidebar()
            return
        self._config = load_app_config()
        self._reload_mcp_config_and_refresh_sidebar()
        state = 'enabled' if enabled else 'disabled'
        self.notify(f'MCP: {state}', severity='information', timeout=2.0)

    async def _toggle_lsp_query(self, enabled: bool) -> None:
        from backend.cli.settings import update_enable_lsp_query
        from backend.cli.settings.mode_runtime import (
            apply_agent_tool_flags_to_controller,
        )
        from backend.core.config import load_app_config

        agent_name = self._active_agent_name()
        try:
            update_enable_lsp_query(enabled, agent_name)
        except Exception as exc:
            self.notify(
                f'Failed to update LSP: {exc}',
                severity='error',
                timeout=3.0,
            )
            self._refresh_sidebar()
            return
        self._config = load_app_config()
        agent_config = self._active_agent_config()
        if agent_config is not None:
            agent_config.enable_lsp_query = enabled
        controller = self._controller
        if controller is not None:
            apply_agent_tool_flags_to_controller(
                controller,
                enable_lsp_query=enabled,
            )
        renderer = self._renderer
        if renderer is not None:
            renderer._last_lsp_sidebar_signature = None
            if enabled:
                renderer._lsp_detection_scheduled = False
                renderer.schedule_lsp_detection()
        self._refresh_sidebar()
        state = 'enabled' if enabled else 'disabled'
        self.notify(f'LSP: {state}', severity='information', timeout=2.0)

    async def _toggle_debugger(self, enabled: bool) -> None:
        from backend.cli.settings import update_enable_debugger
        from backend.cli.settings.mode_runtime import (
            apply_agent_tool_flags_to_controller,
        )
        from backend.core.config import load_app_config

        agent_name = self._active_agent_name()
        try:
            update_enable_debugger(enabled, agent_name)
        except Exception as exc:
            self.notify(
                f'Failed to update debugger: {exc}',
                severity='error',
                timeout=3.0,
            )
            self._refresh_sidebar()
            return
        self._config = load_app_config()
        agent_config = self._active_agent_config()
        if agent_config is not None:
            agent_config.enable_debugger = enabled
        controller = self._controller
        if controller is not None:
            apply_agent_tool_flags_to_controller(
                controller,
                enable_debugger=enabled,
            )
        renderer = self._renderer
        if renderer is not None:
            renderer._last_dap_sidebar_signature = None
            if enabled:
                renderer._lsp_detection_scheduled = False
                renderer.schedule_lsp_detection()
        self._refresh_sidebar()
        state = 'enabled' if enabled else 'disabled'
        self.notify(f'Debugger: {state}', severity='information', timeout=2.0)

    async def _toggle_mcp_server(self, name: str) -> None:
        from backend.cli.settings import get_mcp_server, set_mcp_server_enabled
        from backend.core.config import load_app_config

        self._config = load_app_config()
        server = get_mcp_server(self._config, name)
        if server is None:
            self.notify(
                f'MCP server not found: {name}', severity='warning', timeout=2.5
            )
            return
        enabled = not bool(server.get('enabled', True))
        try:
            set_mcp_server_enabled(name, enabled, config=self._config)
        except Exception as exc:
            self.notify(
                f'Failed to update MCP server: {exc}',
                severity='error',
                timeout=3.0,
            )
            return
        # ``set_mcp_server_enabled`` writes settings.json; that triggers
        # the bus → adapter chain (see ``lifecycle_bootstrap``) which
        # re-runs ``add_mcp_tools_to_agent`` and reconnects clients.
        # We only need to refresh the local sidebar / HUD state.
        self._config = load_app_config()
        self._reload_mcp_config_and_refresh_sidebar()
        state = 'enabled' if enabled else 'disabled'
        self.notify(f'MCP {name}: {state}', severity='information', timeout=2.0)

    @work
    async def on_collapsible_section_action_clicked(self, event: Any) -> None:
        """Open manage dialogs from sidebar section headers."""
        if not event.control:
            return

        from backend.core.config import load_app_config

        if event.control.id == 'sidebar-skills':
            changed = await self.app.push_screen_wait(GrintaManageSkillsDialog())
            if changed:
                self._refresh_sidebar()
                self.notify('Skills updated', severity='information', timeout=2.0)
        elif event.control.id == 'sidebar-mcp':
            self._config = load_app_config()
            changed = await self.app.push_screen_wait(
                GrintaManageMCPDialog(self._config)
            )
            if changed:
                self._reload_mcp_config_and_refresh_sidebar()
                self.notify('MCP servers updated', severity='information', timeout=2.0)
