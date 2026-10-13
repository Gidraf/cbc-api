from .base import Flow, NeedsHuman, NotLoggedIn, StepFailed
from .facebook import Facebook
from .instagram import Instagram
from .linkedin import LinkedIn
from .tiktok import TikTok
from .youtube import YouTube

FLOWS: dict[str, Flow] = {f.platform: f for f in (TikTok(), Instagram(), Facebook(), YouTube(), LinkedIn())}

__all__ = ["FLOWS", "Flow", "NeedsHuman", "NotLoggedIn", "StepFailed"]
