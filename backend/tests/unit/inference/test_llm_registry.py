"""Unit tests for backend.inference.llm_registry."""

from __future__ import annotations

from unittest import TestCase
from unittest.mock import MagicMock, patch

from backend.inference.llm_registry import (
    LLMRegistry,
    RegistryEvent,
)


class TestRegistryEvent(TestCase):
    """Test RegistryEvent dataclass."""

    def test_default_values(self):
        """Test RegistryEvent default values."""
        event = RegistryEvent()
        self.assertEqual(event.event_type, 'update')
        self.assertIsNone(event.key)
        self.assertIsNone(event.llm)
        self.assertIsNone(event.service_id)

    def test_custom_values(self):
        """Test RegistryEvent with custom values."""
        mock_llm = MagicMock()
        event = RegistryEvent(
            event_type='create',
            key='test_key',
            llm=mock_llm,
            service_id='service123',
        )
        self.assertEqual(event.event_type, 'create')
        self.assertEqual(event.key, 'test_key')
        self.assertIs(event.llm, mock_llm)
        self.assertEqual(event.service_id, 'service123')


class TestLLMRegistry(TestCase):
    """Test LLMRegistry class."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_config = MagicMock()
        self.mock_config.default_agent = 'test_agent'
        self.mock_config.get_agent_to_llm_config_map.return_value = {}

        self.mock_llm_config = MagicMock()
        self.mock_llm_config.model = 'gpt-4o'
        self.mock_config.get_llm_config_from_agent.return_value = self.mock_llm_config

    @patch('backend.inference.llm_registry.LLM')
    def test_init(self, mock_llm_cls):
        """Test LLMRegistry initialization."""
        mock_llm = MagicMock()
        mock_llm_cls.return_value = mock_llm

        registry = LLMRegistry(self.mock_config, agent_cls='custom_agent')

        self.assertIsNotNone(registry.registry_id)
        self.assertIsNotNone(registry.config)
        self.assertEqual(registry.service_to_llm['agent'], mock_llm)
        self.assertEqual(registry.active_agent_llm, mock_llm)

    @patch('backend.inference.llm_registry.LLM')
    @patch('backend.inference.llm_registry.copy.deepcopy')
    def test_init_with_default_agent(self, mock_deepcopy, mock_llm_cls):
        """Test initialization uses default agent when none specified."""
        mock_llm = MagicMock()
        mock_llm_cls.return_value = mock_llm

        # Setup the deepcopy to return a mock that we can track
        mock_config_copy = MagicMock()
        mock_config_copy.default_agent = 'test_agent'
        mock_config_copy.get_agent_to_llm_config_map.return_value = {}
        mock_config_copy.get_llm_config_from_agent.return_value = self.mock_llm_config
        mock_deepcopy.return_value = mock_config_copy

        LLMRegistry(self.mock_config)

        mock_config_copy.get_llm_config_from_agent.assert_called_with('test_agent')

    @patch('backend.inference.llm_registry.LLM')
    def test_init_with_retry_listener(self, mock_llm_cls):
        """Test initialization with retry listener."""
        mock_listener = MagicMock()
        mock_llm = MagicMock()
        mock_llm_cls.return_value = mock_llm

        registry = LLMRegistry(self.mock_config, retry_listener=mock_listener)

        self.assertEqual(registry.retry_listner, mock_listener)
        # Verify LLM was created with listener
        mock_llm_cls.assert_called()

    @patch('backend.inference.llm_registry.LLM')
    def test_create_new_llm(self, mock_llm_cls):
        """Test _create_new_llm creates and registers LLM."""
        mock_llm = MagicMock()
        mock_llm_cls.return_value = mock_llm

        registry = LLMRegistry(self.mock_config)

        new_llm = registry._create_new_llm('test_service', self.mock_llm_config)

        self.assertEqual(new_llm, mock_llm)
        self.assertIn('test_service', registry.service_to_llm)
        self.assertEqual(registry.service_to_llm['test_service'], mock_llm)

    @patch('backend.inference.llm_registry.LLM')
    def test_create_new_llm_without_listener(self, mock_llm_cls):
        """Test _create_new_llm without retry listener."""
        mock_llm = MagicMock()
        mock_llm_cls.return_value = mock_llm

        registry = LLMRegistry(self.mock_config)

        registry._create_new_llm(
            'no_listener_service', self.mock_llm_config, with_listener=False
        )

        # Should have created LLM without retry_listener
        call_kwargs = mock_llm_cls.call_args_list[-1].kwargs
        self.assertNotIn('retry_listener', call_kwargs)

    @patch('backend.inference.llm_registry.LLM')
    def test_create_new_llm_notifies_subscriber(self, mock_llm_cls):
        """Test _create_new_llm notifies registered subscribers."""
        mock_llm = MagicMock()
        mock_llm_cls.return_value = mock_llm

        registry = LLMRegistry(self.mock_config)
        mock_subscriber = MagicMock()
        registry.subscriber = mock_subscriber

        registry._create_new_llm('notify_test', self.mock_llm_config)

        # Should notify about both agent and new service creation
        self.assertGreaterEqual(mock_subscriber.call_count, 1)

    @patch('backend.inference.llm_registry.LLM')
    def test_request_extraneous_completion_new_service(self, mock_llm_cls):
        """Test request_extraneous_completion creates new service."""
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = ' Test response '
        mock_llm.completion.return_value = mock_response
        mock_llm_cls.return_value = mock_llm

        registry = LLMRegistry(self.mock_config)

        result = registry.request_extraneous_completion(
            'extraneous_service',
            self.mock_llm_config,
            [{'role': 'user', 'content': 'test'}],
        )

        self.assertEqual(result, 'Test response')
        self.assertIn('extraneous_service', registry.service_to_llm)
        mock_llm.completion.assert_called_once()

    @patch('backend.inference.llm_registry.LLM')
    def test_request_extraneous_completion_existing_service(self, mock_llm_cls):
        """Test request_extraneous_completion reuses existing service."""
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = 'Reused response'
        mock_llm.completion.return_value = mock_response
        mock_llm_cls.return_value = mock_llm

        registry = LLMRegistry(self.mock_config)
        registry.service_to_llm['existing_service'] = mock_llm

        result = registry.request_extraneous_completion(
            'existing_service',
            self.mock_llm_config,
            [{'role': 'user', 'content': 'test'}],
        )

        self.assertEqual(result, 'Reused response')

    @patch('backend.inference.llm_registry.LLM')
    def test_get_llm_from_agent_config(self, mock_llm_cls):
        """Test get_llm_from_agent_config."""
        mock_llm = MagicMock()
        mock_llm_cls.return_value = mock_llm
        mock_agent_config = MagicMock()

        registry = LLMRegistry(self.mock_config)

        llm = registry.get_llm_from_agent_config('agent_service', mock_agent_config)

        self.assertEqual(llm, mock_llm)
        self.assertIn('agent_service', registry.service_to_llm)

    @patch('backend.inference.llm_registry.LLM')
    def test_get_llm_from_agent_config_existing(self, mock_llm_cls):
        """Test get_llm_from_agent_config returns existing LLM."""
        mock_llm = MagicMock()
        mock_llm_cls.return_value = mock_llm
        mock_agent_config = MagicMock()

        registry = LLMRegistry(self.mock_config)
        registry.service_to_llm['existing_agent'] = mock_llm

        llm = registry.get_llm_from_agent_config('existing_agent', mock_agent_config)

        self.assertEqual(llm, mock_llm)

    @patch('backend.inference.llm_registry.LLM')
    def test_get_llm_new_service(self, mock_llm_cls):
        """Test get_llm creates new service with config."""
        mock_llm = MagicMock()
        mock_llm_cls.return_value = mock_llm

        registry = LLMRegistry(self.mock_config)

        llm = registry.get_llm('new_service', self.mock_llm_config)

        self.assertEqual(llm, mock_llm)
        self.assertIn('new_service', registry.service_to_llm)

    @patch('backend.inference.llm_registry.LLM')
    def test_get_llm_existing_service(self, mock_llm_cls):
        """Test get_llm returns existing service."""
        mock_llm = MagicMock()
        mock_llm.config = self.mock_llm_config
        mock_llm_cls.return_value = mock_llm

        registry = LLMRegistry(self.mock_config)
        registry.service_to_llm['existing'] = mock_llm

        llm = registry.get_llm('existing', self.mock_llm_config)

        self.assertEqual(llm, mock_llm)

    @patch('backend.inference.llm_registry.LLM')
    def test_get_llm_without_config_raises(self, mock_llm_cls):
        """Test get_llm raises ValueError when requesting new service without config."""
        mock_llm = MagicMock()
        mock_llm_cls.return_value = mock_llm

        registry = LLMRegistry(self.mock_config)

        with self.assertRaises(ValueError) as cm:
            registry.get_llm('unknown_service')

        self.assertIn('without specifying LLM config', str(cm.exception))

    @patch('backend.inference.llm_registry.LLM')
    def test_get_llm_config_mismatch_raises(self, mock_llm_cls):
        """Test get_llm raises ValueError when config doesn't match existing service."""
        mock_llm = MagicMock()
        mock_llm.config = self.mock_llm_config
        mock_llm_cls.return_value = mock_llm

        registry = LLMRegistry(self.mock_config)
        registry.service_to_llm['mismatch_service'] = mock_llm

        different_config = MagicMock()
        different_config.model = 'different-model'

        with self.assertRaises(ValueError) as cm:
            registry.get_llm('mismatch_service', different_config)

        self.assertIn('different config', str(cm.exception))

    @patch('backend.inference.llm_registry.LLM')
    def test_get_active_llm(self, mock_llm_cls):
        """Test get_active_llm returns active agent LLM."""
        mock_llm = MagicMock()
        mock_llm_cls.return_value = mock_llm

        registry = LLMRegistry(self.mock_config)

        active_llm = registry.get_active_llm()

        self.assertEqual(active_llm, registry.active_agent_llm)

    @patch('backend.inference.llm_registry.LLM')
    def test_set_active_llm(self, mock_llm_cls):
        """Test _set_active_llm changes active LLM."""
        mock_llm1 = MagicMock()
        mock_llm2 = MagicMock()
        mock_llm_cls.side_effect = [mock_llm1, mock_llm2]

        registry = LLMRegistry(self.mock_config)
        registry.service_to_llm['new_active'] = mock_llm2

        registry._set_active_llm('new_active')

        self.assertEqual(registry.active_agent_llm, mock_llm2)

    @patch('backend.inference.llm_registry.LLM')
    def test_set_active_llm_unknown_service_raises(self, mock_llm_cls):
        """Test _set_active_llm raises ValueError for unknown service."""
        mock_llm = MagicMock()
        mock_llm_cls.return_value = mock_llm

        registry = LLMRegistry(self.mock_config)

        with self.assertRaises(ValueError) as cm:
            registry._set_active_llm('unknown_service')

        self.assertIn('Unrecognized service ID', str(cm.exception))

    @patch('backend.inference.llm_registry.LLM')
    def test_subscribe(self, mock_llm_cls):
        """Test subscribe registers callback and notifies immediately."""
        mock_llm = MagicMock()
        mock_llm.service_id = 'agent'
        mock_llm_cls.return_value = mock_llm

        registry = LLMRegistry(self.mock_config)
        mock_callback = MagicMock()

        registry.subscribe(mock_callback)

        self.assertEqual(registry.subscriber, mock_callback)
        # Should immediately notify with current active LLM
        mock_callback.assert_called()
        event = mock_callback.call_args[0][0]
        self.assertEqual(event.llm, registry.active_agent_llm)

    @patch('backend.inference.llm_registry.LLM')
    def test_notify_calls_subscriber(self, mock_llm_cls):
        """Test notify calls registered subscriber."""
        mock_llm = MagicMock()
        mock_llm_cls.return_value = mock_llm

        registry = LLMRegistry(self.mock_config)
        mock_callback = MagicMock()
        registry.subscriber = mock_callback

        test_event = RegistryEvent(event_type='test', service_id='test_svc')
        registry.notify(test_event)

        mock_callback.assert_called_with(test_event)

    @patch('backend.inference.llm_registry.LLM')
    def test_notify_no_subscriber(self, mock_llm_cls):
        """Test notify does nothing when no subscriber registered."""
        mock_llm = MagicMock()
        mock_llm_cls.return_value = mock_llm

        registry = LLMRegistry(self.mock_config)
        test_event = RegistryEvent()

        # Should not raise
        registry.notify(test_event)

    @patch('backend.inference.llm_registry.LLM')
    @patch('backend.inference.llm_registry.logger')
    def test_notify_handles_subscriber_exception(self, mock_logger, mock_llm_cls):
        """Test notify handles exceptions from subscriber gracefully."""
        mock_llm = MagicMock()
        mock_llm_cls.return_value = mock_llm

        registry = LLMRegistry(self.mock_config)

        def failing_callback(event):
            raise RuntimeError('Subscriber error')

        registry.subscriber = failing_callback

        test_event = RegistryEvent()
        registry.notify(test_event)

        # Should log warning but not raise
        mock_logger.warning.assert_called()

    @patch('backend.inference.llm_registry.LLM')
    def test_config_deepcopy(self, mock_llm_cls):
        """Test that config is deep copied on initialization."""
        mock_llm = MagicMock()
        mock_llm_cls.return_value = mock_llm

        with patch('backend.inference.llm_registry.copy.deepcopy') as mock_deepcopy:
            mock_deepcopy.return_value = self.mock_config

            LLMRegistry(self.mock_config)

            mock_deepcopy.assert_called_with(self.mock_config)

    @patch('backend.inference.llm_registry.LLM')
    def test_registry_id_is_unique(self, mock_llm_cls):
        """Test that each registry instance gets unique ID."""
        mock_llm = MagicMock()
        mock_llm_cls.return_value = mock_llm

        registry1 = LLMRegistry(self.mock_config)
        registry2 = LLMRegistry(self.mock_config)

        self.assertNotEqual(registry1.registry_id, registry2.registry_id)

    @patch('backend.inference.llm_registry.LLM')
    def test_agent_to_llm_config_map(self, mock_llm_cls):
        """Test agent_to_llm_config map is initialized."""
        mock_llm = MagicMock()
        mock_llm_cls.return_value = mock_llm

        test_map = {'agent1': MagicMock(), 'agent2': MagicMock()}
        self.mock_config.get_agent_to_llm_config_map.return_value = test_map

        registry = LLMRegistry(self.mock_config)

        self.assertEqual(registry.agent_to_llm_config, test_map)


if __name__ == '__main__':
    import unittest

    unittest.main()
