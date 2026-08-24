"""
Diagnostic: reproduce the bugs for the three issues.
"""
import re
import sys
sys.path.insert(0, ".")

# Simulate the LLM output for "Low Acrylonitrile NBR"
# (from the task-2671 run)
target_modifications = ['low acrylonitrile', 'low-ACN', 'reduced acrylonitrile content', 'low acrylonitrile NBR']
base_material = ['nitrile rubber', 'NBR', 'acrylonitrile butadiene rubber', 'acrylonitrile-butadiene rubber']

# Example query that LLM generated (representative of what was rejected)
example_queries = [
    "(acrylonitrile content control AND (NBR OR \"nitrile rubber\" OR \"acrylonitrile butadiene rubber\"))",
    "(\"nitrile rubber\" AND (\"acrylonitrile content\" OR \"ACN content\" OR \"monomer ratio\"))",
    "(NBR AND (\"low acrylonitrile\" OR \"reduced ACN\" OR \"acrylonitrile monomer ratio\"))",
]

print("=== BUG 1: QUERY VALIDATOR ===")
print(f"target_modifications = {target_modifications}")
print()
for q in example_queries:
    q_lower = q.lower()
    has_target_mod = any(m.lower() in q_lower for m in target_modifications)
    print(f"Query: {q[:80]}")
    print(f"  has_target_mod (literal match): {has_target_mod}")
    # The problem: 'low acrylonitrile' requires exact substring including 'low'
    # but the query may say 'acrylonitrile content control' without 'low'
    for mod in target_modifications:
        if mod.lower() in q_lower:
            print(f"  FOUND: '{mod}'")
    print()

print("=== BUG 2: ALIAS GENERATION ===")
from app.services.pipeline.orchestrator import PipelineOrchestrator
o = PipelineOrchestrator.__new__(PipelineOrchestrator)

# Simulate base_material list for Low ACN NBR
acn_terms = ['nitrile rubber', 'NBR', 'acrylonitrile butadiene rubber', 'acrylonitrile-butadiene rubber',
             'low acrylonitrile NBR', 'low ACN NBR', 'low ACN nitrile rubber']
aliases = o._generate_aliases(acn_terms)
print(f"Generated aliases for Low ACN NBR: {aliases}")

# Collect ALL material tokens
all_terms = set(acn_terms)
all_terms.update(aliases)
material_tokens = set()
for t in all_terms:
    material_tokens.update(re.findall(r'\b[a-zA-Z]+\b', t.lower()))
print(f"All material_tokens (including short ones): {sorted(material_tokens)}")
short_tokens = [t for t in material_tokens if len(t) < 3]
print(f"SHORT TOKENS (< 3 chars) — THE BUG: {short_tokens}")

# Simulate HNBR  
hnbr_terms = ['hydrogenated nitrile rubber', 'HNBR', 'hydrogenated NBR', 'nitrile rubber', 'NBR']
aliases_hnbr = o._generate_aliases(hnbr_terms)
all_hnbr = set(hnbr_terms)
all_hnbr.update(aliases_hnbr)
mat_tok_hnbr = set()
for t in all_hnbr:
    mat_tok_hnbr.update(re.findall(r'\b[a-zA-Z]+\b', t.lower()))
print(f"\nHNBR aliases: {aliases_hnbr}")
print(f"HNBR short tokens: {[t for t in mat_tok_hnbr if len(t) < 3]}")

print("\n=== BUG 3: LOW-DENSITY CENTRALITY ===")
# US7871546B2 (vegetable oil coolant) would have text that mentions 'nitrile rubber'
# perhaps once in a background 'could be used as' sentence, but the patent is
# about vegetable oil dielectric coolant chemistry.
# Current code only penalizes HIGH list-context hits. Very sparse mention (1-2 hits)
# with 0 list-context hits gets NO penalty at all.
simulated_text_length = 50000  # chars
simulated_alias_hits = 2  # 'nitrile' and 'rubber' appear once each as token matches
simulated_list_context_hits = 0  # no list constructions
print(f"Sparse mention scenario: {simulated_alias_hits} alias token hits in {simulated_text_length} char doc")
print(f"list_context_hits: {simulated_list_context_hits}")
print("With current code: centrality_penalty = 0 (BUG: should be penalized)")

print("\nDiagnostic complete.")
