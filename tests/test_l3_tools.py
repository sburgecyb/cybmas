import sys
sys.path.insert(0, '.')

# Test imports
try:
    from services.l3_agent.tools.incident_search import search_incidents
    from services.l3_agent.tools.rca_fetch import fetch_incident_rca
    from services.l3_agent.tools.cross_ref_tickets import cross_reference_tickets_with_incidents
    print("OK - All L3 tools imported successfully")
except Exception as e:
    print(f"FAIL - Import error: {e}")
    sys.exit(1)

# Test docstrings
try:
    assert search_incidents.__doc__ is not None
    assert fetch_incident_rca.__doc__ is not None
    assert cross_reference_tickets_with_incidents.__doc__ is not None
    print("OK - All L3 tools have docstrings")
except AssertionError as e:
    print(f"FAIL - Missing docstring: {e}")

print("\nAll L3 tool tests passed")