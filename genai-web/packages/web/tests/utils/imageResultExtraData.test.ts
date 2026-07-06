import type { ExtraData } from 'genai-web';
import { describe, expect, it } from 'vitest';
import {
  findLatestImageResultMessage,
  IMAGE_RESULT_EXTRA_NAME,
  parseImageResultExtraData,
} from '@/features/generate-image/utils/imageResultExtraData';

const sampleExtra: ExtraData[] = [
  {
    type: 'json',
    name: IMAGE_RESULT_EXTRA_NAME,
    source: {
      type: 'json',
      mediaType: 'application/json',
      data: JSON.stringify({
        version: 1,
        prompt: 'a cat',
        negativePrompt: 'blur',
        stylePreset: 'photo',
        seeds: [1, -1, -1],
        step: 20,
        cfgScale: 7,
        imageSample: 1,
        images: [{ fileUrl: 'http://localhost/api/files/test.png' }],
      }),
    },
  },
];

describe('imageResultExtraData', () => {
  it('parseImageResultExtraData は保存済み JSON を復元する', () => {
    const parsed = parseImageResultExtraData(sampleExtra);
    expect(parsed?.prompt).toBe('a cat');
    expect(parsed?.images).toHaveLength(1);
  });

  it('findLatestImageResultMessage は最後の assistant を返す', () => {
    const found = findLatestImageResultMessage([
      { role: 'user', content: 'hello' },
      { role: 'assistant', content: '{}', messageId: 'm1', extraData: sampleExtra },
      { role: 'user', content: 'more' },
      {
        role: 'assistant',
        content: '{}',
        messageId: 'm2',
        extraData: [
          {
            type: 'json',
            name: IMAGE_RESULT_EXTRA_NAME,
            source: {
              type: 'json',
              mediaType: 'application/json',
              data: JSON.stringify({
                version: 1,
                prompt: 'newest',
                negativePrompt: '',
                stylePreset: '',
                seeds: [2],
                step: 10,
                cfgScale: 5,
                imageSample: 1,
                images: [{ fileUrl: 'http://localhost/api/files/new.png' }],
              }),
            },
          },
        ],
      },
    ]);
    expect(found?.messageId).toBe('m2');
    expect(found?.result.prompt).toBe('newest');
  });
});
