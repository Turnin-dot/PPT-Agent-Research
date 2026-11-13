from pathlib import Path
import json, sys
from demos.environment import inspect_environment
value=inspect_environment(Path('outputs/environment').resolve())
print(json.dumps(value,ensure_ascii=False,indent=2))
raise SystemExit(0 if value['ready_for_local_tools'] else 1)
