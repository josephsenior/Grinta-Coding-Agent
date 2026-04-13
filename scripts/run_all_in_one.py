import subprocess
import sys
import time

import requests

print('Starting server...')
server_proc = subprocess.Popen([sys.executable, 'start_server.py'], stdout=sys.stdout, stderr=sys.stderr)

print('Waiting for server to boot...')
time.sleep(10)

print('Entering health check loop...')
for _ in range(15):
    try:
        r = requests.get('http://127.0.0.1:3000/api/v1/health', timeout=2)
        print('Health status:', r.status_code)
        if r.status_code == 200:
            break
    except Exception as e:
        print('Waiting for server...', type(e).__name__)
        time.sleep(2)
else:
    print('WARNING: Server did not become healthy string. Attempting test anyway.')

print('Running test script...')
test_proc = subprocess.run([sys.executable, 'scripts/run_real_task.py'], capture_output=True, text=True)
print('--- TEST STDOUT ---')
print(test_proc.stdout)
print('--- TEST STDERR ---')
print(test_proc.stderr)

print('Terminating server...')
server_proc.terminate()
try:
    server_proc.wait(timeout=5)
except subprocess.TimeoutExpired:
    server_proc.kill()
print('Done.')
