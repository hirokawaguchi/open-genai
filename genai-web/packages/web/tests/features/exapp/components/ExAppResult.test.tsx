import { render } from '@testing-library/react';
import { InvokeExAppResponse } from 'genai-web';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ExAppResult } from '../../../../src/features/exapp/components/ExAppResult.tsx';

vi.mock('../../../../src/features/exapp/stores/useExAppInvokeStore.ts');
vi.mock('../../../../src/features/exapp/components/ContinueConversationButton.tsx', () => ({
  ContinueConversationButton: () => null,
}));

describe('ExAppResult', () => {
  const createMockExAppResponse = (
    overrides?: Partial<InvokeExAppResponse>,
  ): InvokeExAppResponse => ({
    outputs: 'テスト出力結果',
    artifacts: [],
    timestamps: {
      processingStartedAt: '2025-01-01T00:00:00Z',
      processingEndedAt: '2025-01-01T00:00:01Z',
    },
    ...overrides,
  });

  const defaultStoreValue = {
    exAppResponse: null,
    setExAppResponse: vi.fn(),
    requestLoading: false,
    setRequestLoading: vi.fn(),
    error: null,
    setError: vi.fn(),
    shouldReset: false,
    setShouldReset: vi.fn(),
    clear: vi.fn(),
  };

  const mockUseExAppInvokeStore = vi.fn();

  beforeEach(async () => {
    vi.clearAllMocks();

    mockUseExAppInvokeStore.mockReturnValue(defaultStoreValue);

    const module = await import('../../../../src/features/exapp/stores/useExAppInvokeStore.ts');
    vi.mocked(module.useExAppInvokeStore).mockImplementation(mockUseExAppInvokeStore);
  });

  it('renders initial state', () => {
    const { getByText } = render(<ExAppResult shouldShowConversationHistory={false} />);

    expect(getByText('AIアプリのレスポンスは、ここに表示されます')).toBeDefined();
  });

  it('renders loading state', () => {
    mockUseExAppInvokeStore.mockReturnValue({
      ...defaultStoreValue,
      requestLoading: true,
    });

    const { getByRole } = render(<ExAppResult shouldShowConversationHistory={false} />);

    const loadingIcon = getByRole('img', { name: '読み込み中' });
    expect(loadingIcon).toBeDefined();
    expect(loadingIcon.tagName).toEqual('svg');
  });

  it('renders error state', () => {
    mockUseExAppInvokeStore.mockReturnValue({
      ...defaultStoreValue,
      error: 'エラーが発生しました',
    });

    const { getByText } = render(<ExAppResult shouldShowConversationHistory={false} />);

    const error = getByText('エラーが発生しました');
    expect(error).toBeDefined();
    expect(error.tagName).toEqual('P');
  });

  it('renders result without artifacts', () => {
    const mockResponse = createMockExAppResponse();
    mockUseExAppInvokeStore.mockReturnValue({
      ...defaultStoreValue,
      exAppResponse: mockResponse,
    });

    const { getByText } = render(<ExAppResult shouldShowConversationHistory={false} />);

    expect(getByText('テスト出力結果')).toBeDefined();
  });

  it('renders result with artifacts', () => {
    const mockResponse = createMockExAppResponse({
      artifacts: [
        {
          display_name: 'test-image.png',
          content: 'base64encodedstring',
        },
      ],
    });
    mockUseExAppInvokeStore.mockReturnValue({
      ...defaultStoreValue,
      exAppResponse: mockResponse,
    });

    const { getByAltText } = render(<ExAppResult shouldShowConversationHistory={false} />);

    const image = getByAltText('test-image.png');
    expect(image).toBeDefined();
    expect(image.tagName).toEqual('IMG');
  });

  it('renders citation accordion for RAG sources', () => {
    const mockResponse = createMockExAppResponse({
      artifacts: [
        {
          display_name: '[1] sample.pdf（類似度: 0.800）',
          mime_type: 'text/x.open-genai.citation',
          text: 'これはヒットしたチャンク本文です。',
        },
      ],
    });
    mockUseExAppInvokeStore.mockReturnValue({
      ...defaultStoreValue,
      exAppResponse: mockResponse,
    });

    const { getByText } = render(<ExAppResult shouldShowConversationHistory={false} />);

    expect(getByText('[1] sample.pdf（類似度: 0.800）')).toBeDefined();
    expect(getByText('これはヒットしたチャンク本文です。')).toBeDefined();
  });

  it('renders copy button when result exists', () => {
    const mockResponse = createMockExAppResponse();
    mockUseExAppInvokeStore.mockReturnValue({
      ...defaultStoreValue,
      exAppResponse: mockResponse,
    });

    const { getByRole } = render(<ExAppResult shouldShowConversationHistory={false} />);

    const button = getByRole('button', { name: 'コピー' });
    expect(button).toBeDefined();
    expect(button.tagName).toEqual('BUTTON');
  });
});
