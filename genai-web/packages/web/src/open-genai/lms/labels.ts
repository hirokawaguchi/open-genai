export const fieldClass = 'mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2 text-std-16N-170';

export const stateLabel = (state: string): string =>
  ({ not_started: '未着手', in_progress: '受講中', completed: '修了' })[state] ?? state;

export const statusLabel = (status: string): string =>
  ({
    draft: '下書き',
    published: '公開',
    'not attempted': '未着手',
    incomplete: '途中',
    completed: '完了',
    passed: '合格',
    failed: '不合格',
  })[status] ?? status;

export const transcriptStatusLabel = (status: string): string =>
  ({ none: '未作成', running: '作成中', draft: '下書き', confirmed: '確定', failed: '失敗' })[status] ?? status;
