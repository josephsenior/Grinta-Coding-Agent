"""Resolve an explicitly verified prepared image without mutating task records."""

import re


def verified_runtime(record, registry, evidence):
    task_id = record['identity']['task_id']
    matches = [item for item in evidence if item.get('task_id') == task_id]
    if len(matches) != 1:
        raise ValueError('exactly one runtime verification record is required')
    item = matches[0]
    binding = registry['task_bindings'][task_id]
    image = binding['prepared_image_id']
    pair = item.get('paired_result', {})
    if (
        not re.fullmatch(r'sha256:[0-9a-f]{64}', image)
        or item.get('status') != 'pass'
        or item.get('source_spec_sha256') != record['spec_sha256']
        or binding['parent_image_id'] != record['environment']['effective_image_id']
        or item.get('parent_image_id') != binding['parent_image_id']
        or item.get('prepared_runtime_image') != image
        or pair.get('prepared_runtime_image') != image
        or not pair.get('containers_match')
        or not pair.get('initial_task_probes_match')
        or not item.get('task_toolchain_unchanged')
        or not item.get('parent_image_layers_verified')
    ):
        raise ValueError('prepared runtime does not match the verified task setup')
    return image
