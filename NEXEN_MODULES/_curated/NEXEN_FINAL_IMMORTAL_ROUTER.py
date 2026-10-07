import time
import socket
import subprocess

def route_through_spine(event_data):
    print(f'\n[MIDDLEWARE HOOK] Intercepting event. Forcing through INTELLECT SPINE...')
    subprocess.run(['python', 'H:\\NEXEN\\apps\\INTELLECT_SPINE_ROUTER.py'])
    print('[MIDDLEWARE HOOK] Spine processing complete. Finalizing output.')

def check_internet():
    try:
        socket.create_connection(('8.8.8.8', 53), timeout=3)
        return True
    except OSError:
        pass
    return False

print('=== [NEXEN FINAL] IMMORTAL AUTONOMOUS LOOP ACTIVE ===')

while True:
    try:
        if check_internet():
            print('\n[PULSE] System ONLINE. Sweeping events...')
            route_through_spine('Incoming Event / Prompt')
        else:
            print('\n[PULSE] System OFFLINE. Running local renders...')
            route_through_spine('Local Task Execution')
            
        time.sleep(30)
    except Exception as e:
        print(f'[CRITICAL] Error ignored: {e}. FORCING RESTART.')
        time.sleep(1)
        continue
