"""Command-line entry points.

``main.py`` holds the Typer app (``sentinel validate``, and Milestone 2's
still-pending ``sentinel history``); ``bootstrap.py`` is the composition
root each command calls once; ``resolution.py`` resolves a dataset name
to its Dataset/Policy YAML on disk. See
docs/architecture/0003-milestone-2-architecture.md Part 8.
"""
