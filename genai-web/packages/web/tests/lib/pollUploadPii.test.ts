import { pollUploadPii } from '@/lib/fileApi';

describe('pollUploadPii', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('returns the name-detection result once it is ready', async () => {
    const body = {
      ready: true,
      warned: true,
      categories: ['氏名'],
      hits: [],
      message: '氏名の可能性があります',
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => body,
    });
    vi.stubGlobal('fetch', fetchMock);

    const res = await pollUploadPii('/api/files-pii/uuid/a.txt?exp=1&sig=ab', {
      attempts: 3,
      intervalMs: 1,
    });

    expect(res).toEqual(body);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('gives up and returns null when it never becomes ready', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ready: false }),
    });
    vi.stubGlobal('fetch', fetchMock);

    const res = await pollUploadPii('/api/files-pii/uuid/a.txt?exp=1&sig=ab', {
      attempts: 2,
      intervalMs: 1,
    });

    expect(res).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
