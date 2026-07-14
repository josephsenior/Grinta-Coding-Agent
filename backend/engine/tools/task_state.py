"""Single model-facing tool for durable contract and plan state."""
from typing import Any

from backend.core.tools.tool_names import TASK_STATE_TOOL_NAME
from backend.engine.contracts import ChatCompletionToolParam
from backend.engine.tools.param_defs import create_tool_definition, get_command_param


def create_task_state_tool() -> ChatCompletionToolParam:
    item: dict[str, Any] = {'type':'object','properties':{'id':{'type':'string'},'text':{'type':'string'},'source':{'type':'string','enum':['user','repository','system','agent']},'status':{'type':'string','enum':['unknown','satisfied','gap','not_applicable']}},'required':['text'],'additionalProperties':False}
    task = {'type':'object','properties':{'id':{'type':'string'},'description':{'type':'string'},'status':{'type':'string','enum':['todo','in_progress','done','skipped','blocked']},'result':{'type':'string'}},'required':['id','description'],'additionalProperties':False}
    evidence = {'type':'object','properties':{'item_id':{'type':'string'},'status':{'type':'string','enum':['unknown','satisfied','gap','not_applicable']},'evidence':{'type':'string'},'kind':{'type':'string'}},'required':['item_id','status','evidence'],'additionalProperties':False}
    return create_tool_definition(name=TASK_STATE_TOOL_NAME, description='Create and maintain durable task state. The contract records what must remain true; the plan records the current strategy and may be replaced. Use set, update_task, review, or audit. Never record implementation hypotheses as user requirements.', properties={'action':get_command_param('set replaces only supplied contract or plan fields; update_task changes one task; review is read-only; audit records contract evidence.', ['set','update_task','review','audit']),'expected_revision':{'type':'integer'},'objective':{'type':'string'},'requirements':{'type':'array','items':item},'constraints':{'type':'array','items':item},'success_conditions':{'type':'array','items':item},'tasks':{'type':'array','items':task},'task_id':{'type':'string'},'status':{'type':'string'},'result':{'type':'string'},'evidence':{'type':'array','items':evidence}}, required=['action'])
