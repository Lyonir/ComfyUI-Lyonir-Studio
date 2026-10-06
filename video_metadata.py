"""Capture upstream sampler seeds from the executed API prompt, as exact strings."""
def generation_seeds(prompt, save_node_id, image_input="images"):
    if not isinstance(prompt, dict):
        return []
    graph = {str(k): v for k, v in prompt.items() if isinstance(v, dict)}

    def link(value):
        return isinstance(value, (list, tuple)) and len(value) == 2 and str(value[0]) in graph and isinstance(value[1], int)

    def number(value, seen=None):
        seen = set() if seen is None else seen
        if link(value):
            key = str(value[0])
            if key in seen:
                return None
            seen.add(key)
            inputs = graph[key].get('inputs', {})
            # Only forward explicit seed/value providers; arbitrary computed
            # outputs cannot be reconstructed reliably from their inputs.
            for name in ('seed', 'noise_seed', 'value'):
                if name in inputs:
                    return number(inputs[name], seen)
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, int) and value >= 0:
            return str(value)
        if isinstance(value, str) and value.isdigit():
            return str(int(value))
        return None

    start = graph.get(str(save_node_id), {}).get('inputs', {}).get(image_input)
    pending = [str(start[0])] if link(start) else []
    seen, seeds = set(), []
    while pending:
        key = pending.pop(0)
        if key in seen:
            continue
        seen.add(key)
        node = graph[key]
        inputs = node.get('inputs', {})
        kind = str(node.get('class_type', '')).lower()
        if 'sampler' in kind or kind == 'randomnoise':
            value = number(inputs.get('seed', inputs.get('noise_seed')))
            if value is not None:
                if value not in seeds:
                    seeds.append(value)
            # Do not mislabel an older sampling stage as the final seed when
            # the final sampler's connected seed cannot be resolved.
            if 'seed' in inputs or 'noise_seed' in inputs:
                continue
        pending.extend(str(v[0]) for v in inputs.values() if link(v))
    return seeds
