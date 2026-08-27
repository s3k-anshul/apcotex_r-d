from app.services.pipeline.orchestrator import PipelineOrchestrator
from app.services.pipeline.schemas import LLMCompoundSearchProfile
import re

o = PipelineOrchestrator.__new__(PipelineOrchestrator)

profile_acn = LLMCompoundSearchProfile(
    original_input='Low Acrylonitrile NBR',
    base_material=['nitrile rubber', 'NBR', 'acrylonitrile butadiene rubber', 'acrylonitrile-butadiene rubber'],
    target_modifications=['low acrylonitrile', 'low-ACN', 'reduced acrylonitrile content']
)

material_tokens_acn = set()
for t in profile_acn.base_material:
    for tok in re.findall(r'\b[a-zA-Z]+\b', t.lower()):
        material_tokens_acn.add(tok)
for tok in re.findall(r'\b[a-zA-Z]+\b', 'Low Acrylonitrile NBR'.lower()):
    if tok not in o._DIRECTIONAL_QUALIFIERS and len(tok) >= 3:
        material_tokens_acn.add(tok)

print('Low ACN material_tokens:', sorted(material_tokens_acn))
print('Short tokens (<3):', [t for t in material_tokens_acn if len(t) < 3])
print('"low" present:', 'low' in material_tokens_acn)
assert 'low' not in material_tokens_acn, "FAIL: 'low' still in material_tokens"

# HNBR
material_tokens_hnbr = set()
for t in ['hydrogenated nitrile rubber', 'HNBR', 'hydrogenated NBR', 'nitrile rubber', 'NBR']:
    for tok in re.findall(r'\b[a-zA-Z]+\b', t.lower()):
        material_tokens_hnbr.add(tok)
for tok in re.findall(r'\b[a-zA-Z]+\b', 'Hydrogenated NBR'.lower()):
    if tok not in o._DIRECTIONAL_QUALIFIERS and len(tok) >= 3:
        material_tokens_hnbr.add(tok)
print()
print('HNBR material_tokens:', sorted(material_tokens_hnbr))
print('HNBR short tokens:', [t for t in material_tokens_hnbr if len(t) < 3])
assert not [t for t in material_tokens_hnbr if len(t) < 3], "FAIL: short tokens in HNBR"

print()
print('ALL ASSERTIONS PASSED')
