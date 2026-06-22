from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from textual import events, work

from backend.cli.event_rendering.panels import task_panel_signature
from backend.cli.tui.constants import _tui_logger
from backend.cli.tui.dialogs import (  # noqa: F401
    ConfirmWidget,
    GrintaAddMCPDialog,
    GrintaAddSkillDialog,
    GrintaConfirmDialog,
)
from backend.cli.tui.widgets.collapsible import CollapsibleSection, SidebarRow
from backend.cli.tui.widgets.small import (
    InputBar,
)
from backend.core.interaction_modes import (
    AGENT_MODE,
    VISIBLE_INTERACTION_MODES,
    is_chat_mode,
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

    def _highlight_sidebar_item(self, section_id: str, item_id: str) -> None:
        try:
            section = self.query_one(section_id, CollapsibleSection)
            for row in section.query('.sidebar-item-row'):
                if getattr(row, 'item_id', None) == item_id:
                    row.add_class('-highlight')
                    self.set_timer(2.0, lambda r=row: r.remove_class('-highlight'))
                    break
        except Exception:
            pass

    def _existing_mcp_server_names(self) -> set[str]:
        from backend.cli.settings import get_mcp_servers

        return {str(s.get('name') or '') for s in get_mcp_servers(self._config)}

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
        from backend.cli.settings import (
            get_persisted_autonomy_level,
            update_autonomy_level,
        )

        agent_name = self._active_agent_name()
        previous = self._runtime_autonomy_level()
        if (
            previous == level
            and self._hud.state.autonomy_level == level
            and level == get_persisted_autonomy_level(agent_name)
        ):
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
            update_autonomy_level(level, agent_name)
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
            self.run_worker(self._open_mcp_editor(mcp_name), exclusive=True)
        elif item_id.startswith('skill:'):
            skill_name = item_id.split(':', 1)[1]
            self.run_worker(self._open_skill_editor(skill_name), exclusive=True)

    def on_sidebar_row_toggle_requested(self, event: Any) -> None:
        if not isinstance(event, SidebarRow.ToggleRequested) or not event.item_id:
            return
        if event.item_id.startswith('mcp:'):
            mcp_name = event.item_id.split(':', 1)[1]
            self.run_worker(self._toggle_mcp_server(mcp_name), exclusive=True)

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
        self._config = load_app_config()
        self._reload_mcp_config_and_refresh_sidebar()
        state = 'enabled' if enabled else 'disabled'
        self.notify(f'MCP {name}: {state}', severity='information', timeout=2.0)

    async def _open_mcp_editor(self, name: str) -> None:
        from backend.cli.settings import (
            get_mcp_server,
            mcp_server_endpoint,
            update_mcp_server,
        )
        from backend.core.config import load_app_config

        self._config = load_app_config()
        server = get_mcp_server(self._config, name)
        if server is None:
            self.notify(
                f'MCP server not found: {name}', severity='warning', timeout=2.5
            )
            return
        result = await self.app.push_screen_wait(
            GrintaAddMCPDialog(
                existing_names=self._existing_mcp_server_names(),
                edit_name=name,
                edit_command=mcp_server_endpoint(server),
            )
        )
        if not result:
            return
        try:
            update_mcp_server(
                name,
                command=result['command'],
                config=self._config,
            )
        except Exception as exc:
            self.notify(
                f'Failed to update MCP server: {exc}',
                severity='error',
                timeout=3.0,
            )
            return
        self._reload_mcp_config_and_refresh_sidebar()
        self.notify(f'MCP server updated: {name}', severity='information', timeout=2.0)

    async def _open_skill_editor(self, name: str) -> None:
        from backend.cli.event_rendering.sidebar import is_user_skill

        stem = name.removesuffix('.md')
        skill_path = Path.home() / '.grinta' / 'skills' / f'{stem}.md'
        read_only = not is_user_skill(stem)
        content = ''
        if read_only:
            import backend

            playbook_path = (
                Path(backend.__file__).resolve().parent  # noqa: ASYNC240
                / 'playbooks'
                / f'{stem}.md'
            )
            try:
                content = playbook_path.read_text(encoding='utf-8')
            except OSError:
                self.notify(
                    f'Built-in playbook not found: {stem}.md',
                    severity='warning',
                    timeout=2.5,
                )
                return
        else:
            try:
                content = skill_path.read_text(encoding='utf-8')
            except OSError:
                self.notify(
                    f'Custom skill not found: {stem}.md',
                    severity='warning',
                    timeout=2.5,
                )
                return

        result = await self.app.push_screen_wait(
            GrintaAddSkillDialog(
                edit_name=stem,
                edit_content=content,
                read_only=read_only,
            )
        )
        if not result or read_only:
            return
        await self._save_skill_content(stem, result['content'])

    async def _save_skill_content(self, name: str, content: str) -> None:
        import asyncio

        await asyncio.to_thread(self._save_skill_content_sync, name, content)
        self._refresh_sidebar()
        self.notify(f'Skill updated: {name}.md', severity='information', timeout=2.0)

    def _save_skill_content_sync(self, name: str, content: str) -> None:
        skills_dir = Path.home() / '.grinta' / 'skills'
        skills_dir.mkdir(parents=True, exist_ok=True)
        stem = name.removesuffix('.md')
        skill_path = skills_dir / f'{stem}.md'
        skill_path.write_text(content, encoding='utf-8')

    async def _confirm_delete_skill(self, skill_name: str) -> None:
        from backend.cli.event_rendering.sidebar import is_user_skill

        if not is_user_skill(skill_name):
            self.notify(
                f'Built-in playbook {skill_name}.md cannot be removed.',
                severity='warning',
                timeout=2.5,
            )
            return

        widget = self.query_one('#confirm-widget', ConfirmWidget)
        widget.configure_prompt(
            f'Remove custom skill [white]{skill_name}.md[/]?',
            [('cancel', 'Cancel'), ('delete', 'Remove')],
            recommended=1,
        )
        widget.show()
        try:
            result = await widget.wait_for_decision()
        finally:
            widget.hide()
        if result == 'delete':
            await self._delete_skill(skill_name)

    async def _confirm_delete_mcp(self, mcp_name: str) -> None:
        result = await self.app.push_screen_wait(
            GrintaConfirmDialog(
                title='Delete MCP Server',
                body=f"Are you sure you want to remove the server '{mcp_name}'?",
                options=[('cancel', 'Cancel'), ('delete', 'Remove')],
            )
        )
        if result == 'delete':
            await self._delete_mcp_server(mcp_name)

    def _delete_skill_sync(self, name: str) -> None:
        """Synchronous skill deletion - used internally by _delete_skill()."""
        if not name.endswith('.md'):
            name += '.md'
        skill_path = Path.home() / '.grinta' / 'skills' / name
        try:
            if skill_path.exists():
                skill_path.unlink()
                self.notify(f'Skill deleted: {name}', severity='information')
            else:
                self.notify(f'Skill not found: {name}', severity='warning')
        except Exception as e:
            self.notify(f'Failed to delete skill: {e}', severity='error')

    async def _delete_skill(self, name: str) -> None:
        """Delete a skill file, offloaded to a thread pool."""
        import asyncio

        await asyncio.to_thread(self._delete_skill_sync, name)
        self._refresh_sidebar()

    def _delete_mcp_server_sync(self, name: str) -> None:
        """Synchronous MCP server deletion - used internally by _delete_mcp_server()."""
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
        except Exception as e:
            self.notify(f'Failed to remove MCP server: {e}', severity='error')

    async def _delete_mcp_server(self, name: str) -> None:
        """Delete an MCP server, offloaded to a thread pool."""
        import asyncio

        await asyncio.to_thread(self._delete_mcp_server_sync, name)
        self._reload_mcp_config_and_refresh_sidebar()

    @work
    async def on_collapsible_section_action_clicked(self, event: Any) -> None:
        """Handle [+] Add clicks on sidebar sections."""
        if not event.control:
            return

        if event.control.id == 'sidebar-skills':
            result = await self.app.push_screen_wait(GrintaAddSkillDialog())
            if result:
                await self._create_skill(result['name'], result['content'])
                self._highlight_sidebar_item(
                    '#sidebar-skills', f'skill:{result["name"]}'
                )
                self.notify(
                    f'Added skill {result["name"]}.md · Enter edit · Del remove',
                    severity='information',
                    timeout=3.0,
                )
        elif event.control.id == 'sidebar-mcp':
            result = await self.app.push_screen_wait(
                GrintaAddMCPDialog(existing_names=self._existing_mcp_server_names())
            )
            if result:
                await self._add_mcp_server(result['name'], result['command'])
                self._highlight_sidebar_item('#sidebar-mcp', f'mcp:{result["name"]}')
                self.notify(
                    f'Added MCP {result["name"]} · Enter edit · Del remove',
                    severity='information',
                    timeout=3.0,
                )

    def _create_skill_sync(self, name: str, content: str) -> None:
        """Synchronous skill creation - used internally by _create_skill()."""
        skills_dir = Path.home() / '.grinta' / 'skills'
        skills_dir.mkdir(parents=True, exist_ok=True)
        if not name.endswith('.md'):
            name += '.md'
        skill_path = skills_dir / name
        try:
            skill_path.write_text(content, encoding='utf-8')
            self.notify(f'Skill created: {name}', severity='information')
        except Exception as e:
            self.notify(f'Failed to create skill: {e}', severity='error')

    async def _create_skill(self, name: str, content: str) -> None:
        """Create a skill file, offloaded to a thread pool."""
        import asyncio

        await asyncio.to_thread(self._create_skill_sync, name, content)
        self._refresh_sidebar()

    def _add_mcp_server_sync(self, name: str, command: str) -> None:
        """Synchronous MCP server addition - used internally by _add_mcp_server()."""
        from backend.cli.settings import add_mcp_server

        try:
            add_mcp_server(name, command=command)
            self.notify(f'MCP Server added: {name}', severity='information')
        except Exception as e:
            self.notify(f'Failed to add MCP server: {e}', severity='error')

    async def _add_mcp_server(self, name: str, command: str) -> None:
        """Add an MCP server, offloaded to a thread pool."""
        import asyncio

        await asyncio.to_thread(self._add_mcp_server_sync, name, command)
        self._reload_mcp_config_and_refresh_sidebar()
