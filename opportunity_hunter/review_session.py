"""Normal Chrome session for manual sign-in; attach instead of relaunching its profile."""
import json
import os
import re
import socket
import subprocess
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit


def _version(port):
    base=f'http://127.0.0.1:{port}'
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(base+'/json/version',timeout=1) as response:info=json.load(response)
    ws=urlsplit(info.get('webSocketDebuggerUrl',''))
    if not str(info.get('Browser','')).startswith('Chrome/') or ws.hostname!='127.0.0.1' or ws.port!=port or not re.fullmatch(r'/devtools/browser/[a-zA-Z0-9-]+',ws.path):raise ValueError('Not the dedicated local Chrome')
    return base,ws.path


def endpoint(root):
    root=Path(root).resolve()
    try:
        descriptor=json.loads((root/'data/reviews/browser-session.json').read_text())
        if descriptor['profile']!=str(root/'data/profiles/opportunity-hunter'):return None
        port=descriptor['port']
        if isinstance(port,bool) or not isinstance(port,int) or not 1024<=port<=65535:return None
        base,browser_id=_version(port)
        return base if browser_id==descriptor['browser_id'] else None
    except (OSError,ValueError,KeyError,IndexError,TypeError):return None


def open_browser(root):
    root=Path(root).resolve()
    if endpoint(root):return {'status':'open','profile':'opportunity-hunter'}
    chrome=Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
    if not chrome.exists():raise ValueError('Installed Google Chrome is required for manual review sign-in')
    profile=root/'data/profiles/opportunity-hunter';profile.mkdir(parents=True,exist_ok=True);profile.chmod(0o700)
    folder=root/'data/reviews';folder.mkdir(exist_ok=True)
    # Choose a real nonzero port. Chrome's special port=0 mode marks a normal browser
    # as WebDriver-controlled; it is unsuitable for a manually signed-in session.
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    fd=os.open(folder/'browser-session.log',os.O_CREAT|os.O_APPEND|os.O_WRONLY,0o600)
    with os.fdopen(fd,'ab') as log:
        proc=subprocess.Popen([str(chrome),'--remote-debugging-address=127.0.0.1','--remote-debugging-port='+str(port),
                          '--user-data-dir='+str(profile),'--profile-directory=Default','--no-first-run',
                          '--no-default-browser-check','https://www.google.com/maps'],stdout=log,stderr=log,start_new_session=True)
    for _ in range(40):
        if proc.poll() is not None:break
        try:
            _,browser_id=_version(port)
            descriptor={'profile':str(profile),'port':port,'browser_id':browser_id,'pid':proc.pid}
            marker=folder/'browser-session.json';marker.write_text(json.dumps(descriptor));marker.chmod(0o600)
            return {'status':'open','profile':'opportunity-hunter'}
        except (OSError,ValueError):time.sleep(.2)
    return {'status':'needs_close','reason':'Close the earlier dedicated review Chrome instance, then retry --login. Other Chrome profiles are unaffected.'}
