"""Claude Code hook logic for the insar-agent plugin.

Kept under ``src`` (not the plugin ``hooks/`` dir) so the decision logic is
importable and unit-testable. The thin scripts in the plugin ``hooks/``
directory bootstrap ``sys.path`` and delegate here.
"""
