import { render } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { InvokeExAppHistory } from 'genai-web';
import { describe, expect, it, vi } from 'vitest';
import { ExAppConversationList } from '../../../../src/features/exapp/components/ExAppConversationList';
import { ExAppConversation } from '../../../../src/features/exapp/hooks/useExAppConversations';

vi.mock('@/utils/formatDateTime', () => ({
  formatDateTime: () => '2026年9月1日 8:33',
}));

vi.mock('../../../../src/features/exapp/hooks/useDeleteExAppInvokeHistory.ts', () => ({
  useDeleteExAppInvokeHistory: () => ({
    deleteHistory: vi.fn(),
    deleteConversation: vi.fn(),
  }),
}));

const history: InvokeExAppHistory = {
  teamId: 'team-1',
  teamName: '共通',
  exAppId: 'app-1',
  exAppName: 'テストアプリ',
  userId: 'admin',
  inputs: { query: '一般職員はグリーン車は使えるの？' },
  outputs: '回答',
  createdDate: '1756683180000',
  status: 'COMPLETED',
  progress: '',
  sessionId: 'session-1',
};

const conversation: ExAppConversation = {
  sessionId: 'session-1',
  title: '一般職員はグリーン車は使えるの？',
  updatedAt: '1756683180000',
  turnCount: 1,
  histories: [history],
};

describe('ExAppConversationList', () => {
  it('shows a delete button for each conversation', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    const onDeleted = vi.fn();
    const { getByText, getByLabelText, getByRole } = render(
      <ExAppConversationList
        conversations={[conversation]}
        activeSessionId=''
        teamId='team-1'
        exAppId='app-1'
        onSelect={onSelect}
        onDeleted={onDeleted}
      />,
    );

    await user.click(getByText('過去の会話（1）'));

    expect(getByText('一般職員はグリーン車は使えるの？')).toBeDefined();
    expect(getByLabelText('会話「一般職員はグリーン車は使えるの？」を削除')).toBeDefined();
    expect(onSelect).not.toHaveBeenCalled();

    await user.click(getByLabelText('会話「一般職員はグリーン車は使えるの？」を削除'));

    expect(onSelect).not.toHaveBeenCalled();
    expect(getByRole('heading', { name: '会話の削除' })).toBeDefined();
    expect(onDeleted).not.toHaveBeenCalled();
  });
});
