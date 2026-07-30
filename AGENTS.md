# Cosmic Pulse — terminal agent map

Entry: **server.py** (HTTP) + **index.html** (UI). No app.py.

## Review workflow (bash only)
```bash
ls *.py
rg -n "threading|while True|time.sleep|global " server.py store.py stutter.py | head -40
sed -n '1,100p' server.py
python3 -m pytest tests/ -q --tb=line
```

Hot files: server.py, store.py, stutter.py, games.py, diagnostics.py, index.html
