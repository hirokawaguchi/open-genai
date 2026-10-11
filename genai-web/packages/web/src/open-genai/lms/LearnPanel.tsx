import { Button } from '@/components/ui/dads/Button';
import { stateLabel } from './labels';
import type { LearningRow } from './types';

type Props = {
  rows: LearningRow[];
  busy: boolean;
  onOpen: (courseId: string, enrollmentId: string | null) => void;
};

export const LearnPanel = ({ rows, busy, onOpen }: Props) => {
  return (
    <section className='flex flex-col gap-3'>
      <h2 className='text-std-18B-160 text-solid-gray-900'>受講一覧</h2>
      <div className='overflow-x-auto rounded-8 border border-solid-gray-300'>
        <table className='w-full min-w-[40rem] border-collapse text-dns-14N-130'>
          <thead>
            <tr className='border-b border-solid-gray-300 bg-solid-gray-50 text-left text-solid-gray-600'>
              <th className='px-3 py-2'>コース名</th>
              <th className='px-3 py-2'>状態</th>
              <th className='px-3 py-2'>期限</th>
              <th className='px-3 py-2 text-right'>操作</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={4} className='px-3 py-6 text-center text-solid-gray-500'>
                  割り当てられたコースはありません。
                </td>
              </tr>
            ) : (
              rows.map((row) => (
                <tr key={row.courseId} className='border-b border-solid-gray-200 last:border-b-0'>
                  <td className='px-3 py-2 text-std-16N-170 text-solid-gray-900'>{row.title}</td>
                  <td className='px-3 py-2 text-solid-gray-600'>
                    {stateLabel(row.state)}
                    {row.required ? '・必須' : ''}
                    {row.overdue ? '・期限超過' : ''}
                    {row.practicalPending ? '・実技が未認定' : ''}
                  </td>
                  <td className='px-3 py-2 text-solid-gray-600'>{row.dueAt || ''}</td>
                  <td className='px-3 py-2 text-right'>
                    <Button
                      type='button'
                      variant='solid-fill'
                      size='sm'
                      aria-disabled={busy}
                      onClick={() => {
                        if (busy) {
                          return;
                        }
                        onOpen(row.courseId, row.enrollmentId);
                      }}
                    >
                      {row.state === 'not_started' ? '始める' : '続きから'}
                    </Button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
};
