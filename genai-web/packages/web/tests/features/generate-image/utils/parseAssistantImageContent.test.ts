import { describe, expect, it } from 'vitest';
import {
  fallbackAssistantImageContent,
  parseAssistantImageContent,
  resolveAssistantImageContent,
} from '../../../../src/features/generate-image/utils/parseAssistantImageContent';

describe('parseAssistantImageContent', () => {
  it('JSON をそのまま読む', () => {
    const parsed = parseAssistantImageContent(
      JSON.stringify({
        prompt: 'shiba inu, grassy field',
        negativePrompt: 'blurry',
        comment: 'ok',
        recommendedStylePreset: ['photographic'],
      }),
    );
    expect(parsed.prompt).toBe('shiba inu, grassy field');
    expect(parsed.recommendedStylePreset).toEqual(['photographic']);
  });

  it('会話文に埋もれた JSON と string の preset を許容する', () => {
    const parsed = parseAssistantImageContent(
      'はい、どうぞ\n```json\n{"prompt":"a","negativePrompt":"b","comment":"c","recommendedStylePreset":"photographic"}\n```',
    );
    expect(parsed.prompt).toBe('a');
    expect(parsed.recommendedStylePreset).toEqual(['photographic']);
  });

  it('JSON が無いと例外', () => {
    expect(() => parseAssistantImageContent('柴犬が草原で走っています')).toThrow('JSON not found');
  });
});

describe('resolveAssistantImageContent', () => {
  it('会話文ならユーザー入力からフォールバックする', () => {
    const resolved = resolveAssistantImageContent(
      '柴犬が広々とした草原で元気よく走り回っている様子は、とても癒やされますね！',
      '柴犬が草原で楽しそうに走り回っている',
    );
    expect(resolved.prompt).toContain('柴犬が草原で楽しそうに走り回っている');
    expect(resolved.negativePrompt).toContain('blurry');
    expect(resolved.recommendedStylePreset).toContain('photographic');
  });

  it('空プロンプトもフォールバックする', () => {
    const resolved = resolveAssistantImageContent(
      '{"prompt":"","negativePrompt":"x","comment":"","recommendedStylePreset":[]}',
      '猫',
    );
    expect(resolved.prompt).toContain('猫');
  });
});

describe('fallbackAssistantImageContent', () => {
  it('ユーザー文が空でも品質語だけ返す', () => {
    const fallback = fallbackAssistantImageContent('   ');
    expect(fallback.prompt).toBe('photorealistic, high quality, natural light');
  });
});
