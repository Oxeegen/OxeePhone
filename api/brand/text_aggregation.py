"""First clause of a reply sent to the voice model without waiting for the
whole sentence (call-engine setting ``performance.tts_first_clause``).

Pipecat hands text to the TTS one sentence at a time: the first audio of a
reply waits until the language model has written its whole first sentence
(and one more character, to confirm the sentence ends there). With this
aggregator the first piece of each reply ends at its first comma or colon
once it holds a few words; the rest of the reply goes sentence by sentence as
usual. A comma followed by a digit ("3,5", "10:30") is not a break.
"""

from collections.abc import AsyncIterator

from pipecat.utils.text.base_text_aggregator import Aggregation, AggregationType
from pipecat.utils.text.simple_text_aggregator import SimpleTextAggregator

CLAUSE_PUNCTUATION = (",", ":", "—", "–")
MIN_WORDS = 3


class FirstClauseAggregator(SimpleTextAggregator):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._first_pending = True
        self._clause_lookahead = False

    async def aggregate(self, text: str) -> AsyncIterator[Aggregation]:
        if self._aggregation_type == AggregationType.TOKEN:
            async for aggregate in super().aggregate(text):
                yield aggregate
            return
        for char in text:
            self._text += char
            clause = self._check_clause(char) if self._first_pending else None
            if clause:
                self._first_pending = False
                yield clause
                continue
            result = await self._check_sentence_with_lookahead(char)
            if result:
                self._first_pending = False
                self._clause_lookahead = False
                yield result

    def _check_clause(self, char: str) -> Aggregation | None:
        if self._clause_lookahead:
            self._clause_lookahead = False
            # "3,5" / "10:30": not a pause.
            if char.isspace():
                head = self._text[:-1].strip(" ")
                if len(head.split()) >= MIN_WORDS:
                    self._text = self._text[-1:]
                    return Aggregation(text=head, type=AggregationType.SENTENCE)
            return None
        if char in CLAUSE_PUNCTUATION:
            self._clause_lookahead = True
        return None

    async def handle_interruption(self):
        await super().handle_interruption()
        self._first_pending = True
        self._clause_lookahead = False

    async def reset(self):
        await super().reset()
        self._first_pending = True
        self._clause_lookahead = False


def use_first_clause(tts) -> bool:
    """Swap the TTS service's sentence aggregator; False when it has none."""
    current = getattr(tts, "_text_aggregator", None)
    if type(current) is not SimpleTextAggregator:
        return False
    tts._text_aggregator = FirstClauseAggregator(aggregation_type=current.aggregation_type)
    return True
