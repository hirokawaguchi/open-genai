/** ISO → datetime-local / date 入力用 */
export const toLocalInputValue = (iso: string, allDay: boolean): string => {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const pad = (n: number) => String(n).padStart(2, '0');
  if (allDay) {
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  }
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

export const formatDateTime = (
  iso: string,
  end?: string | null,
  allDay?: boolean,
): string => {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    if (allDay) {
      return d.toLocaleDateString('ja-JP', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        weekday: 'short',
      });
    }
    let s = d.toLocaleString('ja-JP', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      weekday: 'short',
      hour: '2-digit',
      minute: '2-digit',
    });
    if (end) {
      const e = new Date(end);
      if (!Number.isNaN(e.getTime())) {
        s += ` 〜 ${e.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' })}`;
      }
    }
    return s;
  } catch {
    return iso;
  }
};

export const STATUS_LABEL = {
  ok: '参加可',
  maybe: '検討中',
  ng: '不可',
} as const;

/** 調整さん風の記号表示 */
export const STATUS_MARK = {
  ok: '○',
  maybe: '△',
  ng: '×',
} as const;
