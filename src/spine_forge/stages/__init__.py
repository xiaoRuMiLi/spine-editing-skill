"""Pipeline stages. Every stage reads files and writes files -- no hidden state.

That constraint is what lets an agent drive the pipeline one command at a time,
and what lets a human edit the JSON in between two commands.
"""

__all__ = ["split", "rig", "build", "preview"]
