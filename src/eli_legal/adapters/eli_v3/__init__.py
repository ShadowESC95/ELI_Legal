"""Adapters onto a hosting ELI v3 runtime.

ELI Legal is a separate product that ELI v3 can load as an edition. Only three things are taken
from the host: local model inference, its network gate (so that both gates must agree before
anything leaves the machine), and its capability registry (to advertise the LEGAL_ actions).
Nothing else is imported. ELI Legal does not use the host's kernel, agent bus, memory, desktop
control, shell or scheduler, and keeps its own store, vault, audit ledger and workflow runner.
"""
