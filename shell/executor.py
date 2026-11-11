"""Session lifetime hooks for blocks that own resources."""


class SessionBlock:
    """A block's session instance can stop work and release owned resources."""
    def request_stop(self):
        pass

    def close_session(self):
        pass
