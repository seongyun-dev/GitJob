"""Analysis worker process package."""

__all__ = ["app"]


def __getattr__(name):
    # Completion clients and migration CLI must not initialize the HTTP server
    # or require its Registry/DB configuration merely by importing this package.
    if name != "app":
        raise AttributeError(name)
    from worker.api import create_compute_app

    app = create_compute_app()
    globals()[name] = app
    return app
