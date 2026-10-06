from eli_legal.adapters.eli_v2.inference import EliV2InferenceAdapter
from eli_legal.adapters.eli_v2.network import EliV2NetworkAdapter
from eli_legal.adapters.eli_v2.workflow import EliV2WorkflowAdapter


def test_eli_v2_adapters_import_without_requiring_eli_at_module_import_time():
    assert EliV2InferenceAdapter
    assert EliV2NetworkAdapter
    assert EliV2WorkflowAdapter
