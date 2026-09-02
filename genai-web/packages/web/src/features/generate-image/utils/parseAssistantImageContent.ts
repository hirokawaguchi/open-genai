export type AssistantImageContent = {
  prompt: string | null;
  negativePrompt: string | null;
  comment: string;
  recommendedStylePreset: string[];
  error?: boolean;
};

const DEFAULT_NEGATIVE_PROMPT =
  'worst quality, low quality, blurry, deformed, text, watermark';

const asString = (value: unknown): string | null => {
  if (typeof value === 'string') {
    return value;
  }
  if (value == null) {
    return null;
  }
  return String(value);
};

const asStringArray = (value: unknown): string[] => {
  if (Array.isArray(value)) {
    return value.filter((item): item is string => typeof item === 'string' && item.length > 0);
  }
  if (typeof value === 'string' && value.trim()) {
    return [value.trim()];
  }
  return [];
};

export const parseAssistantImageContent = (content: string): AssistantImageContent => {
  const fenced = content.match(/```(?:json)?\s*([\s\S]*?)```/i);
  const candidate = (fenced ? fenced[1] : content).trim();
  const start = candidate.indexOf('{');
  const end = candidate.lastIndexOf('}');
  if (start < 0 || end <= start) {
    throw new Error('JSON not found');
  }
  const parsed = JSON.parse(candidate.slice(start, end + 1)) as Record<string, unknown>;
  return {
    prompt: asString(parsed.prompt),
    negativePrompt: asString(parsed.negativePrompt),
    comment: asString(parsed.comment) ?? '',
    recommendedStylePreset: asStringArray(parsed.recommendedStylePreset),
  };
};

/** LLM が会話文を返したときでも画像生成を止めない。 */
export const fallbackAssistantImageContent = (userText: string): AssistantImageContent => {
  const subject = userText.trim();
  const prompt = subject
    ? `${subject}, photorealistic, high quality, natural light`
    : 'photorealistic, high quality, natural light';
  return {
    prompt,
    negativePrompt: DEFAULT_NEGATIVE_PROMPT,
    comment:
      '画像を生成しました。続けて会話することで、画像を理想に近づけていくことができます。以下が改善案です。\n1. 被写体の表情や動作をより具体的に指定してみてください。\n2. 時間帯や天候を指定してみてください。\n3. 構図（寄り／引き）を指定してみてください。',
    recommendedStylePreset: ['photographic', 'cinematic', 'analog-film'],
  };
};

export const resolveAssistantImageContent = (
  content: string,
  userText: string,
): AssistantImageContent => {
  try {
    const parsed = parseAssistantImageContent(content);
    if (!parsed.prompt) {
      return fallbackAssistantImageContent(userText);
    }
    return {
      ...parsed,
      negativePrompt: parsed.negativePrompt ?? DEFAULT_NEGATIVE_PROMPT,
    };
  } catch {
    return fallbackAssistantImageContent(userText);
  }
};
