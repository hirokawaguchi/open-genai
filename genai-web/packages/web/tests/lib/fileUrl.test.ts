import { describe, expect, it } from 'vitest';
import { fileObjectKeyFromUrl, pageFileUrl } from '@/lib/fileUrl';

describe('fileObjectKeyFromUrl', () => {
  it('strips /api prefix from Open GENAI upload URLs', () => {
    expect(
      fileObjectKeyFromUrl(
        'https://example.jp/api/files/84c61db9-bb82-4fc2-9102-eef0e4e65789/image.png',
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

  it('reads a relative /api/files path', () => {
    expect(fileObjectKeyFromUrl('/api/files/uuid/a.png?exp=1&sig=ab')).toBe('uuid/a.png');
  });
});

describe('pageFileUrl', () => {
  it('drops the host from an absolute files URL', () => {
    expect(
      pageFileUrl('https://example.jp/api/files/image-gen/a.png?exp=1&sig=ab'),
    ).toBe('/api/files/image-gen/a.png?exp=1&sig=ab');
  });

  it('keeps a path and a data URL', () => {
    expect(pageFileUrl('/api/files/image-gen/a.png?exp=1')).toBe(
      '/api/files/image-gen/a.png?exp=1',
    );
    expect(pageFileUrl('data:image/png;base64,abc')).toBe('data:image/png;base64,abc');
  });
});
