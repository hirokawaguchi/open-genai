import { useEffect, useState, type FormEvent } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { BreadcrumbsNav } from '@/components/ui/BreadcrumbsNav';
import { Button } from '@/components/ui/dads/Button';
import { Label } from '@/components/ui/dads/Label';
import { PageTitle } from '@/components/PageTitle';
import { LayoutBody } from '@/layout/LayoutBody';
import type { ChoseiDateInput } from './types';
import { useChoseiActions, useChoseiEvent } from './useChosei';

type DateRow = { id: string; start: string; end: string; allDay: boolean };

const toLocalInput = (iso: string, allDay: boolean): string => {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const pad = (n: number) => String(n).padStart(2, '0');
  if (allDay) {
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  }
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

export const ChoseiEditPage = () => {
  const { eventId } = useParams<{ eventId: string }>();
  const navigate = useNavigate();
  const { detail, isLoading, loadError } = useChoseiEvent(eventId);
  const { update, submitting, error, setError } = useChoseiActions();

  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [creatorName, setCreatorName] = useState('');
  const [eventPassword, setEventPassword] = useState('');
  const [dates, setDates] = useState<DateRow[]>([]);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!detail || ready) return;
    setTitle(detail.event.title);
    setDescription(detail.event.description || '');
    setCreatorName(detail.event.creator_name || '');
    setDates(
      detail.dates.map((d) => ({
        id: String(d.id),
        start: toLocalInput(d.date_time, d.is_all_day),
        end: d.end_time ? toLocalInput(d.end_time, false) : '',
        allDay: d.is_all_day,
      })),
    );
    setReady(true);
  }, [detail, ready]);

  if (isLoading || !ready) {
    return (
      <LayoutBody>
        <PageTitle title='日程調整の編集' />
        <div className='p-8 text-solid-gray-600'>読み込み中...</div>
      </LayoutBody>
    );
  }

  if (loadError || !detail || !eventId) {
    return (
      <LayoutBody>
        <PageTitle title='日程調整の編集' />
        <div className='p-8 text-error-1'>{loadError || 'イベントが見つかりません'}</div>
      </LayoutBody>
    );
  }

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    const normalized: ChoseiDateInput[] = dates
      .filter((d) => d.start)
      .map((d) => ({
        start_time: new Date(d.start).toISOString(),
        end_time: d.end && !d.allDay ? new Date(d.end).toISOString() : null,
        is_all_day: d.allDay,
      }));
    if (!title.trim() || normalized.length === 0) {
      setError('タイトルと日程候補を入力してください。');
      return;
    }
    const updated = await update(eventId, {
      title: title.trim(),
      description: description.trim() || undefined,
      creator_name: creatorName.trim() || undefined,
      event_password: eventPassword.trim() || undefined,
      dates: normalized,
    });
    if (updated) {
      navigate(`/chosei/events/${eventId}`);
    }
  };

  return (
    <LayoutBody>
      <PageTitle title='日程調整の編集' />
      <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-6 p-6 lg:p-8'>
        <BreadcrumbsNav
          items={[
            { label: 'ホーム', to: '/' },
            { label: '日程調整', to: '/chosei' },
            { label: detail.event.title, to: `/chosei/events/${eventId}` },
            { label: '編集' },
          ]}
        />
        <h1 className='text-std-20B-160'>イベントを編集</h1>
        <p className='text-dns-14N-130 text-solid-gray-600'>
          作成者本人以外はイベント暗証番号が必要です。日程を変更すると既存の回答は削除されます。
        </p>
        <form onSubmit={onSubmit} className='flex flex-col gap-4'>
          <div>
            <Label htmlFor='edit-title' size='sm'>
              タイトル
            </Label>
            <input
              id='edit-title'
              className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
            />
          </div>
          <div>
            <Label htmlFor='edit-desc' size='sm'>
              説明
            </Label>
            <textarea
              id='edit-desc'
              className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
              rows={3}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <div className='grid gap-4 md:grid-cols-2'>
            <div>
              <Label htmlFor='edit-creator' size='sm'>
                作成者名
              </Label>
              <input
                id='edit-creator'
                className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                value={creatorName}
                onChange={(e) => setCreatorName(e.target.value)}
              />
            </div>
            <div>
              <Label htmlFor='edit-pin' size='sm'>
                イベント暗証番号（作成者以外）
              </Label>
              <input
                id='edit-pin'
                className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                inputMode='numeric'
                maxLength={4}
                value={eventPassword}
                onChange={(e) => setEventPassword(e.target.value)}
              />
            </div>
          </div>
          <div className='flex flex-col gap-3'>
            <Label size='sm'>日程候補</Label>
            {dates.map((d) => (
              <div
                key={d.id}
                className='flex flex-col gap-2 rounded-8 border border-solid-gray-300 p-3 md:flex-row md:items-end'
              >
                <div className='flex-1'>
                  <input
                    type={d.allDay ? 'date' : 'datetime-local'}
                    className='w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                    value={d.start}
                    onChange={(e) =>
                      setDates((prev) =>
                        prev.map((x) => (x.id === d.id ? { ...x, start: e.target.value } : x)),
                      )
                    }
                  />
                </div>
                {!d.allDay && (
                  <div className='flex-1'>
                    <input
                      type='datetime-local'
                      className='w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                      value={d.end}
                      onChange={(e) =>
                        setDates((prev) =>
                          prev.map((x) => (x.id === d.id ? { ...x, end: e.target.value } : x)),
                        )
                      }
                    />
                  </div>
                )}
                <label className='flex items-center gap-2 text-std-14N-160'>
                  <input
                    type='checkbox'
                    checked={d.allDay}
                    onChange={(e) =>
                      setDates((prev) =>
                        prev.map((x) =>
                          x.id === d.id ? { ...x, allDay: e.target.checked } : x,
                        ),
                      )
                    }
                  />
                  終日
                </label>
              </div>
            ))}
            <Button
              type='button'
              variant='outline'
              size='sm'
              onClick={() =>
                setDates((p) => [
                  ...p,
                  { id: crypto.randomUUID(), start: '', end: '', allDay: false },
                ])
              }
            >
              日程を追加
            </Button>
          </div>
          {error && (
            <p className='text-error-1' role='alert'>
              {error}
            </p>
          )}
          <div className='flex flex-wrap gap-3'>
            <Button type='submit' variant='solid-fill' size='md' aria-disabled={submitting}>
              {submitting ? '保存中...' : '保存する'}
            </Button>
            <Link to={`/chosei/events/${eventId}`}>
              <Button type='button' variant='text' size='md'>
                キャンセル
              </Button>
            </Link>
          </div>
        </form>
      </div>
    </LayoutBody>
  );
};
