import { render, within } from '@testing-library/react';
import { InvokeExAppHistory } from 'genai-web';
import { MemoryRouter } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ExAppInvokedHistoryItem } from '../../../../src/features/exapp/components/ExAppInvokedHistoryItem';

vi.mock('@/utils/formatDateTime', () => ({
  formatDateTime: () => '2025年1月1日 9:00',
}));

describe('ExAppInvokedHistoryItem', () => {
  const mockOnReload = vi.fn();
  const mockOnDeleted = vi.fn();

  const mockHistory: InvokeExAppHistory = {
    teamId: 'team1',
    teamName: 'テストチーム1',
    exAppId: 'app1',
    exAppName: 'テストアプリ1',
    userId: 'user1',
    createdDate: '1735689600000', // 2025-01-01T00:00:00.000Z
    inputs: {
      input1: 'テスト用の入力内容',
    },
    outputs: 'テスト用の出力内容',
    status: 'COMPLETED',
    progress: '完了',
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  const renderComponent = (
    props: Partial<React.ComponentProps<typeof ExAppInvokedHistoryItem>> = {},
  ) => {
    return render(
      <MemoryRouter>
        <ExAppInvokedHistoryItem
          history={mockHistory}
          shouldShowConversationHistory={false}
          isReloading={false}
          onReload={mockOnReload}
          onDeleted={mockOnDeleted}
          {...props}
        />
      </MemoryRouter>,
    );
  };

  it('renders history time correctly', () => {
    const { getByRole } = renderComponent();

    const heading = getByRole('heading', { level: 3 });
    expect(heading).toBeDefined();
    expect(within(heading).getByText('2025年1月1日 9:00')).toBeDefined();

    const timeElement = heading.querySelector('time');
    expect(timeElement).toBeDefined();
    expect(timeElement?.getAttribute('datetime')).toEqual('2025-01-01T00:00:00.000Z');
  });

  it('renders COMPLETED history item correctly', () => {
    const { getByText, getByRole } = renderComponent();

    const heading = getByRole('heading', { level: 3 });
    expect(within(heading).getByText('完了')).toBeDefined();

    expect(getByText('input1: テスト用の入力内容')).toBeDefined();
    expect(getByText('テスト用の出力内容')).toBeDefined();
  });

  it('renders ACCEPTED history item correctly', () => {
    const { getByText, getByRole } = renderComponent({
      history: { ...mockHistory, status: 'ACCEPTED' },
    });

    const heading = getByRole('heading', { level: 3 });
    expect(within(heading).getByText('受付済')).toBeDefined();

    const message = getByText('処理を受け付けました。しばらくお待ちください。');
    expect(message).toBeDefined();
    expect(message.tagName).toEqual('P');

    const reloadButton = getByRole('button', { name: '状態を更新' });
    expect(reloadButton).toBeDefined();
    expect(reloadButton.tagName).toEqual('BUTTON');
  });

  it('renders IN_PROGRESS history item correctly', () => {
    const { getByText, getByRole } = renderComponent({
      history: { ...mockHistory, status: 'IN_PROGRESS', progress: '処理中です。' },
    });

    const heading = getByRole('heading', { level: 3 });
    expect(within(heading).getByText('処理中')).toBeDefined();

    const message = getByText('処理中です。');
    expect(message).toBeDefined();
    expect(message.tagName).toEqual('P');

    const reloadButton = getByRole('button', { name: '状態を更新' });
    expect(reloadButton).toBeDefined();
    expect(reloadButton.tagName).toEqual('BUTTON');
  });

  it('renders ERROR history item with fallback message when outputs is empty', () => {
    const { getByText, getByRole } = renderComponent({
      history: { ...mockHistory, status: 'ERROR', outputs: '' },
    });

    const heading = getByRole('heading', { level: 3 });
    expect(within(heading).getByText('エラー')).toBeDefined();

    const message = getByText('実行中にエラーが発生しました。再度お試しください。');
    expect(message).toBeDefined();
    expect(message.tagName).toEqual('P');
  });

  it('renders ERROR history item with user-facing outputs message', () => {
    const userMessage =
      '現在リクエストが集中しています。しばらく時間をおいてから再度お試しください。';
    const { getByText, getByRole } = renderComponent({
      history: { ...mockHistory, status: 'ERROR', outputs: userMessage },
    });

    const heading = getByRole('heading', { level: 3 });
    expect(within(heading).getByText('エラー')).toBeDefined();

    const message = getByText(userMessage);
    expect(message).toBeDefined();
    expect(message.tagName).toEqual('P');
  });

  it('renders continue conversation button when shouldShowConversationHistory is true and status is not COMPLETED', () => {
    const { getByRole } = renderComponent({
      shouldShowConversationHistory: true,
    });

    const continueButton = getByRole('button', { name: '会話を続ける' });
    expect(continueButton).toBeDefined();
    expect(continueButton.tagName).toEqual('BUTTON');
  });

  it('does not render continue conversation button when shouldShowConversationHistory is true and status is not COMPLETED', () => {
    const { queryByRole } = renderComponent({
      shouldShowConversationHistory: true,
      history: { ...mockHistory, status: 'IN_PROGRESS' },
    });

    const continueButton = queryByRole('button', { name: '会話を続ける' });
    expect(continueButton).toBeNull();
  });

  it('renders delete button correctly', () => {
    const { getByRole } = renderComponent();

    const deleteButton = getByRole('button', { name: '履歴を削除' });
    expect(deleteButton).toBeDefined();
    expect(deleteButton.tagName).toEqual('BUTTON');
  });

  it('renders download buttons when artifacts exist', () => {
    const { getByText, getByRole } = renderComponent({
      history: {
        ...mockHistory,
        artifacts: [
          { file_url: 's3://bucket/file1.png', display_name: 'file1.png' },
          { file_url: 's3://bucket/file2.pdf', display_name: 'file2.pdf' },
        ],
      },
    });

    expect(getByText('ファイル一覧:')).toBeDefined();
    expect(getByRole('button', { name: 'file1.pngをダウンロード' })).toBeDefined();
    expect(getByRole('button', { name: 'file2.pdfをダウンロード' })).toBeDefined();
  });
});
