import { useMemo, useState } from 'react';
import { PiBookOpenBold } from 'react-icons/pi';
import { PageTitle } from '@/components/PageTitle';
import { BreadcrumbsNav } from '@/components/ui/BreadcrumbsNav';
import {
  CustomDialog,
  CustomDialogBody,
  CustomDialogHeader,
  CustomDialogPanel,
} from '@/components/ui/CustomDialog';
import { Button } from '@/components/ui/dads/Button';
import { ExAppUsageMarkdownRenderer } from '@/features/exapp/components/ExAppUsageMarkdownRenderer';
import { useRegisteredAppMeta } from '@/features/exapp/hooks/useRegisteredAppMeta';
import { COMMON_EXAPPS_TEAM_ID } from '@/features/exapps/constants';
import { LayoutBody } from '@/layout/LayoutBody';
import { LMS_EXAPP_ID } from '@/layout/navItems';
import { CoursePanel } from './CoursePanel';
import { CourseWizard } from './CourseWizard';
import { LearnPanel } from './LearnPanel';
import { LibraryPanel } from './LibraryPanel';
import { PlayerPanel } from './PlayerPanel';
import { ProgressPanel } from './ProgressPanel';
import { TranscriptPanel } from './TranscriptPanel';
import { useLmsActions, useLmsConfig, useLmsHome, useLmsMaterials } from './useLms';

const tabs = [
  { id: 'learn', label: '受講' },
  { id: 'library', label: '教材庫' },
  { id: 'courses', label: 'コース' },
  { id: 'progress', label: '進捗' },
] as const;

type Tab = (typeof tabs)[number]['id'] | 'play' | 'preview';

