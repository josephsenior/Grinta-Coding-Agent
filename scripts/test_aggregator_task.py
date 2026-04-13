import asyncio
import json
import time

import requests
import socketio

sio = socketio.AsyncClient()
sid = None
output_file = open('complex_task_output.txt', 'w', encoding='utf-8')

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
            res = requests.post('http://127.0.0.1:3000/api/v1/conversations', json={}, timeout=30)  # noqa: ASYNC210
            res.raise_for_status()
            break
        except Exception as e:
            log(f'Waiting for backend... ({i+1}/20) - {e}')
            time.sleep(2)  # noqa: ASYNC251
    else:
        log('Backend never became available')
        return

    conv = res.json()
    sid = conv['conversation_id']
    log(f'Conversation created with ID: {sid}')

    log('Connecting to ws...')
    await sio.connect(f'http://127.0.0.1:3000?conversation_id={sid}&latest_event_id=-1')
    log('Waiting 2 seconds...')
    await asyncio.sleep(2)

    msg = """Goal: I need you to design and implement a standalone "Local Metrics Aggregator and Alerting Engine" from scratch in this workspace.

Business Requirements:
1. The system must run a continuous background worker that monitors a specific local directory (e.g., `./ingest`) for incoming `.json` metric files dropped by hypothetical external services.
2. As new files arrive, it must parse them, aggregate the data internally, and flush the aggregated records to a local SQLite database in batches (either every 5 seconds, or when 50 metrics are queued).
3. It needs an alerting mechanism: if a specific metric (like "cpu_usage" or "error_rate") exceeds a threshold defined in a configuration file (which you must design), it should append a formatted warning into an `alerts.log` file.
4. You must also write a separate "mock generator" script that randomly dumps fake `.json` metric files into the ingest folder to continuously test the system.

Constraints & Complexity:
- I am not providing the folder structure, the specific JSON schemas, or the database implementation details. You have to design the data models and configuration format yourself.
- Fault tolerance is critical: If a malformed or corrupted JSON file is dropped into the folder, the engine must quarantine the bad file into a `./dead_letter` folder and continue processing. It cannot crash.
- Decide on the best approach for file watching, concurrency, and database locking.

Instructions:
Do NOT start writing code immediately. Use your think and task tracking tools to break down this entire project into a comprehensive, multi-step plan. Define your proposed architecture, state management, and error handling strategy, then execute the steps sequentially."""

    log(f'Sending app_user_action: {msg[:100]}...')
    await sio.emit('app_user_action', {
        'action': 'message',
        'args': {
            'content': msg,
            'image_urls': [],
            'file_urls': []
        }
    })

    try:
        await asyncio.wait_for(sio.wait(), timeout=600)  # Extended timeout for complex task
    except (TimeoutError, asyncio.TimeoutError):
        log('Timed out waiting for response!')
        await sio.disconnect()

if __name__ == '__main__':
    asyncio.run(main())
    output_file.close()
