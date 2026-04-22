import json
import os
import sys

sys.path.insert(0, '.')
os.environ['APP_SETTINGS_FILE'] = 'settings.json'

from backend.engine.planner import OrchestratorPlanner
from backend.persistence.data_models.settings import Settings

settings = Settings.model_validate(json.load(open('settings.json')))
planner = OrchestratorPlanner(settings)  # type: ignore
tools = planner.get_tools()  # type: ignore
tools_json = json.dumps(tools, default=str)
print(f'Tool count: {len(tools)}')
print(f'Tool schema total chars: {len(tools_json)}')
print(f'Approx tool tokens: {len(tools_json) // 4}')
for t in tools:
    n = t.get('name') or t.get('function', {}).get('name', '?')
    sz = len(json.dumps(t))
    print(f'  {n}: ~{sz // 4} tokens')
