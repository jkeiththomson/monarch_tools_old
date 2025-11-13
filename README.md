# monarch-tools (clean)

Fresh, PyCharm-friendly CLI toolbox with **four commands**:
- `hello` — prints “Hello, World”
- `name <your_name>` — greets the provided name
- `help` — lists command names and arguments

## Why this version?
- Uses a **src/** layout to avoid import shadowing
- Provides **module-mode** PyCharm Run/Debug configurations (more resilient)
- Includes `__main__.py` so you can run `python -m monarch_tools`

## Quick start
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
```

### Run
```bash
# via console script (installed by pip)
monarch-tools hello
monarch-tools name "Kathy"
monarch-tools help

# or directly as a module (bypasses PATH issues)
python -m monarch_tools hello
python -m monarch_tools name Keith
python -m monarch_tools help
```

## If you had a previous install
In your active venv:
```bash
python -m pip uninstall -y monarch-tools
pip install -e .
```
