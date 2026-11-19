export type LiveTurn = { id: string; text: string };

export const applyLiveMessage = (
  turns: LiveTurn[],
  message: { type?: string; itemId?: string; text?: string },
): LiveTurn[] => {
  if ((message.type !== 'delta' && message.type !== 'transcript') || !message.itemId) {
    return turns;
  }
  const text = message.text ?? '';
  const index = turns.findIndex((turn) => turn.id === message.itemId);
  if (index === -1) {
    return [...turns, { id: message.itemId, text }];
  }
  const next = turns.slice();
  next[index] = { id: message.itemId, text };
  return next;
};

export const liveTranscript = (turns: LiveTurn[]): string =>
  turns
    .map((turn) => turn.text.trim())
    .filter(Boolean)
    .join('\n');
