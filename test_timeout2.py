import subprocess
import time
import threading

proc = None
def run_cmd():
    global proc
    print('Starting')
    proc = subprocess.Popen(['bash', '-c', 'sleep 1000'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print(f'Started pid {proc.pid}')
    try:
        proc.communicate()
    except subprocess.TimeoutExpired:
        print('Timeout expired block')
    print('Done communicating')

t = threading.Thread(target=run_cmd)
t.start()
time.sleep(2)
print('Killing from main thread')
subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'])
t.join()
print('Main thread done')
