"""Repository analysis worker: Kafka request -> pinned checkout on local disk.

Separate from `worker/` (C's compute HTTP API) and `github/` (bulk public
snapshot collection for the Registry). Those serve different features; this one
handles a signed-in user's request for one repository at one commit.
"""
