import { describe, expect, it } from 'vitest';
import { fileObjectKeyFromUrl } from '@/lib/fileUrl';

describe('fileObjectKeyFromUrl', () => {
  it('strips /api prefix from Open GENAI upload URLs', () => {
    expect(
      fileObjectKeyFromUrl(
        'https://paris.example.jp/api/files/84c61db9-bb82-4fc2-9102-eef0e4e65789/image.png',
      ),
    ).toBe('84c61db9-bb82-4fc2-9102-eef0e4e65789/image.png');
  });

  it('handles /files without /api', () => {
    expect(fileObjectKeyFromUrl('https://example.com/files/uuid/a.wav')).toBe('uuid/a.wav');
  });

  it('ignores query string', () => {
    expect(
      fileObjectKeyFromUrl('https://example.com/api/files/uuid/a.txt?X-Amz-Signature=1'),
    ).toBe('uuid/a.txt');
  });

  it('returns undefined for invalid URL', () => {
    expect(fileObjectKeyFromUrl('not-a-url')).toBeUndefined();
  });
});