export const LmsPage = () => {
  const { documentTitle, title, description, howToUse } = useRegisteredAppMeta(
    COMMON_EXAPPS_TEAM_ID,
    LMS_EXAPP_ID,
    '研修',
    '研修動画とテキストをコースにし、受講と実技認定の記録を残します。',
  );
  const { isLoading, unavailable, error } = useLmsConfig();
  const enabled = !isLoading && !unavailable;
  const { home, mutate } = useLmsHome(enabled);
  const libraryEnabled = enabled && Boolean(home?.canUseLibrary);
  const { materials, mutate: mutateMaterials } = useLmsMaterials(libraryEnabled);
  const { materials: trashedMaterials, mutate: mutateTrashed } = useLmsMaterials(libraryEnabled, 'trash');
  const actions = useLmsActions();
  const [helpOpen, setHelpOpen] = useState(false);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [tab, setTab] = useState<Tab>('learn');
  const [courseId, setCourseId] = useState<string | null>(null);
  const [enrollmentId, setEnrollmentId] = useState<string | null>(null);
  const [transcriptId, setTranscriptId] = useState<string | null>(null);
  const transcriptSplits =
    materials.some((item) => item.id === transcriptId) || trashedMaterials.some((item) => item.id === transcriptId);

  const progressCourses = useMemo(() => {
    const map = new Map<string, { id: string; title: string; status: 'draft' | 'published' }>();
    for (const course of home?.editableCourses ?? []) {
      map.set(course.id, course);
    }
    for (const course of home?.certifiableCourses ?? []) {
      map.set(course.id, course);
    }
    return [...map.values()];
  }, [home]);

  const openTab = (next: Tab, extra?: { course?: string; enrollment?: string }) => {
    setTab(next);
    setCourseId(extra?.course ?? null);
    setEnrollmentId(extra?.enrollment ?? null);
    setTranscriptId(null);
  };

  return (
    <LayoutBody>
      <PageTitle title={documentTitle} />
      <div
        className={
          transcriptSplits
            ? 'mx-auto flex h-[calc(100dvh-var(--header-height))] w-full max-w-(--page-width) min-h-0 flex-col gap-3 overflow-hidden p-4 lg:p-6'
            : 'mx-auto flex w-full max-w-(--page-width) flex-col gap-3 p-4 lg:p-6'
        }
      >
        <BreadcrumbsNav
          items={[
            { label: 'ホーム', to: '/' },
            { label: 'AIアプリ', to: '/apps' },
            tab === 'play' || tab === 'preview' || transcriptId
              ? {
                  label: title,
                  onClick: () => {
                    if (transcriptId) {
                      setTranscriptId(null);
                      return;
                    }
                    openTab(
                      tab === 'preview' ? 'courses' : 'learn',
                      tab === 'preview' && courseId ? { course: courseId } : {},
                    );
                  },
                }
              : { label: title },
            ...(tab === 'play' ? [{ label: '受講' }] : []),
            ...(tab === 'preview' ? [{ label: 'プレビュー' }] : []),
            ...(transcriptId ? [{ label: '本文' }] : []),
          ]}
        />
        <div className='flex min-w-0 items-center justify-between gap-3'>
          <div className='flex min-w-0 items-baseline gap-3'>
            <h1 className='shrink-0 text-std-16B-170 text-solid-gray-900'>{title}</h1>
            {description && (
              <p className='truncate text-dns-14N-130 text-solid-gray-600' title={description}>
                {description}
              </p>
            )}
          </div>
          <Button
            type='button'
            variant='outline'
            size='sm'
            className='inline-flex shrink-0 items-center gap-1'
            onClick={() => setHelpOpen(true)}
          >
            <PiBookOpenBold aria-hidden={true} className='size-4' />
            使い方
          </Button>
        </div>
        {(unavailable || (!isLoading && error)) && (
          <div className='rounded-8 border border-solid-gray-420 bg-solid-gray-50 px-4 py-4' role='status'>
            <p className='text-std-16B-150'>研修は現在有効化されていません</p>
            <p className='mt-2 text-std-16N-170 text-solid-gray-700'>{error || 'コンテナを profiles: ["lms"] で起動してください。'}</p>
            <pre className='mt-3 overflow-x-auto rounded-4 bg-white p-3 text-dns-14N-130'>
              docker compose --profile lms up -d{'\n'}
              # または .env に COMPOSE_PROFILES=lms
            </pre>
          </div>
        )}
        {enabled && home && tab !== 'play' && tab !== 'preview' && !transcriptId && (
          <div className='flex flex-wrap gap-1 overflow-x-auto border-b border-solid-gray-300'>
            {tabs
              .filter((item) => item.id !== 'library' || home.canUseLibrary)
              .map((item) => (
                <button
                  key={item.id}
                  type='button'
                  onClick={() => openTab(item.id)}
                  className={
                    tab === item.id
                      ? 'whitespace-nowrap border-b-2 border-blue-900 px-3 py-2 text-std-16B-150 text-blue-900'
                      : 'whitespace-nowrap px-3 py-2 text-std-16N-170 text-solid-gray-700 hover:text-blue-900'
                  }
                >
                  {item.label}
                </button>
              ))}
          </div>
        )}
        {enabled && home && tab === 'learn' && (
          <LearnPanel
            rows={home.learning}
            busy={actions.busy}
            onOpen={async (id, existing) => {
              if (existing) {
                openTab('play', { enrollment: existing });
                return;
              }
              const started = await actions.start(id);
              if (started) {
                await mutate();
                openTab('play', { enrollment: started.enrollmentId });
              }
            }}
          />
        )}
        {actions.error && tab === 'learn' && <p className='text-dns-14N-130 text-red-700'>{actions.error}</p>}
        {enabled && home && tab === 'library' && !transcriptId && (
          <LibraryPanel
            materials={materials}
            trashedMaterials={trashedMaterials}
            onOpenTranscript={setTranscriptId}
            onChanged={() => {
              void mutateMaterials();
              void mutateTrashed();
            }}
          />
        )}
        {enabled && home && tab === 'library' && transcriptId && (
          <TranscriptPanel
            key={transcriptId}
            materialId={transcriptId}
            onChanged={() => {
              void mutateMaterials();
            }}
          />
        )}
        {enabled && home && tab === 'courses' && (
          <CoursePanel
            courses={home.editableCourses}
            courseId={courseId}
            users={home.users}
            teams={home.teams}
            materials={materials}
            trashedMaterials={trashedMaterials}
            onSelect={(id) => openTab('courses', { course: id })}
            onOpenWizard={() => setWizardOpen(true)}
            onPreview={(id) => openTab('preview', { course: id })}
            onChanged={() => {
              void mutate();
            }}
            onDeleted={() => openTab('courses')}
          />
        )}
        {enabled && home && tab === 'progress' && (
          <ProgressPanel
            courses={progressCourses}
            courseId={courseId}
            canGrade={home.certifiableCourses.some((course) => course.id === courseId)}
            onSelect={(id) => openTab('progress', { course: id })}
          />
        )}
        {enabled && tab === 'play' && (
          <PlayerPanel enrollmentId={enrollmentId} previewCourseId={null} onBack={() => openTab('learn')} />
        )}
        {enabled && tab === 'preview' && (
          <PlayerPanel enrollmentId={null} previewCourseId={courseId} onBack={() => openTab('courses', courseId ? { course: courseId } : {})} />
        )}
      </div>
      <CustomDialog isOpen={helpOpen} onClose={() => setHelpOpen(false)}>
        <CustomDialogPanel className='max-w-lg'>
          <CustomDialogHeader hasClose onClose={() => setHelpOpen(false)}>
            使い方
          </CustomDialogHeader>
          <CustomDialogBody>
            {howToUse ? (
              <ExAppUsageMarkdownRenderer content={howToUse} size='sm' />
            ) : (
              <div className='flex flex-col gap-1.5 text-dns-14N-130 text-solid-gray-700'>
                <p>・コースを作ると、自分がそのコースのコース編集者になります。</p>
                <p>・教材庫は、棟の所属者が使います。コースが無くても、動画と PDF を置けます。</p>
                <p>・教材の本文は「本文」から作ります。PDF はページごと、動画は発話ごとに直して確定します。</p>
                <p>・修了は、必須の教材と必須の実技がどちらも合格または完了のときです。</p>
              </div>
            )}
          </CustomDialogBody>
        </CustomDialogPanel>
      </CustomDialog>
      {home && (
        <CourseWizard
          open={wizardOpen}
          users={home.users}
          teams={home.teams}
          materials={materials}
          selfUserId={home.userId}
          onClose={() => setWizardOpen(false)}
          onCreated={async (id) => {
            await mutate();
            openTab('courses', { course: id });
          }}
        />
      )}
    </LayoutBody>
  );
};
