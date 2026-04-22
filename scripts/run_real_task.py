import asyncio
import json
import time

import requests
import socketio

sio = socketio.AsyncClient()
sid = None
output_file = open('real_task_output.txt', 'w', encoding='utf-8')


def log(msg):
    print(msg)
    output_file.write(msg + '\n')
    output_file.flush()


@sio.event
async def connect():
    log('Connected to backend')


@sio.event
async def disconnect():
    log('Disconnected from backend')


@sio.on('app_event')
async def on_app_event(data):
    log(f'Event JSON: {json.dumps(data)}')
    data.get('type')
    data.get('action')
    if data.get('state') == 'awaiting_user_input':
        log('Agent finished thinking!')
        asyncio.create_task(shutdown_sio())


async def shutdown_sio():
    await asyncio.sleep(0.5)
    await sio.disconnect()


async def main():
    global sid
    log('Creating conversation...')
    for i in range(20):
        try:
            res = requests.post(  # noqa: ASYNC210
                'http://127.0.0.1:3202/api/v1/conversations', json={}, timeout=30
            )
            res.raise_for_status()
            break
        except Exception as e:
            log(f'Waiting for backend... ({i + 1}/20) - {e}')
            time.sleep(2)  # noqa: ASYNC251
    else:
        log('Backend never became available')
        return

    conv = res.json()
    sid = conv['conversation_id']
    log(f'Conversation created with ID: {sid}')

    log('Connecting to ws...')
    await sio.connect(f'http://127.0.0.1:3202?conversation_id={sid}&latest_event_id=-1')

    log('Waiting 2 seconds...')
    await asyncio.sleep(2)

    msg = "Create a python script in a folder named `real_world_task` containing a script `app.py` that starts a tiny FastAPI server on port 8080 returning {'message': 'Hello World'}. Also write a `requirements.txt` for it in that folder. Use tool calls to write the files."
    log(f'Sending app_user_action: {msg}')
    await sio.emit(
        'app_user_action',
        {
            'action': 'message',
            'args': {'content': msg, 'image_urls': [], 'file_urls': []},
        },
    )

    try:
        await asyncio.wait_for(sio.wait(), timeout=300)
    except (TimeoutError, asyncio.TimeoutError):
        log('Timed out waiting for response!')
        await sio.disconnect()


if __name__ == '__main__':
    asyncio.run(main())
    output_file.close()
