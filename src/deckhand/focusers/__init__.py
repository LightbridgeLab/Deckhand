"""Platform-specific focuser primitives.

A focuser is an async, no-arg callable that brings a specific window/tab
to the foreground on the local machine when invoked. Each platform
target (iTerm, Cursor, browser tabs) lives in its own submodule. The
orchestrator's :class:`~deckhand.orchestrator.focusers.FocuserRegistry`
stores them keyed by agent id; the ``agents.focus_next_pending`` action
looks them up at press time.
"""
