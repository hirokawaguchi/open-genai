import { useState } from 'react';
import { useNavigate } from 'react-router';
import { PiBookOpenBold, PiCalendarPlusBold } from 'react-icons/pi';
import { Button } from '@/components/ui/dads/Button';
import { PageTitle } from '@/components/PageTitle';
import {
  CustomDialog,
  CustomDialogBody,
  CustomDialogHeader,
  CustomDialogPanel,
} from '@/components/ui/CustomDialog';
import { ExAppUsageMarkdownRenderer } from '@/features/exapp/components/ExAppUsageMarkdownRenderer';
import { ManagedAppHeader } from '@/features/exapp/components/ManagedAppHeader';
import { useRegisteredAppMeta } from '@/features/exapp/hooks/useRegisteredAppMeta';
import { COMMON_EXAPPS_TEAM_ID } from '@/features/exapps/constants';
import { LayoutBody } from '@/layout/LayoutBody';
import { CHOSEI_EXAPP_ID } from '@/layout/navItems';
import { ChoseiCreateWizard } from './ChoseiCreateWizard';
import type { ChoseiEventDetail } from './types';
import { useChoseiConfig, useChoseiEvents } from './useChosei';

const formatWhen = (iso: string) => {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('ja-JP');
};

/**
 * 日程調整専用ページ（OpenGENAI 拡張）。
 * Compose profiles: ["chosei"] 未起動時は有効化手順を案内する。
 */
export const ChoseiPage = () => {
  const { documentTitle, howToUse } = useRegisteredAppMeta(
    COMMON_EXAPPS_TEAM_ID,
    CHOSEI_EXAPP_ID,
    '日程調整',
    '庁内利用者と外部参加者の日程を調整します。共有 URL からログインなしで回答できます。',
  );
  const navigate = useNavigate();
  const { config, isLoading: configLoading, unavailable } = useChoseiConfig();
  const { events, isLoading, loadError, mutate } = useChoseiEvents();
  const [wizardOpen, setWizardOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);

  const onCreated = async (detail: ChoseiEventDetail) => {
    setWizardOpen(false);
    await mutate();
    navigate(`/chosei/events/${detail.event.id}`);
  };

  return (
    <LayoutBody>
      <PageTitle title={documentTitle} />
      <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-3 p-4 lg:p-6'>
        <ManagedAppHeader
          teamId={COMMON_EXAPPS_TEAM_ID}
          exAppId={CHOSEI_EXAPP_ID}
          fallbackTitle='日程調整'
          fallbackDescription='庁内利用者と外部参加者の日程を調整します。共有 URL からログインなしで回答できます。'
          hideHowTo={true}
        />

        {(unavailable || (!configLoading && config?.enabled === false)) && (
          <div
            className='rounded-8 border border-solid-gray-420 bg-solid-gray-50 px-4 py-4 text-std-16N-170'
            role='status'
          >
            <p className='text-std-16B-150 text-solid-gray-900'>日程調整は現在有効化されていません</p>
            <p className='mt-2 text-solid-gray-700'>
              {config?.error || 'コンテナを profiles: ["chosei"] で起動してください。'}
            </p>
            <pre className='mt-3 overflow-x-auto rounded-4 bg-white p-3 text-dns-14N-130 text-solid-gray-800'>
              docker compose --profile chosei up -d{'\n'}
              # または .env に COMPOSE_PROFILES=chosei
            </pre>
          </div>
        )}

        {!unavailable && (
          <section className='flex flex-col gap-3'>
            <div className='flex flex-wrap items-end justify-between gap-2'>
              <h2 className='text-std-18B-160 text-solid-gray-900'>自分のイベント</h2>
              <div className='flex flex-wrap gap-2'>
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  className='inline-flex items-center gap-1'
                  onClick={() => setHelpOpen(true)}
                >
                  <PiBookOpenBold aria-hidden={true} className='size-4' />
                  使い方
                </Button>
                <Button
                  type='button'
                  variant='solid-fill'
                  size='sm'
                  onClick={() => setWizardOpen(true)}
                >
                  <span className='inline-flex items-center gap-1 whitespace-nowrap'>
                    <PiCalendarPlusBold className='size-4' aria-hidden={true} />
                    新しいイベント
                  </span>
                </Button>
              </div>
            </div>

            {isLoading ? (
              <p className='text-solid-gray-600'>読み込み中...</p>
            ) : loadError ? (
              <p className='text-error-1' role='alert'>
                {loadError}
              </p>
            ) : (
              <div className='overflow-x-auto rounded-8 border border-solid-gray-300'>
                <table className='w-full min-w-[40rem] border-collapse text-dns-14N-130'>
                  <thead>
                    <tr className='border-b border-solid-gray-300 bg-solid-gray-50 text-left text-solid-gray-600'>
                      <th className='w-3/5 min-w-[16rem] px-3 py-2'>イベント名</th>
                      <th className='px-3 py-2'>作成者</th>
                      <th className='px-3 py-2'>作成日時</th>
                      <th className='px-3 py-2 text-right'>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {events.length === 0 ? (
                      <tr>
                        <td colSpan={4} className='px-3 py-6 text-center text-solid-gray-500'>
                          イベントがありません。右上から新規作成してください。
                        </td>
                      </tr>
                    ) : (
                      events.map((ev) => (
                        <tr key={ev.id} className='border-b border-solid-gray-200 last:border-b-0'>
                          <td className='px-3 py-2 text-std-16N-170 text-solid-gray-900'>{ev.title}</td>
                          <td className='px-3 py-2 text-solid-gray-600'>{ev.creator_name || '—'}</td>
                          <td className='px-3 py-2 text-solid-gray-600'>{formatWhen(ev.created_at)}</td>
                          <td className='px-3 py-2 text-right'>
                            <Button
                              type='button'
                              variant='solid-fill'
                              size='xs'
                              onClick={() => navigate(`/chosei/events/${ev.id}`)}
                            >
                              開く
                            </Button>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        )}
      </div>

      <ChoseiCreateWizard
        open={wizardOpen}
        onClose={() => setWizardOpen(false)}
        onCreated={(detail) => void onCreated(detail)}
      />

      <CustomDialog isOpen={helpOpen} onClose={() => setHelpOpen(false)}>
        <CustomDialogPanel className='max-w-2xl'>
          <CustomDialogHeader hasClose onClose={() => setHelpOpen(false)}>
            使い方
          </CustomDialogHeader>
          <CustomDialogBody>
            {howToUse ? (
              <ExAppUsageMarkdownRenderer content={howToUse} size='sm' />
            ) : (
              <div className='flex flex-col gap-2 text-std-16N-170 text-solid-gray-700'>
                <p>・「新しいイベント」から名前、作成者、日程候補の順に作ります。</p>
                <p>・作成すると庁内用ページと外部共有 URL が発行されます。</p>
                <p>・外部共有 URL を相手に送ると、ログインなしで出欠を入れられます。</p>
                <p>・外部 URL に届かない場合は、リンクファイルを持ち出して別端末で開いてください。</p>
                {config?.retention_days != null && (
                  <p>・作成から {config.retention_days} 日経過したイベントは自動削除されます。</p>
                )}
              </div>
            )}
          </CustomDialogBody>
        </CustomDialogPanel>
      </CustomDialog>
    </LayoutBody>
  );
};
