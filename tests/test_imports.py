"""Import every module for real. Other tests swallow import errors on purpose
(e.g. when Redis is missing), which once hid a Python 3.12-only TypeError."""


def test_memory_modules_import():
    import memory.long_term
    import memory.manager
    import memory.short_term
    assert memory.long_term.LongTermMemory.list_facts  # not shadowing builtin `list`


def test_page_modules_import():
    import agent
    import crew.graph
    import tools
    assert agent.run_agent and crew.graph.build_graph and tools.TOOL_SCHEMAS
