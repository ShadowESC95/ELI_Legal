"""Measuring how well ELI Legal's analysis steps do their work, against answers fixed in advance.

``research`` measures legal research on real EU and UK legislation; ``linking`` measures how
facts are tied to the issues they bear on. Each runs the code a matter runs, not a copy of it.
The planted-defects evaluation of the whole workflow is in ``application/compliance_service.py``.
"""
