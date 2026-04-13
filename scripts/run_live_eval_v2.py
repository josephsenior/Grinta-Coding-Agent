import asyncio
import json
import subprocess
import sys
import time

import psutil
import requests
import socketio

with open('live_eval_log.txt', 'w', encoding='utf-8') as clog:
    def log_print(msg):
        print(msg)
        clog.write(msg + '\n')
        clog.flush()

    try:
        # 1. Kill old servers
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmdline = ' '.join(proc.info['cmdline'] or []).lower()
                if 'uvicorn' in cmdline or 'start_server.py' in cmdline or 'app.py' in cmdline:
                    if sys.executable.lower() in cmdline or 'python' in cmdline:
                        log_print(f'Killing old server process {proc.pid}')
                        proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass

        time.sleep(2)

        log_print('Starting fresh live server...')
        with open('server_stdout.log', 'w') as s_out:
            server_proc = subprocess.Popen([sys.executable, 'start_server.py'], stdout=s_out, stderr=s_out)

        log_print('Waiting for server to become healthy...')
        server_up = False
        for i in range(30):
            try:
                r = requests.get('http://127.0.0.1:3000/api/v1/health', timeout=2)
                if r.status_code == 200:
                    server_up = True
                    break
            except Exception:
                pass
            time.sleep(2)
            log_print(f'Waiting for health... {i}/30')

        if not server_up:
            log_print('FAILED TO START SERVER')
            server_proc.kill()
            sys.exit(1)

        log_print('Server is UP! Running test scenario...')

        async def run_scenario():
            sio = socketio.AsyncClient()

            log_print('Creating conversation HTTP POST...')
            res = requests.post('http://127.0.0.1:3000/api/v1/conversations', json={}, timeout=60)  # noqa: ASYNC210
            res.raise_for_status()
            conv = res.json()
            sid = conv['conversation_id']
            log_print(f'Conversation defined: {sid}')

            @sio.event
            async def connect():
                log_print('WS Connected!')

            @sio.event
            async def disconnect():
                log_print('WS Disconnected!')

            @sio.on('app_event')
            async def on_app_event(data):
                if 'action' in data and data['action'] == 'working_memory':
                    log_print('\n----- MEMORY SCRATCHPAD UPDATE -----')
                    log_print(json.dumps(data.get('args', {}), indent=2))
                    log_print('------------------------------------')

                if data.get('type') == 'observation' and 'output' in data:
                    out_text = str(data['output'])[:100].replace('\n', ' ')
                    log_print(f'> Tool Output: {out_text}...')

                if data.get('state') == 'awaiting_user_input':
                    log_print('Agent has finished execution.')
                    await sio.disconnect()

            log_print('Connecting WS...')
            await sio.connect(f'http://127.0.0.1:3000?conversation_id={sid}&latest_event_id=-1')

            await asyncio.sleep(1)

            msg = "Create a Python script in a folder named `real_world_task` containing a script `app.py` that starts a tiny FastAPI server on port 8080 returning {'message': 'Hello World'}. Also write a `requirements.txt` for it in that folder. Use tool calls to write the files."
            log_print(f'Sending prompt... {msg}')
            await sio.emit('app_user_action', {
                'action': 'message',
                'args': {'content': msg, 'image_urls': [], 'file_urls': []}
            })

            log_print('Waiting for agent to finish...')
            try:
                await asyncio.wait_for(sio.wait(), timeout=180)
            except asyncio.TimeoutError:
                log_print('Timed out waiting for agent completion!')
                await sio.disconnect()

        asyncio.run(run_scenario())
        log_print('Scenario done. Shutting down live server...')
    except Exception as e:
        log_print(f'FATAL ERROR: {str(e)}')
    finally:
        if 'server_proc' in locals():
            server_proc.terminate()
            try:
                server_proc.wait(timeout=5)
            except:  # noqa: E722
                server_proc.kill()
        log_print('Done!')
