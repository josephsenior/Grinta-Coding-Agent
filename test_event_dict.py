"""Check if event_to_dict works correctly for AgentStateChangedObservation."""
import sys, json

try:
    from backend.events.observation.agent import AgentStateChangedObservation
    sys.stderr.write("Import AgentStateChangedObservation: OK\n")
except Exception as e:
    sys.stderr.write(f"IMPORT ERROR: {e}\n")
    sys.exit(1)

try:
    from backend.events.serialization import event_to_dict
    sys.stderr.write("Import event_to_dict: OK\n")
except Exception as e:
    sys.stderr.write(f"IMPORT ERROR: {e}\n")
    sys.exit(1)

try:
    obs = AgentStateChangedObservation("", "awaiting_user_input", "Default state on connection")
    sys.stderr.write(f"Created observation: {obs}\n")
except Exception as e:
    sys.stderr.write(f"CREATION ERROR: {e}\n")
    import traceback; traceback.print_exc(file=sys.stderr)
    sys.exit(1)

try:
    d = event_to_dict(obs)
    sys.stderr.write(f"event_to_dict result: {json.dumps(d, indent=2)}\n")
except Exception as e:
    sys.stderr.write(f"event_to_dict ERROR: {e}\n")
    import traceback; traceback.print_exc(file=sys.stderr)
    sys.exit(1)
