"""Tests for backend.engine.tools.common."""

from __future__ import annotations

from backend.engine.tools.common import (
    create_tool_definition,
    get_command_param,
    get_is_input_param,
    get_path_param,
    get_security_risk_param,
    get_timeout_param,
    get_url_param,
)

# ---------------------------------------------------------------------------
# create_tool_definition
# ---------------------------------------------------------------------------


class TestCreateToolDefinition:
    def test_returns_dict_with_type_function(self):
        tool = create_tool_definition(
            name='my_tool',
            description='Does stuff',
            properties={'x': {'type': 'string'}},
            required=['x'],
        )
        assert isinstance(tool, dict)
        assert tool.get('type') == 'function'

    def test_function_name_set(self):
        tool = create_tool_definition(
            name='my_tool',
            description='Desc',
            properties={},
            required=[],
        )
        assert tool['function']['name'] == 'my_tool'

    def test_description_set(self):
        tool = create_tool_definition(
            name='t',
            description='My description',
            properties={},
            required=[],
        )
        assert tool['function']['description'] == 'My description'

    def test_properties_embedded(self):
        props = {'alpha': {'type': 'string'}, 'beta': {'type': 'integer'}}
        tool = create_tool_definition(
            name='t', description='d', properties=props, required=['alpha']
        )
        assert tool['function']['parameters']['properties'] == props

    def test_required_list_embedded(self):
        tool = create_tool_definition(
            name='t',
            description='d',
            properties={'x': {'type': 'string'}},
            required=['x'],
        )
        assert tool['function']['parameters']['required'] == ['x']

    def test_additional_properties_default_false(self):
        tool = create_tool_definition(
            name='t', description='d', properties={}, required=[]
        )
        assert tool['function']['parameters']['additionalProperties'] is False

    def test_additional_properties_can_be_true(self):
        tool = create_tool_definition(
            name='t',
            description='d',
            properties={},
            required=[],
            additional_properties=True,
        )
        assert tool['function']['parameters']['additionalProperties'] is True

    def test_empty_properties_and_required(self):
        tool = create_tool_definition(
            name='empty_tool', description='No params', properties={}, required=[]
        )
        assert tool['function']['parameters']['properties'] == {}
        assert tool['function']['parameters']['required'] == []


# ---------------------------------------------------------------------------
# get_is_input_param
# ---------------------------------------------------------------------------


class TestGetIsInputParam:
    def test_returns_dict(self):
        param = get_is_input_param()
        assert isinstance(param, dict)

    def test_type_is_string(self):
        assert get_is_input_param()['type'] == 'string'

    def test_enum_has_true_false(self):
        enum = get_is_input_param()['enum']
        assert 'true' in enum
        assert 'false' in enum

    def test_custom_description_used(self):
        param = get_is_input_param('Custom desc')
        assert param['description'] == 'Custom desc'

    def test_default_description_not_empty(self):
        param = get_is_input_param()
        assert len(param['description']) > 0


# ---------------------------------------------------------------------------
# get_security_risk_param
# ---------------------------------------------------------------------------


class TestGetSecurityRiskParam:
    def test_returns_dict(self):
        assert isinstance(get_security_risk_param(), dict)

    def test_type_is_string(self):
        assert get_security_risk_param()['type'] == 'string'

    def test_has_description(self):
        param = get_security_risk_param()
        assert 'description' in param
        assert len(param['description']) > 0

    def test_has_enum(self):
        param = get_security_risk_param()
        assert 'enum' in param
        assert len(param['enum']) >= 1


# ---------------------------------------------------------------------------
# get_command_param
# ---------------------------------------------------------------------------


class TestGetCommandParam:
    def test_returns_dict(self):
        assert isinstance(get_command_param('desc'), dict)

    def test_type_is_string(self):
        assert get_command_param('do it')['type'] == 'string'

    def test_description_set(self):
        param = get_command_param('Execute command')
        assert param['description'] == 'Execute command'

    def test_no_enum_by_default(self):
        param = get_command_param('desc')
        assert 'enum' not in param

    def test_enum_added_when_provided(self):
        param = get_command_param('Mode', ['view', 'edit'])
        assert param['enum'] == ['view', 'edit']

    def test_empty_enum_not_added(self):
        # falsy empty list → enum not added
        param = get_command_param('cmd', [])
        assert 'enum' not in param


# ---------------------------------------------------------------------------
# get_url_param
# ---------------------------------------------------------------------------


class TestGetUrlParam:
    def test_returns_dict(self):
        assert isinstance(get_url_param(), dict)

    def test_type_is_string(self):
        assert get_url_param()['type'] == 'string'

    def test_default_description(self):
        param = get_url_param()
        assert 'url' in param['description'].lower() or len(param['description']) > 0

    def test_custom_description(self):
        param = get_url_param('Load this URL')
        assert param['description'] == 'Load this URL'


# ---------------------------------------------------------------------------
# get_path_param
# ---------------------------------------------------------------------------


class TestGetPathParam:
    def test_returns_dict(self):
        assert isinstance(get_path_param('Path to file'), dict)

    def test_type_is_string(self):
        assert get_path_param('File path')['type'] == 'string'

    def test_description_set(self):
        param = get_path_param('File path to read')
        assert param['description'] == 'File path to read'


# ---------------------------------------------------------------------------
# get_timeout_param
# ---------------------------------------------------------------------------


class TestGetTimeoutParam:
    def test_returns_dict(self):
        assert isinstance(get_timeout_param('Timeout in seconds'), dict)

    def test_type_is_number(self):
        assert get_timeout_param('Timeout')['type'] == 'number'

    def test_description_set(self):
        param = get_timeout_param('Max wait time')
        assert param['description'] == 'Max wait time'
