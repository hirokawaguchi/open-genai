import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router';
import { PiBookOpenBold, PiCalendarBlankBold } from 'react-icons/pi';
import { BreadcrumbsNav } from '@/components/ui/BreadcrumbsNav';
import { Button } from '@/components/ui/dads/Button';
import { Disclosure, DisclosureSummary } from '@/components/ui/dads/Disclosure';
import { Label } from '@/components/ui/dads/Label';
import { PageTitle } from '@/components/PageTitle';
import { LayoutBody } from '@/layout/LayoutBody';
import { toLocalInputValue } from './format';
import type { ChoseiDateInput } from './types';
import {
  useChoseiActions,
  useChoseiAssist,
  useChoseiConfig,
  useChoseiEvents,
} from './useChosei';

type DateRow = { id: string; start: string; end: string; allDay: boolean };

const newRow = (): DateRow => ({
  id: crypto.randomUUID(),
  start: '',
  end: '',
  allDay: false,
});

/**
 * 日程調整専用ページ（OpenGENAI 拡張）。
 * Compose profiles: ["chosei"] 未起動時は有効化手順を案内する。
 */
export const ChoseiPage = () => {
  const navigate = useNavigate();
  const { config, isLoading: configLoading, unavailable } = useChoseiConfig();
  const { events, isLoading, loadError, mutate } = useChoseiEvents();
  const { create, submitting, error, setError } = useChoseiActions();
  const {
    parseDates,
    busy: assistBusy,
    error: assistError,
    setError: setAssistError,
  } = useChoseiAssist();

  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [creatorName, setCreatorName] = useState('');
  const [eventPassword, setEventPassword] = useState('');
  const [dates, setDates] = useState<DateRow[]>([newRow()]);
  const [nlText, setNlText] = useState('');
  const [nlNotes, setNlNotes] = useState<string | null>(null);

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
    const detail = await create({
      title: title.trim(),
      description: description.trim() || undefined,
      creator_name: creatorName.trim() || undefined,
      event_password: eventPassword.trim() || undefined,
      dates: normalized,
    });
    if (detail) {
      await mutate();
      navigate(`/chosei/events/${detail.event.id}`);
    }
  };

  return (
    <LayoutBody>
      <PageTitle title='日程調整' />
      <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-6 p-6 lg:p-8'>
        <div className='flex flex-col gap-4'>
          <BreadcrumbsNav
            items={[
              { label: 'ホーム', to: '/' },
              { label: 'AIアプリ', to: '/apps' },
              { label: '日程調整' },
            ]}
          />
          <h1 className='text-std-20B-160 lg:text-std-24B-150'>日程調整</h1>
          <p className='text-std-16N-170 text-solid-gray-700'>
            庁内利用者と外部参加者の日程を調整します。外部には別 URL（公開エンドポイント）で回答してもらえます。
          </p>
          <Disclosure className='rounded-8 border border-solid-gray-420 bg-solid-gray-50 px-4 py-3'>
            <DisclosureSummary>
              <span className='flex items-center text-std-16B-150'>
                <PiBookOpenBold className='mr-2 size-5 flex-none' />
                使い方（クリックで開閉）
              </span>
            </DisclosureSummary>
            <div className='mt-3 flex flex-col gap-1.5 text-std-16N-170 text-solid-gray-700'>
              <p>・イベントを作成すると庁内用ページと外部共有 URL が発行されます。</p>
              <p>・外部 URL は LGWAN から届かない場合、リンクファイルを持ち出して別端末で開いてください。</p>
              <p>
                ・有効化: <code>docker compose --profile chosei up -d</code> または{' '}
                <code>COMPOSE_PROFILES=chosei</code>
              </p>
              {config?.retention_days != null && (
                <p>・作成から {config.retention_days} 日経過したイベントは自動削除されます。</p>
              )}
            </div>
          </Disclosure>
        </div>

        {(unavailable || (!configLoading && config?.enabled === false)) && (
          <div
            className='rounded-8 border border-solid-gray-420 bg-solid-gray-50 px-4 py-4 text-std-16N-170'
            role='status'
          >
            <p className='text-std-16B-150 text-solid-gray-900'>日程調整は現在有効化されていません</p>
            <p className='mt-2 text-solid-gray-700'>
              {config?.error ||
                'コンテナを profiles: ["chosei"] で起動してください。'}
            </p>
            <pre className='mt-3 overflow-x-auto rounded-4 bg-white p-3 text-dns-14N-130 text-solid-gray-800'>
              docker compose --profile chosei up -d{'\n'}
              # または .env に COMPOSE_PROFILES=chosei
            </pre>
          </div>
        )}

        {!unavailable && (
          <>
            <section className='flex flex-col gap-4'>
              <h2 className='flex items-center gap-2 text-std-18B-160'>
                <PiCalendarBlankBold className='size-5' />
                新しいイベント
              </h2>
              <form onSubmit={onSubmit} className='flex flex-col gap-4'>
                <div>
                  <Label htmlFor='chosei-title' size='sm'>
                    タイトル
                  </Label>
                  <input
                    id='chosei-title'
                    className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2 text-std-16N-170'
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    required
                  />
                </div>
                <div>
                  <Label htmlFor='chosei-desc' size='sm'>
                    説明（任意）
                  </Label>
                  <textarea
                    id='chosei-desc'
                    className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2 text-std-16N-170'
                    rows={3}
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                  />
                </div>
                <div className='grid gap-4 md:grid-cols-2'>
                  <div>
                    <Label htmlFor='chosei-creator' size='sm'>
                      作成者名（任意）
                    </Label>
                    <input
                      id='chosei-creator'
                      className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2 text-std-16N-170'
                      value={creatorName}
                      onChange={(e) => setCreatorName(e.target.value)}
                    />
                  </div>
                  <div>
                    <Label htmlFor='chosei-pin' size='sm'>
                      イベント暗証番号（4桁・任意）
                    </Label>
                    <input
                      id='chosei-pin'
                      className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2 text-std-16N-170'
                      inputMode='numeric'
                      maxLength={4}
                      value={eventPassword}
                      onChange={(e) => setEventPassword(e.target.value)}
                      placeholder='作成者以外が編集するときに使用'
                    />
                  </div>
                </div>

                <div className='flex flex-col gap-2 rounded-8 border border-solid-gray-300 bg-solid-gray-50 p-4'>
                  <Label htmlFor='chosei-nl' size='sm'>
                    自然文から日程候補を作成（LLM）
                  </Label>
                  <textarea
                    id='chosei-nl'
                    className='w-full rounded-4 border border-solid-gray-420 bg-white px-3 py-2 text-std-16N-170'
                    rows={2}
                    value={nlText}
                    onChange={(e) => setNlText(e.target.value)}
                    placeholder='例: 来週の火・水・木の午後2時から1時間ずつ'
                  />
                  <p className='text-dns-14N-130 text-solid-gray-600'>
                    モデル: {config?.llm?.model || '（未設定）'}。生成後に下の候補を確認・編集できます。
                  </p>
                  {(assistError || nlNotes) && (
                    <p
                      className={
                        assistError ? 'text-dns-14N-130 text-error-1' : 'text-dns-14N-130 text-solid-gray-700'
                      }
                      role={assistError ? 'alert' : undefined}
                    >
                      {assistError || nlNotes}
                    </p>
                  )}
                  <div>
                    <Button
                      type='button'
                      variant='outline'
                      size='sm'
                      aria-disabled={assistBusy || !nlText.trim()}
                      onClick={async () => {
                        setAssistError(null);
                        setNlNotes(null);
                        const res = await parseDates(nlText.trim());
                        if (!res) return;
                        if (!res.dates.length) {
                          setNlNotes(res.notes || '候補を抽出できませんでした。');
                          return;
                        }
                        setDates(
                          res.dates.map((d) => ({
                            id: crypto.randomUUID(),
                            start: toLocalInputValue(d.start_time, !!d.is_all_day),
                            end:
                              d.end_time && !d.is_all_day
                                ? toLocalInputValue(d.end_time, false)
                                : '',
                            allDay: !!d.is_all_day,
                          })),
                        );
                        setNlNotes(res.notes || `${res.dates.length}件の候補を反映しました。`);
                      }}
                    >
                      {assistBusy ? '解釈中...' : '日程候補に反映'}
                    </Button>
                  </div>
                </div>

                <div className='flex flex-col gap-3'>
                  <Label size='sm'>日程候補</Label>
                  {dates.map((d, idx) => (
                    <div
                      key={d.id}
                      className='flex flex-col gap-2 rounded-8 border border-solid-gray-300 p-3 md:flex-row md:items-end'
                    >
                      <div className='flex-1'>
                        <Label htmlFor={`start-${d.id}`} size='sm'>
                          開始
                        </Label>
                        <input
                          id={`start-${d.id}`}
                          type={d.allDay ? 'date' : 'datetime-local'}
                          className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                          value={d.start}
                          onChange={(e) =>
                            setDates((prev) =>
                              prev.map((x) =>
                                x.id === d.id ? { ...x, start: e.target.value } : x,
                              ),
                            )
                          }
                        />
                      </div>
                      {!d.allDay && (
                        <div className='flex-1'>
                          <Label htmlFor={`end-${d.id}`} size='sm'>
                            終了（任意）
                          </Label>
                          <input
                            id={`end-${d.id}`}
                            type='datetime-local'
                            className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                            value={d.end}
                            onChange={(e) =>
                              setDates((prev) =>
                                prev.map((x) =>
                                  x.id === d.id ? { ...x, end: e.target.value } : x,
                                ),
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
                      {dates.length > 1 && (
                        <Button
                          type='button'
                          variant='text'
                          size='sm'
                          onClick={() => setDates((prev) => prev.filter((x) => x.id !== d.id))}
                        >
                          削除
                        </Button>
                      )}
                      <span className='sr-only'>候補 {idx + 1}</span>
                    </div>
                  ))}
                  <Button type='button' variant='outline' size='sm' onClick={() => setDates((p) => [...p, newRow()])}>
                    日程を追加
                  </Button>
                </div>

                {error && (
                  <p className='text-dns-16N-130 text-error-1' role='alert'>
                    {error}
                  </p>
                )}
                <div>
                  <Button type='submit' variant='solid-fill' size='md' aria-disabled={submitting}>
                    {submitting ? '作成中...' : '日程調整を作成'}
                  </Button>
                </div>
              </form>
            </section>

            <section className='flex flex-col gap-3'>
              <h2 className='text-std-18B-160'>自分のイベント</h2>
              {isLoading ? (
                <p className='text-solid-gray-600'>読み込み中...</p>
              ) : loadError ? (
                <p className='text-error-1' role='alert'>
                  {loadError}
                </p>
              ) : events.length === 0 ? (
                <p className='text-solid-gray-600'>まだイベントがありません。</p>
              ) : (
                <ul className='divide-y divide-solid-gray-300 border-y border-solid-gray-300'>
                  {events.map((ev) => (
                    <li key={ev.id} className='py-3'>
                      <Link
                        to={`/chosei/events/${ev.id}`}
                        className='text-std-16B-150 text-blue-900 underline-offset-2 hover:underline'
                      >
                        {ev.title}
                      </Link>
                      <p className='text-dns-14N-130 text-solid-gray-600'>
                        {new Date(ev.created_at).toLocaleString('ja-JP')}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </>
        )}
      </div>
    </LayoutBody>
  );
};
