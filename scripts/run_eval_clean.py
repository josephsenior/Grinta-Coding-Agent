import subprocess
import sys

with open('eval_results.txt', 'w', encoding='utf-8') as out:
    out.write('Starting test via subprocess\n')
    out.flush()
    try:
        proc = subprocess.run(
            [sys.executable, 'run_live_eval.py'],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=120,
        )
        out.write('Return Code: ' + str(proc.returncode) + '\n')
        out.write('--- SCRIPT OUTPUT START ---\n')
        out.write(proc.stdout)
        out.write('\n--- SCRIPT OUTPUT END ---\n')
    except subprocess.TimeoutExpired as e:
        out.write('Timeout expired!\n')
        if e.stdout:
            out.write('--- SCRIPT OUTPUT SO FAR ---\n')
            out.write(
                e.stdout.decode('utf-8') if isinstance(e.stdout, bytes) else e.stdout
            )
    except Exception as e:
        out.write('Error: ' + str(e) + '\n')
