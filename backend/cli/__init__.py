"""Grinta CLI — Zero-Config terminal frontend for the agent engine.

Rendering architecture (for contributors)
-----------------------------------------
* **Event path:** the ledger delivers events on a background thread; :class:`~backend.cli.event_renderer.CLIEventRenderer` only mutates the Rich ``Live`` and ``console`` from the asyncio main loop via ``drain_events()`` (see ``_on_event_threadsafe``). Do not print to the console from stream callbacks.
* **Live vs input:** while the user is at the ``prompt_toolkit`` prompt, committed transcript lines go through ``run_in_terminal`` so they appear above the multiline input. Status chrome is built from :mod:`backend.cli.status_chrome` so the bottom toolbar and the agent-turn “fake” footer stay aligned.
* **Theming:** Rich and prompt_toolkit colors live in :mod:`backend.cli.theme` (``prompt_toolkit_style_dict`` for PT, ``no_color_enabled`` for both).
"""
