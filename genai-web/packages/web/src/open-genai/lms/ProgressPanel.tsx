import { useState } from 'react';
import { Button } from '@/components/ui/dads/Button';
import { teamApi } from '@/lib/fetcher';
import { fieldClass, stateLabel, statusLabel } from './labels';
import type { CourseSummary } from './types';
import { useLmsActions, useLmsProgress } from './useLms';

type Props = {
  courses: CourseSummary[];
  courseId: string | null;
  canGrade: boolean;
  onSelect: (courseId: string) => void;
};

export const ProgressPanel = ({ courses, courseId, canGrade, onSelect }: Props) => {
  const { progress, mutate } = useLmsProgress(courseId);
  const actions = useLmsActions();
  const [score, setScore] = useState('');

  const download = async () => {
    if (!courseId) {
      return;
    }
    const res = await teamApi.getBlob(`lms/courses/${courseId}/progress.csv`);
    const url = URL.createObjectURL(res.blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'lms-progress.csv';
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className='flex flex-col gap-4'>
      <section className='flex flex-col gap-3'>
        <h2 className='text-std-18B-160 text-solid-gray-900'>コース</h2>
        <div className='overflow-x-auto rounded-8 border border-solid-gray-300'>
          <table className='w-full min-w-[32rem] border-collapse text-dns-14N-130'>
            <thead>
              <tr className='border-b border-solid-gray-300 bg-solid-gray-50 text-left text-solid-gray-600'>
                <th className='px-3 py-2'>コース名</th>
                <th className='px-3 py-2'>状態</th>
                <th className='px-3 py-2 text-right'>操作</th>
              </tr>
            </thead>
            <tbody>
              {courses.length === 0 ? (
                <tr>
                  <td colSpan={3} className='px-3 py-6 text-center text-solid-gray-500'>
                    進捗を見られるコースはありません。
                  </td>
                </tr>
              ) : (
                courses.map((item) => (
                  <tr
                    key={item.id}
                    className={`border-b border-solid-gray-200 last:border-b-0 ${item.id === courseId ? 'bg-blue-50' : ''}`}
                  >
                    <td className='px-3 py-2 text-std-16N-170 text-solid-gray-900'>
                      {item.title}
                      {item.id === courseId && (
                        <span className='ml-2 rounded-full bg-blue-100 px-2 py-0.5 text-dns-14N-130 text-blue-900'>
                          選択中
                        </span>
                      )}
                    </td>
                    <td className='px-3 py-2 text-solid-gray-600'>{statusLabel(item.status)}</td>
                    <td className='px-3 py-2 text-right'>
                      <Button type='button' variant='solid-fill' size='sm' onClick={() => onSelect(item.id)}>
                        開く
                      </Button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
      {courseId && (
        <div className='flex flex-wrap items-center justify-between gap-2'>
          <h2 className='text-std-18B-160 text-solid-gray-900'>受講者</h2>
          <Button type='button' variant='outline' size='sm' onClick={() => void download()}>
            CSV
          </Button>
        </div>
      )}
      {actions.error && (
        <p className='text-dns-14N-130 text-error-1' role='alert'>
          {actions.error}
        </p>
      )}
      {progress && (
        <div className='overflow-x-auto rounded-8 border border-solid-gray-300'>
          <table className='w-full min-w-[40rem] border-collapse text-dns-14N-130'>
            <thead>
              <tr className='border-b border-solid-gray-300 bg-solid-gray-50 text-left text-solid-gray-600'>
                <th className='px-3 py-2'>利用者</th>
                <th className='px-3 py-2'>状態</th>
                <th className='px-3 py-2'>期限</th>
                <th className='px-3 py-2'>教材</th>
                <th className='px-3 py-2'>実技</th>
              </tr>
            </thead>
            <tbody>
              {progress.rows.length === 0 ? (
                <tr>
                  <td colSpan={5} className='px-3 py-6 text-center text-solid-gray-500'>
                    受講者はいません。
                  </td>
                </tr>
              ) : (
                progress.rows.map((row) => (
                <tr key={row.userId} className='border-b border-solid-gray-200 align-top last:border-b-0'>
                  <td className='px-3 py-2'>{row.userName}</td>
                  <td className='px-3 py-2'>
                    {stateLabel(row.state)}
                    {row.overdue ? '・期限超過' : ''}
                    {row.required ? '・必須' : ''}
                  </td>
                  <td className='px-3 py-2'>{row.dueAt || ''}</td>
                  <td className='px-3 py-2'>{row.materialDone ? '完了' : ''}</td>
                  <td className='px-3 py-2'>
                    {row.practicalPending ? '未認定' : ''}
                    {canGrade &&
                      row.enrollmentId &&
                      row.practicals.map((item) => (
                        <div key={item.lessonId} className='mt-2 flex flex-wrap items-center gap-2'>
                          <span>
                            {item.title}（{statusLabel(item.lesson_status)}）
                          </span>
                          <input
                            className={fieldClass}
                            aria-label={`${item.title} の点数`}
                            value={score}
                            onChange={(e) => setScore(e.target.value)}
                            placeholder='点数'
                          />
                          <Button
                            type='button'
                            variant='solid-fill'
                            size='sm'
                            onClick={async () => {
                              const saved = await actions.grade(row.enrollmentId || '', item.lessonId, 'passed', score);
                              if (saved) {
                                await mutate();
                              }
                            }}
                          >
                            合格
                          </Button>
                          <Button
                            type='button'
                            variant='outline'
                            size='sm'
                            onClick={async () => {
                              const saved = await actions.grade(row.enrollmentId || '', item.lessonId, 'failed', score);
                              if (saved) {
                                await mutate();
                              }
                            }}
                          >
                            不合格
                          </Button>
                        </div>
                      ))}
                  </td>
                </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
