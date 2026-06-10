import logging
from abc import ABC, abstractmethod
from pathlib import Path
from core.events import SignalReceived

log = logging.getLogger(__name__)


class BaseSignalProcessor(ABC):
    """Base abstract class for all specialized signal processors in the decentralized pipeline."""

    def __init__(self, name: str, knowledge_path: str = None) -> None:
        self.name = name
        self.knowledge_path = knowledge_path
        self._knowledge_content = ""

    def load_knowledge(self) -> str:
        """Load knowledge grounding content from the specified markdown file path."""
        if not self.knowledge_path:
            return ""

        path = Path(self.knowledge_path)
        if not path.is_absolute():
            # Resolve relative to the workspace root (5 levels up from nerves/workers/trading/processor)
            workspace_root = Path(__file__).parent.parent.parent.parent.parent
            path = workspace_root / path

        try:
            if path.exists():
                self._knowledge_content = path.read_text(encoding="utf-8")
                log.info(
                    f"Processor '{self.name}': Grounding knowledge loaded from {path.name}"
                )
            else:
                log.warning(
                    f"Processor '{self.name}': Knowledge file not found at {path}"
                )
        except Exception as e:
            log.error(f"Processor '{self.name}': Failed to read knowledge file: {e}")

        return self._knowledge_content

    @abstractmethod
    async def process(self, event: SignalReceived) -> bool:
        """Process the signal event.

        Returns True if the signal is valid/accepted, False if it is rejected.
        """
        pass
