"""Errors the setup's jobs raise. The wizard shows their message to the player."""


class SetupError(Exception):
    """A step failed. The message says what went wrong and, where it can, what to do."""


class JobCancelled(Exception):
    """The player stopped the job."""
