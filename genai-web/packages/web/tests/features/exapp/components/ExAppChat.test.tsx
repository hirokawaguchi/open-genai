import { render } from '@testing-library/react';
import { ExApp } from 'genai-web';
import { describe, expect, it, vi } from 'vitest';
import { ExAppChat } from '../../../../src/features/exapp/components/ExAppChat';

// invoke フックは fetcher に依存するため、描画テストではスタブ化する
vi.mock('../../../../src/features/exapp/hooks/useInvokeExApp.ts', () => ({
  useInvokeExApp: () => ({ invokeExApp: vi.fn(), invokeExAppStream: vi.fn() }),
}));

// 過去の会話一覧も fetcher に依存するため、描画テストではスタブ化する
vi.mock('../../../../src/features/exapp/hooks/useExAppConversations.ts', () => ({
  useExAppConversations: () => ({ conversations: [], mutate: vi.fn() }),
}));

describe('ExAppChat file attach button', () => {
  const mockExApp: ExApp = {
    teamId: 'team-123',
    exAppId: 'app-123',
    exAppName: 'テストチャット',
    endpoint: 'https://example.com/invoke',
    placeholder: '{}',
    description: '',
    howToUse: '',
    apiKey: 'test-api-key',
    createdDate: '2025-01-01',
    updatedDate: '2025-01-01',
  };

  it('hides the attach button when fileAttachEnabled is false', () => {
    const { queryByText, getByText } = render(
      <ExAppChat exApp={mockExApp} fileAttachEnabled={false} />,
    );

    expect(queryByText('ファイルを添付')).toBeNull();
    // 「新しい会話」は常に表示される（無効化されるのは添付だけ）
    expect(getByText('新しい会話')).toBeDefined();
  });

  it('hides the attach button by default (prop omitted)', () => {
    const { queryByText } = render(<ExAppChat exApp={mockExApp} />);

    expect(queryByText('ファイルを添付')).toBeNull();
  });

  it('shows the attach button when fileAttachEnabled is true', () => {
    const { getByText } = render(<ExAppChat exApp={mockExApp} fileAttachEnabled />);

    expect(getByText('ファイルを添付')).toBeDefined();
  });
});
