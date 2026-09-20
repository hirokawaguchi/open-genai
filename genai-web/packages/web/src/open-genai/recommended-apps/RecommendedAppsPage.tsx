import { useEffect, useState } from 'react';
import { PageTitle } from '@/components/PageTitle';
import { Button } from '@/components/ui/dads/Button';
import { ErrorText } from '@/components/ui/dads/ErrorText';
import { SupportText } from '@/components/ui/dads/SupportText';
import { useTeamAuth } from '@/features/teams/hooks/useTeamAuth';
import { LayoutBody } from '@/layout/LayoutBody';
import { isApiError } from '@/lib/fetcher';
import { OfficialAppRuntimeStatus } from '@/open-genai/official-apps/OfficialAppRuntimeStatus';
import { useOfficialAppRuntime } from '@/open-genai/official-apps/useOfficialAppRuntime';
import { RECOMMENDED_APP_OPTIONS } from './recommendedApps';
import { useRecommendedApps, useRecommendedAppsActions } from './useRecommendedApps';

const readCheckedIds = (form: HTMLFormElement): string[] =>
  RECOMMENDED_APP_OPTIONS.map((opt) => opt.id).filter((id) => {
    const el = form.elements.namedItem(id);
    return el instanceof HTMLInputElement && el.checked;
  });

export const RecommendedAppsPage = () => {
  const { isSystemAdminGroup } = useTeamAuth();
  const { exAppIds, availableIds, isLoading, error: loadError } = useRecommendedApps();
  const { running: runtimeRunning } = useOfficialAppRuntime();
  const running = runtimeRunning ?? availableIds;
  const { save } = useRecommendedAppsActions();
  const [selected, setSelected] = useState<string[]>(exAppIds);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setSelected(exAppIds);
  }, [exAppIds]);

  if (!isSystemAdminGroup) {
    return (
      <LayoutBody>
        <PageTitle title='おすすめアプリ' />
        <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-6 p-6 lg:p-8'>
          <p className='text-dns-16N-130 text-error-1' role='alert'>
            このページの閲覧にはシステム管理者権限が必要です。
          </p>
        </div>
      </LayoutBody>
    );
  }

  return (
    <LayoutBody>
      <PageTitle title='おすすめアプリ' />
      <form
        className='mx-auto flex w-full max-w-(--page-width) flex-col gap-6 p-6 lg:p-8'
        onSubmit={(e) => {
          e.preventDefault();
          const checked = readCheckedIds(e.currentTarget);
          void (async () => {
            try {
              setError('');
              setBusy(true);
              const res = await save(checked);
              const kept = new Set(res.exAppIds);
              for (const id of checked) {
                kept.add(id);
              }
              setSelected(RECOMMENDED_APP_OPTIONS.map((o) => o.id).filter((id) => kept.has(id)));
            } catch (err) {
              setError(
                isApiError(err)
                  ? ((err.data as { error?: string })?.error ?? '保存に失敗しました')
                  : '保存に失敗しました',
              );
            } finally {
              setBusy(false);
            }
          })();
        }}
      >
        <h1 className='text-std-20B-160 lg:text-std-24B-150'>おすすめアプリ</h1>
        <SupportText>
          トップとサイドの「おすすめ」に出す公式アプリです。システム全体で共通です。すべてのAIアプリ一覧には影響しません。ここには存在する公式アプリをすべて出します。未起動は利用者のメニューには出ません。
        </SupportText>
        {(error || loadError) && (
          <ErrorText>
            {error || '設定を取得できませんでした。ページを再読み込みしてください。'}
          </ErrorText>
        )}
        {isLoading ? (
          <p>読み込み中...</p>
        ) : (
          <div className='flex flex-col gap-2'>
            {RECOMMENDED_APP_OPTIONS.map((opt) => (
              <label key={opt.id} className='flex items-center gap-2 text-dns-16N-130'>
                <input
                  type='checkbox'
                  name={opt.id}
                  checked={selected.includes(opt.id)}
                  onChange={(e) =>
                    setSelected((prev) =>
                      e.target.checked
                        ? [...prev, opt.id]
                        : prev.filter((id) => id !== opt.id),
                    )
                  }
                />
                <span>{opt.label}</span>
                <OfficialAppRuntimeStatus id={opt.id} running={running} />
              </label>
            ))}
          </div>
        )}
        <Button
          type='submit'
          variant='solid-fill'
          size='md'
          aria-disabled={busy || isLoading || undefined}
        >
          保存
        </Button>
      </form>
    </LayoutBody>
  );
};
