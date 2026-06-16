"""Optional LLM connection validation during first-run setup."""

from __future__ import annotations

import asyncio

from rich.console import Console
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text

from backend.cli.theme import CLR_META, CLR_SPINNER, CLR_STATUS_OK, CLR_STATUS_WARN


def validate_connection(
    console: Console,
    model: str,
    api_key: str,
    base_url: str | None,
) -> None:
    """Test the LLM connection with a minimal request. Non-fatal on failure."""
    if not api_key:
        return

    spinner = Spinner('dots', text='  Validating connection…', style=CLR_SPINNER)
    try:
        with Live(spinner, console=console, transient=True):

            async def _run_with_timeout_update() -> bool | str:
                async def _update_spinner_text() -> None:
                    await asyncio.sleep(5)
                    spinner.text = Text(
                        '  Still waiting on provider... (this might take up to 15s)',
                        style=CLR_SPINNER,
                    )

                update_task = asyncio.create_task(_update_spinner_text())
                try:
                    return await _test_llm_call(model, api_key, base_url)
                finally:
                    update_task.cancel()

            result = asyncio.run(_run_with_timeout_update())

        if result is True:
            console.print(f'  [{CLR_STATUS_OK}]✓[/] Connection verified')
        elif isinstance(result, str):
            console.print(f'  [{CLR_STATUS_WARN}]⚠[/] [{CLR_META}]{result}[/]')
            console.print(
                f'  [{CLR_META}]Settings saved anyway — you can fix this in /settings[/]'
            )
    except Exception:
        console.print(
            '  [dim]⚠ Could not verify (will try when you send a message)[/dim]'
        )


async def _test_llm_call(model: str, api_key: str, base_url: str | None) -> bool | str:
    """Make a minimal LLM call to verify credentials. Returns True or error string."""
    try:
        from backend.inference.direct_clients import get_direct_client
        from backend.inference.exceptions import (
            APIConnectionError,
            AuthenticationError,
            BadRequestError,
            NotFoundError,
            RateLimitError,
            Timeout,
        )

        client = get_direct_client(
            model=model,
            api_key=api_key or 'not-needed',
            base_url=base_url,
            timeout=15.0,
        )
        await client.acompletion(
            messages=[{'role': 'user', 'content': 'Say "ok" and nothing else.'}],
            model=model,
            max_tokens=5,
            temperature=0,
        )
        return True
    except Timeout:
        return 'Connection timed out — check your network'
    except APIConnectionError:
        return 'Could not connect — check the base URL'
    except AuthenticationError:
        return 'Invalid API key'
    except NotFoundError:
        return f'Model not found: {_strip_provider_prefix(model)}'
    except RateLimitError:
        return 'Rate limited — but credentials look valid'
    except BadRequestError as e:
        return f'Request rejected: {e.message}'
    except Exception as e:
        return f'Connection error: {type(e).__name__}'


def _strip_provider_prefix(model: str) -> str:
    if '/' not in model:
        return model
    parts = model.split('/', 1)
    if parts[0] in (
        'openai',
        'anthropic',
        'google',
        'groq',
        'xai',
        'deepseek',
        'opencode',
        'opencode-go',
        'vercel',
    ):
        return parts[1]
    return model
