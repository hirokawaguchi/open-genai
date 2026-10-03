import { useEffect, useRef, useState, type DragEvent, type FormEvent, type ReactNode } from 'react';
import { PiBookOpenBold } from 'react-icons/pi';
import { PageTitle } from '@/components/PageTitle';
import {
  CustomDialog,
  CustomDialogBody,
  CustomDialogHeader,
  CustomDialogPanel,
} from '@/components/ui/CustomDialog';
import { Button } from '@/components/ui/dads/Button';
import { Label } from '@/components/ui/dads/Label';
import { ExAppUsageMarkdownRenderer } from '@/features/exapp/components/ExAppUsageMarkdownRenderer';
import { useRegisteredAppMeta } from '@/features/exapp/hooks/useRegisteredAppMeta';
import { COMMON_EXAPPS_TEAM_ID } from '@/features/exapps/constants';
import { LayoutBody } from '@/layout/LayoutBody';
import { NISHUKAN_EXAPP_ID } from '@/layout/navItems';
import type { NishukanHome, NishukanIssue, NishukanProject } from './types';
import { useNishukanActions, useNishukanConfig, useNishukanHome } from './useNishukan';

const fieldClass = 'w-full rounded-4 border border-solid-gray-420 bg-white px-3 py-2 text-std-16N-170';
const SIZE_OPTIONS = ['0.25', '0.5', '1', '2', '3', '5', '8'];
const formatSize = (value: number) => {
  const quarters = Math.round(value * 4) / 4;
  return Number.isInteger(quarters) ? String(quarters) : String(quarters);
};
const formatWhen = (iso: string) => {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  const hour = String(date.getHours()).padStart(2, '0');
  const minute = String(date.getMinutes()).padStart(2, '0');
  return `${date.getMonth() + 1}/${date.getDate()} ${hour}:${minute}`;
};
const noteLinks = (text: string) => text.match(/https?:\/\/[^\s)]+/g) ?? [];
const compactField = 'rounded-4 border border-solid-gray-420 bg-white px-2 py-1 text-dns-14N-130';
const shellClass =
  'mx-auto flex h-[calc(100dvh-var(--header-height))] w-full max-w-(--page-width) flex-col gap-2 overflow-hidden px-4 py-2 lg:px-6';

type Pane = 'board' | 'setup';

const STATUS: { id: string; label: string }[] = [
  { id: 'todo', label: '未着手' },
  { id: 'doing', label: '対応中' },
  { id: 'waiting', label: '待ち' },
  { id: 'done', label: '完了' },
];

const statusLabel = (id: string) => STATUS.find((s) => s.id === id)?.label ?? id;

const scheduleBlock = (issue: NishukanIssue): string | null => {
  if (!issue.completionText.trim() || (issue.completionMode !== 'chief' && issue.completionMode !== 'objective')) {
    return '完了条件を書いてから、未着手へ移せます。';
  }
  if (issue.completionMode === 'objective' && issue.checks.length === 0) {
    return '確認項目を書いてから、未着手へ移せます。';
  }
  return null;
};

const routinePiles = (issues: NishukanIssue[], names: Map<string, string>) => {
  const groups = new Map<string, NishukanIssue[]>();
  for (const issue of issues) {
    const key = issue.templateId || issue.title;
    const list = groups.get(key) ?? [];
    list.push(issue);
    groups.set(key, list);
  }
  return [...groups.entries()].map(([id, items]) => ({
    id,
    name:
      items[0]?.templateName ||
      (items[0]?.templateId && names.get(items[0].templateId)) ||
      items[0]?.title ||
      '定常',
    items,
    size: items.reduce((sum, issue) => sum + (issue.size ?? 0), 0),
  }));
};

const tabClass = (active: boolean) =>
  active
    ? 'whitespace-nowrap border-b-2 border-blue-900 px-3 py-1.5 text-std-16B-150 text-blue-900'
    : 'whitespace-nowrap px-3 py-1.5 text-std-16N-170 text-solid-gray-700 hover:text-blue-900';

const Shell = ({
  documentTitle,
  title,
  description,
  toolbar,
  help,
  children,
}: {
  documentTitle: string;
  title: string;
  description: string;
  toolbar?: ReactNode;
  help?: ReactNode;
  children: ReactNode;
}) => (
  <LayoutBody>
    <PageTitle title={documentTitle} />
    <div className={shellClass}>
      <div className='flex min-w-0 items-baseline gap-3'>
        <h1 className='shrink-0 text-std-16B-170 text-solid-gray-900'>{title}</h1>
        {description && (
          <p className='truncate text-dns-14N-130 text-solid-gray-600' title={description}>
            {description}
          </p>
        )}
      </div>
      {toolbar}
      {children}
      {help}
    </div>
  </LayoutBody>
);

const HelpDialog = ({
  open,
  howToUse,
  onClose,
}: {
  open: boolean;
  howToUse: string;
  onClose: () => void;
}) => (
  <CustomDialog isOpen={open} onClose={onClose}>
    <CustomDialogPanel className='max-w-2xl'>
      <CustomDialogHeader hasClose onClose={onClose}>
        使い方
      </CustomDialogHeader>
      <CustomDialogBody>
        <div className='flex flex-col gap-4 text-std-16N-170 text-solid-gray-800'>
          <p>チームの2週間の仕事を、この画面で見ます。仕事の持ち主はチームです。今期枠に何を入れるかは、所属長が決めます。</p>
          <section className='flex flex-col gap-1'>
            <h2 className='m-0 text-std-16B-170'>期枠</h2>
            <p>上の3枚が期枠です。ひとつは2週間です。今期枠が、いま進める仕事の入れ物です。前期枠は直前の2週間で、次の見通しの基準になります。次期枠は、その次の2週間です。カードを押すと、その2週間の中身に切り替わります。</p>
            <p>棒は、入っている量の内訳です。濃い青が計画、薄い青が定常、灰色が休みです。縦の線は、前期枠で終えた量です。休みがあると、その分だけ仕事に回せる量が減ります。棒の下に、その目安が書いてあります。</p>
          </section>
          <section className='flex flex-col gap-1'>
            <h2 className='m-0 text-std-16B-170'>作業</h2>
            <p>白いカードが、1件の作業です。カードをほかの列へドラッグすると、未着手、対応中、待ちが変わります。</p>
            <p>期枠未定は、いつやるかまだ決めていない作業です。今期枠と次期枠の両方に出ます。ここにいるあいだは規模がありません。終わったと言える条件も、ここにいるあいだに書きます。期枠に入ったあとは、その条件のまま進めます。</p>
            <p>期枠未定から未着手へドラッグすると、詳細が開きます。完了条件を書いて「今期枠の未着手にする」を押すと移ります。閉じただけでは、期枠未定のままです。移すときに規模を置きます。1は、1人が1日働く量です。いちばん小さい0.25は、およそ2時間です。</p>
            <p>完了へドラッグしても、すぐには完了になりません。詳細で、確認項目をすべて入れるか、所属長が完了にします。閉じると、元の列のままです。</p>
            <p>「作業追加」を押すと、空の詳細が開きます。名称を書くと残ります。書かずに閉じると、何も残りません。</p>
          </section>
          <section className='flex flex-col gap-1'>
            <h2 className='m-0 text-std-16B-170'>定常</h2>
            <p>上の青いボタンは、繰り返す仕事の分類です。窓口相談や、他課からの依頼のような名前です。ボタンを押すと詳細が開き、その1件の名称を書きます。たとえば「資料を送る」「山田さんの相談」です。書かずに閉じると残りません。</p>
            <p>列の上にある青いまとまりが、その分類です。開くと、1件ずつの名称と来た日時が出ます。定常はドラッグしません。急ぎの仕事なので、規模は大きめでもかまいません。所属長は、詳細から規模を見直せます。</p>
          </section>
          <section className='flex flex-col gap-1'>
            <h2 className='m-0 text-std-16B-170'>休み</h2>
            <p>祝日は、カレンダーに合わせて前期枠・今期枠・次期枠へ入ります。チーム設定で人数を置くと、祝日1日は人数のぶんだけ規模が引かれます。5人なら、祝日1日で5です。人数が未設定のあいだは、引きません。</p>
            <p>メンバーの休暇は、見ている期枠の「休暇登録」で、合計の規模だけを置きます。0にすると、その期枠の休暇は消えます。登録できるのは所属長です。</p>
          </section>
          <section className='flex flex-col gap-1'>
            <h2 className='m-0 text-std-16B-170'>事業とチーム設定</h2>
            <p>事業は、作業を束ねる名前です。どの取り組みの仕事か、後から付けられます。書いた時点で決まっていなくても、作業は残せます。</p>
            <p>人数、所属長、事業、定型、外から仕事を足すための受付の鍵は、チーム設定にあります。休暇や、いま見ている期枠の中身は、通常の画面で扱います。</p>
          </section>
        </div>
        {howToUse && (
          <div className='mt-4'>
            <ExAppUsageMarkdownRenderer content={howToUse} size='sm' />
          </div>
        )}
      </CustomDialogBody>
    </CustomDialogPanel>
  </CustomDialog>
);

/**
 * 二週間の仕事。Compose profiles: ["nishukan"] 未起動時は有効化手順を案内する。
 * 課題は個人に割り当てない。期枠と優先度と完了の判定は所属長が行う。
 */
export const NishukanPage = () => {
  const { documentTitle, title, description, howToUse } = useRegisteredAppMeta(
    COMMON_EXAPPS_TEAM_ID,
    NISHUKAN_EXAPP_ID,
    '二週間の仕事',
    'チームの仕事を２週間単位で区切り、その中で何をどこまでやるかを管理します。',
  );
  const { isLoading: configLoading, unavailable, error: configError } = useNishukanConfig();
  const [teamId, setTeamId] = useState<string | null>(null);
  const { home, isLoading, loadError, mutate } = useNishukanHome(teamId, !unavailable);
  const actions = useNishukanActions();
  const [selected, setSelected] = useState<NishukanIssue | null>(null);
  const [receiptKey, setReceiptKey] = useState<string | null>(null);
  const [pane, setPane] = useState<Pane>('board');
  const [boxFocus, setBoxFocus] = useState<'previous' | 'current' | 'next'>('current');
  const [openPile, setOpenPile] = useState<string | null>(null);
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [dropColumn, setDropColumn] = useState<string | null>(null);
  const [dropIntent, setDropIntent] = useState<'todo' | 'done' | null>(null);
  const skipClick = useRef(false);
  const dropNotice = useRef<string | null>(null);
  const [vacationOpen, setVacationOpen] = useState(false);
  const [vacationSize, setVacationSize] = useState('');
  const [helpOpen, setHelpOpen] = useState(false);

  const refresh = async () => {
    await mutate();
  };

  const help = (
    <HelpDialog open={helpOpen} howToUse={howToUse} onClose={() => setHelpOpen(false)} />
  );

  if (configLoading || (isLoading && !home)) {
    return (
      <Shell documentTitle={documentTitle} title={title} description={description} help={help}>
        <p className='text-dns-16N-130'>読み込み中…</p>
      </Shell>
    );
  }

  if (!home || unavailable || home.enabled === false) {
    return (
      <Shell documentTitle={documentTitle} title={title} description={description} help={help}>
        <p className='text-dns-16N-130 text-solid-gray-800' role='alert'>
          {loadError ||
            configError ||
            '二週間の仕事はまだ有効になっていません。`docker compose --profile nishukan up -d` で起動してください。'}
        </p>
      </Shell>
    );
  }

  const data = home as NishukanHome;
  const currentStart = data.boxes?.current.start ?? '';
  const focusStart = data.boxes?.[boxFocus].start ?? '';
  const inFocus = (issues: NishukanIssue[] | undefined) =>
    (issues ?? []).filter((issue) => issue.timeboxStart === focusStart);
  const planInBox = inFocus(data.planIssues);
  const undecided = (data.planIssues ?? []).filter((issue) => !issue.timeboxStart);
  const routineFlat = (data.routine ?? []).flatMap((group) => group.issues);
  const columns = boxFocus === 'previous' ? STATUS : [{ id: 'unscheduled', label: '期枠未定' }, ...STATUS];
  const leaveInBox = inFocus(data.leaveIssues);
  const routineInBox = (data.routine ?? [])
    .map((group) => {
      const issues = group.issues.filter((issue) => issue.timeboxStart === focusStart);
      return {
        ...group,
        issues,
        count: issues.length,
        openCount: issues.filter((issue) => issue.status !== 'done').length,
        size: issues.reduce((sum, issue) => sum + (issue.size ?? 0), 0),
      };
    })
    .filter((group) => group.count > 0);
  const sizeOf = (issues: NishukanIssue[]) => issues.reduce((sum, issue) => sum + (issue.size ?? 0), 0);
  const planSize = sizeOf(planInBox);
  const routineSize = routineInBox.reduce((sum, group) => sum + group.size, 0);
  const leaveSize = sizeOf(leaveInBox);
  const reserve = boxFocus === 'next' ? (data.boxes?.next.routineReserve ?? 0) : 0;
  const pace = data.pace ?? 0;
  const leaveImpact =
    boxFocus === 'previous'
      ? `前期枠でこなした作業は規模 ${formatSize(pace)} です。休みが使った規模は ${formatSize(leaveSize)} です。`
      : leaveSize > 0
        ? pace >= leaveSize
          ? `休みがこの期枠の作業を規模 ${formatSize(leaveSize)} 削ります。前期枠でこなした規模 ${formatSize(pace)} から引くと、作業に回せる目安は規模 ${formatSize(pace - leaveSize)} です。`
          : `休みがこの期枠の作業を規模 ${formatSize(leaveSize)} 削ります。前期枠でこなした規模 ${formatSize(pace)} を、休みが規模 ${formatSize(leaveSize - pace)} 上回っています。`
        : `休みの規模はまだ 0 です。祝日や休暇に規模を置くと、前期枠でこなした規模 ${formatSize(pace)} からその分が引かれます。`;
  const focusNote =
    boxFocus === 'next'
      ? `${leaveImpact} 先に入っているのは規模 ${formatSize(planSize + routineSize + leaveSize)} で、直前の定常 規模 ${formatSize(reserve)} を見込みに足します。`
      : leaveImpact;

  const hasTeam = Boolean(data.teamId && data.boxes);
  const dropPlan = async (issue: NishukanIssue, columnId: string) => {
    if (!issue.timeboxStart) {
      if (columnId !== 'todo' || !data.isChief || !focusStart) return;
      if (scheduleBlock(issue)) {
        setDropIntent('todo');
        setSelected(issue);
        return;
      }
      const updated = await actions.updateIssue(issue.id, {
        status: 'todo',
        timeboxStart: focusStart,
        size: issue.size ?? 1,
      });
      if (updated) await refresh();
      return;
    }
    if (columnId === 'done') {
      setDropIntent('done');
      setSelected(issue);
      return;
    }
    if (columnId === 'unscheduled') return;
    const updated = await actions.updateIssue(issue.id, { status: columnId });
    if (updated) await refresh();
  };

  return (
    <Shell
      documentTitle={documentTitle}
      title={title}
      description={description}
      help={help}
      toolbar={
        <div className='flex flex-wrap items-center justify-between gap-2'>
          <div role='tablist' aria-label='二週間の仕事' className='flex gap-1 overflow-x-auto border-b border-solid-gray-300'>
            <button type='button' role='tab' aria-selected={pane === 'board'} className={tabClass(pane === 'board')} onClick={() => setPane('board')}>
              通常
            </button>
            <button type='button' role='tab' aria-selected={pane === 'setup'} className={tabClass(pane === 'setup')} onClick={() => setPane('setup')}>
              チーム設定
            </button>
          </div>
          <div className='flex items-center gap-2'>
            {data.teams && data.teams.length > 1 && (
              <select
                id='nishukan-team'
                aria-label='チーム'
                className={compactField}
                value={data.teamId ?? ''}
                onChange={(e) => {
                  setTeamId(e.target.value);
                  setSelected(null);
                  setBoxFocus('current');
                }}
              >
                {data.teams.map((t) => (
                  <option key={t.teamId} value={t.teamId}>
                    {t.teamName}
                  </option>
                ))}
              </select>
            )}
            <Button type='button' variant='outline' size='sm' className='inline-flex items-center gap-1' onClick={() => setHelpOpen(true)}>
              <PiBookOpenBold aria-hidden={true} className='size-4' />
              使い方
            </Button>
          </div>
        </div>
      }
    >
      {(loadError || actions.error) && (
        <p className='text-dns-14N-130 text-error-1' role='alert'>
          {loadError || actions.error}
        </p>
      )}

      {!hasTeam && (
        <p
          className='rounded-8 border border-solid-gray-420 bg-solid-gray-50 px-3 py-2 text-dns-16N-130'
          role='status'
        >
          この棟にはチームがありません。別の棟を選ぶか、この棟にチームを作ると、期枠と課題を使えます。
        </p>
      )}

      {hasTeam && (
      <>
      <div className={pane === 'board' ? 'flex min-h-0 flex-1 flex-col gap-2' : 'hidden'}>
      <section className='grid shrink-0 gap-2 md:grid-cols-3'>
        <BoxButton
          active={boxFocus === 'previous'}
          title='前期枠'
          meaning='直前の2週間。こなした量が、次の基準'
          start={data.boxes?.previous.start}
          end={data.boxes?.previous.end}
          size={data.pace ?? 0}
          sizeLabel='完了'
          onClick={() => {
            setBoxFocus('previous');
            setSelected(null);
          }}
        />
        <BoxButton
          active={boxFocus === 'current'}
          title='今期枠'
          meaning='いまの2週間。計画と定常と休みが入る'
          start={data.boxes?.current.start}
          end={data.boxes?.current.end}
          size={data.boxes?.current.size ?? 0}
          sizeLabel='入っている'
          onClick={() => {
            setBoxFocus('current');
            setSelected(null);
          }}
        />
        <BoxButton
          active={boxFocus === 'next'}
          title='次期枠'
          meaning='次の2週間。先入れと、直前の定常の見込み'
          start={data.boxes?.next.start}
          end={data.boxes?.next.end}
          size={data.boxes?.next.forecastSize ?? 0}
          sizeLabel='見込み'
          onClick={() => {
            setBoxFocus('next');
            setSelected(null);
          }}
        />
      </section>
      <LoadBar
        plan={planSize}
        routine={routineSize}
        leave={leaveSize}
        reserve={reserve}
        pace={boxFocus === 'previous' ? 0 : pace}
        note={focusNote}
      />

      <div className='flex shrink-0 flex-wrap items-center gap-2'>
          <span className='text-dns-14N-130 text-solid-gray-600'>今期枠へ足す</span>
          {(data.templates ?? []).map((template) => (
            <Button
              key={template.id}
              type='button'
              variant='solid-fill'
              size='sm'
              aria-disabled={actions.busy || !data.isMember}
              onClick={() => {
                const project = (data.projects ?? []).find((item) => item.id === template.projectId);
                setBoxFocus('current');
                setSelected({
                  id: '',
                  projectId: template.projectId,
                  projectKey: project?.key ?? '',
                  projectMode: 'routine',
                  teamId: data.teamId ?? '',
                  number: 0,
                  title: '',
                  body: '',
                  status: 'todo',
                  priority: template.priority,
                  size: template.size,
                  kind: 'work',
                  leaveName: '',
                  completionText: template.completionText,
                  completionMode: template.completionMode,
                  timeboxStart: currentStart,
                  templateId: template.id,
                  dueDate: null,
                  createdAt: '',
                  checks: [],
                  comments: [],
                });
              }}
            >
              {template.name}・規模 {formatSize(template.size)}
            </Button>
          ))}
          {(data.templates ?? []).length === 0 && (
            <p className='text-dns-14N-130 text-solid-gray-700'>定型はまだありません。チーム設定で作ります。</p>
          )}
          <div className='ml-auto flex items-center gap-2'>
            <Button
              type='button'
              variant='outline'
              size='sm'
              aria-disabled={!focusStart}
              onClick={() => {
                const current = leaveInBox.find((issue) => issue.title === '休暇' && !issue.leaveName && !issue.holidayDate);
                setVacationSize(current?.size ? formatSize(current.size) : '');
                setVacationOpen(true);
              }}
            >
              休暇登録
            </Button>
            <Button
              type='button'
              variant='outline'
              size='sm'
              aria-disabled={actions.busy || !data.teamId}
              onClick={() => {
                if (boxFocus === 'previous') setBoxFocus('current');
                setSelected({
                  id: '',
                  projectId: '',
                  projectKey: '',
                  projectMode: 'plan',
                  teamId: data.teamId ?? '',
                  number: 0,
                  title: '',
                  body: '',
                  status: 'todo',
                  priority: null,
                  size: null,
                  kind: 'work',
                  leaveName: '',
                  completionText: '',
                  completionMode: null,
                  timeboxStart: null,
                  templateId: null,
                  dueDate: null,
                  createdAt: '',
                  checks: [],
                  comments: [],
                });
              }}
            >
              作業追加
            </Button>
          </div>
      </div>

      <CustomDialog isOpen={vacationOpen} onClose={() => setVacationOpen(false)}>
        <CustomDialogPanel>
          <CustomDialogHeader hasClose onClose={() => setVacationOpen(false)}>
            休暇登録
          </CustomDialogHeader>
          <CustomDialogBody>
            <p className='text-std-16N-170 text-solid-gray-700'>
              {boxFocus === 'previous' ? '前期枠' : boxFocus === 'next' ? '次期枠' : '今期枠'}
              の休暇を、規模の合計で置きます。0にすると、この期枠の休暇は消えます。
            </p>
            {data.isChief ? (
              <form
                className='mt-4 flex flex-col items-start gap-2'
                onSubmit={async (e) => {
                  e.preventDefault();
                  if (!data.teamId || !focusStart || vacationSize === '') return;
                  if (await actions.setVacation(data.teamId, focusStart, Number(vacationSize))) {
                    setVacationOpen(false);
                    await refresh();
                  }
                }}
              >
                <Label htmlFor='nishukan-vacation-size' size='sm'>
                  規模
                </Label>
                <input
                  id='nishukan-vacation-size'
                  type='number'
                  min={0}
                  step={0.25}
                  className={`${compactField} w-28`}
                  value={vacationSize}
                  onChange={(e) => setVacationSize(e.target.value)}
                />
                <Button type='submit' variant='solid-fill' size='sm' aria-disabled={actions.busy || vacationSize === ''}>
                  登録する
                </Button>
              </form>
            ) : (
              <p className='mt-4 text-dns-16N-130'>休暇の規模は、所属長が置きます。</p>
            )}
          </CustomDialogBody>
        </CustomDialogPanel>
      </CustomDialog>

      {leaveInBox.length > 0 && (
        <p className='shrink-0 truncate text-dns-14N-130 text-solid-gray-700'>
          この期枠の休み{' '}
          {leaveInBox
            .map((issue) => {
              const amount = issue.holidayDate && !data.headcount ? '人数未設定' : issue.size == null ? '' : formatSize(issue.size);
              return `${issue.title}${issue.leaveName ? `（${issue.leaveName}）` : ''} ${amount}`;
            })
            .join('、')}
        </p>
      )}

      <div className='flex min-h-0 flex-1 flex-col gap-2 overflow-hidden'>
        {selected && (
        <IssuePanel
          issue={selected}
          isChief={Boolean(data.isChief)}
          currentStart={currentStart}
          busy={actions.busy}
          dropIntent={dropIntent}
          acceptLabel={dropIntent === 'todo' && boxFocus === 'next' ? '次期枠の未着手にする' : '今期枠の未着手にする'}
          onClose={() => {
            setDropIntent(null);
            setSelected(null);
          }}
          onStatus={async (status) => {
            const updated = await actions.updateIssue(selected.id, { status });
            if (updated) {
              setSelected(updated);
              await refresh();
            }
          }}
          onComplete={async () => {
            const updated = await actions.updateIssue(selected.id, { complete: true });
            if (updated) {
              setDropIntent(null);
              setSelected(updated);
              await refresh();
            }
          }}
          onCheck={async (checkId, done) => {
            const updated = await actions.setCheck(selected.id, checkId, done);
            if (updated) {
              if (updated.status === 'done') setDropIntent(null);
              setSelected(updated);
              await refresh();
            }
          }}
          onComment={async (body) => {
            const updated = await actions.comment(selected.id, body);
            if (updated) {
              setSelected(updated);
            }
          }}
          onPlace={async () => {
            const updated = await actions.updateIssue(selected.id, { timeboxStart: currentStart });
            if (updated) {
              setBoxFocus('current');
              setSelected(updated);
              await refresh();
            }
          }}
          projects={data.projects ?? []}
          templateName={(data.templates ?? []).find((item) => item.id === selected.templateId)?.name ?? ''}
          onSave={async (body) => {
            if (!selected.id && selected.templateId) {
              const title = String(body.title || '').trim();
              if (!title) return;
              const created = await actions.arrive(selected.templateId, title);
              if (created) {
                setBoxFocus('current');
                setSelected(created);
                await refresh();
              }
              return;
            }
            if (!selected.id) {
              const title = String(body.title || '').trim();
              if (!title || !data.teamId) return;
              const created = await actions.createIssue({
                projectId: body.projectId || '',
                teamId: data.teamId,
                title,
                body: body.body || '',
                ...(body.completionText
                  ? {
                      completionText: body.completionText,
                      completionMode: body.completionMode,
                      checks: body.checks,
                    }
                  : {}),
              });
              if (created) {
                setSelected(created);
                await refresh();
              }
              return;
            }
            const updated = await actions.updateIssue(selected.id, body);
            if (updated) {
              setSelected(updated);
              await refresh();
            }
          }}
          onAccept={async (body) => {
            let issueId = selected.id;
            if (!issueId) {
              const title = String(body.title || '').trim();
              if (!title || !data.teamId) return;
              const created = await actions.createIssue({
                projectId: body.projectId || '',
                teamId: data.teamId,
                title,
                body: body.body || '',
              });
              if (!created) return;
              issueId = created.id;
            }
            const updated = await actions.updateIssue(issueId, {
              status: 'todo',
              timeboxStart: dropIntent === 'todo' ? focusStart : currentStart,
              size: body.size,
              completionText: body.completionText,
              completionMode: body.completionMode,
              checks: body.checks,
            });
            if (updated) {
              if (dropIntent !== 'todo') setBoxFocus('current');
              setDropIntent(null);
              setSelected(updated);
              await refresh();
            }
          }}
          onUndo={async () => {
            const result = await actions.undo(selected.id);
            if (result) {
              setSelected(null);
              await refresh();
            }
          }}
        />
        )}
        <div className='flex min-h-0 min-w-0 flex-1 flex-col gap-1 overflow-hidden'>
          <p className='shrink-0 text-dns-14N-130 text-solid-gray-600'>
            {boxFocus === 'previous' ? '前期枠' : boxFocus === 'next' ? '次期枠' : '今期枠'}
            。期枠未定から未着手へ落とすと詳細が開き、完了条件を書いて移すまで動きません。完了へ落とすと、詳細で条件を満たすまで動きません。定常は各列の上にまとめています
          </p>
          <div className='flex min-h-0 flex-1 gap-2 overflow-x-auto'>
          {columns.map((column) => {
            const routineHere =
              column.id === 'unscheduled'
                ? routineFlat.filter((issue) => !issue.timeboxStart)
                : routineFlat.filter((issue) => issue.timeboxStart === focusStart && issue.status === column.id);
            const plansHere =
              column.id === 'unscheduled'
                ? undecided
                : planInBox.filter((issue) => issue.status === column.id);
            const piles = routinePiles(
              routineHere,
              new Map((data.templates ?? []).map((item) => [item.id, item.name])),
            );
            const dragging = [...undecided, ...planInBox].find((issue) => issue.id === draggingId);
            const source = dragging ? (dragging.timeboxStart ? dragging.status : 'unscheduled') : '';
            const acceptsDrop =
              Boolean(dragging) &&
              source !== column.id &&
              (dragging?.timeboxStart
                ? column.id !== 'unscheduled'
                : column.id === 'todo' && Boolean(data.isChief));
            return (
            <div
              key={column.id}
              className={`flex w-44 shrink-0 flex-col overflow-hidden rounded-8 p-2 md:w-auto md:min-w-40 md:flex-1 ${dropColumn === column.id ? 'bg-blue-50 outline outline-2 outline-blue-900' : 'bg-solid-gray-50'}`}
              onDragOver={(event) => {
                if (dragging && !dragging.timeboxStart && column.id === 'todo' && !acceptsDrop) {
                  event.preventDefault();
                  event.dataTransfer.dropEffect = 'none';
                  const notice = '未着手へ移すのは所属長です。';
                  if (dropNotice.current !== notice) {
                    dropNotice.current = notice;
                    actions.setError(notice);
                  }
                  return;
                }
                if (!acceptsDrop) return;
                event.preventDefault();
                event.dataTransfer.dropEffect = 'move';
                if (dropColumn !== column.id) setDropColumn(column.id);
              }}
              onDrop={(event) => {
                event.preventDefault();
                setDropColumn(null);
                setDraggingId(null);
                if (!dragging || !acceptsDrop) return;
                void dropPlan(dragging, column.id);
              }}
            >
              <p className='shrink-0 text-std-16B-170'>{column.label}</p>
              <ul className='mt-1 flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto'>
                {piles.map((pile) => {
                  const pileKey = `${column.id}:${pile.id}`;
                  const opened = openPile === pileKey;
                  return (
                    <li key={pileKey}>
                      <button
                        type='button'
                        className='w-full rounded-8 border border-blue-300 bg-blue-50 p-2 text-left'
                        aria-expanded={opened}
                        onClick={() => setOpenPile(opened ? null : pileKey)}
                      >
                        <span className='block text-dns-14N-130 text-blue-900'>定常 {pile.items.length} 件</span>
                        <span className='text-std-16N-170'>{pile.name}</span>
                        <span className='block text-dns-14N-130 text-solid-gray-700'>規模 {formatSize(pile.size)}</span>
                      </button>
                      {opened && (
                        <ul className='ml-2 mt-1 flex flex-col gap-1 border-l-2 border-blue-300 pl-2'>
                          {pile.items.map((issue) => (
                            <li key={issue.id}>
                              <button
                                type='button'
                                className={`w-full rounded-4 px-2 py-1 text-left ${selected?.id === issue.id ? 'bg-blue-100' : 'bg-blue-50 hover:bg-blue-100'}`}
                                onClick={() => setSelected(issue)}
                              >
                                <span className='block text-dns-16N-130 text-blue-900'>{issue.title}</span>
                                <span className='block text-dns-14N-130 text-solid-gray-600'>{formatWhen(issue.createdAt)}</span>
                              </button>
                            </li>
                          ))}
                        </ul>
                      )}
                    </li>
                  );
                })}
                {plansHere.map((issue) => (
                    <li key={issue.id}>
                      <button
                        type='button'
                        draggable
                        title='ドラッグして状態を変える'
                        className={`w-full cursor-grab rounded-8 border p-2 text-left active:cursor-grabbing ${selected?.id === issue.id ? 'border-blue-900 bg-blue-50' : 'border-solid-gray-300 bg-white'} ${draggingId === issue.id ? 'opacity-50' : ''}`}
                        onDragStart={(event: DragEvent<HTMLButtonElement>) => {
                          skipClick.current = true;
                          dropNotice.current = null;
                          event.dataTransfer.setData('text/plain', issue.id);
                          event.dataTransfer.effectAllowed = 'move';
                          setDraggingId(issue.id);
                        }}
                        onDragEnd={() => {
                          setDraggingId(null);
                          setDropColumn(null);
                          window.setTimeout(() => {
                            skipClick.current = false;
                          }, 0);
                        }}
                        onClick={() => {
                          if (skipClick.current) return;
                          setSelected(issue);
                        }}
                      >
                        <span className='text-std-16N-170'>{issue.title}</span>
                        <span className='block text-dns-14N-130 text-solid-gray-600'>
                          {issue.size ? `規模 ${formatSize(issue.size)}` : column.id === 'unscheduled' ? '規模は未定' : ''}
                        </span>
                      </button>
                    </li>
                  ))}
              </ul>
            </div>
            );
          })}
          </div>
        </div>
      </div>
      </div>

      <div className={pane === 'setup' ? 'min-h-0 flex-1 overflow-y-auto' : 'hidden'}>
      <Setup
        home={data}
        busy={actions.busy}
        receiptKey={receiptKey}
        onChief={async (userId) => {
          if (!data.teamId) return;
          if (await actions.appointChief(data.teamId, userId)) await refresh();
        }}
        onProject={async (body) => {
          if (await actions.createProject({ ...body, teamId: data.teamId })) await refresh();
        }}
        onUpdateProject={async (projectId, body) => {
          const updated = await actions.updateProject(projectId, body);
          if (updated) await refresh();
          return Boolean(updated);
        }}
        onDeleteProject={async (projectId) => {
          const removed = await actions.deleteProject(projectId);
          if (removed) await refresh();
          return Boolean(removed);
        }}
        onTemplate={async (body) => {
          if (await actions.createTemplate(body)) await refresh();
        }}
        onUpdateTemplate={async (templateId, body) => {
          const updated = await actions.updateTemplate(templateId, body);
          if (updated) await refresh();
          return Boolean(updated);
        }}
        onDeleteTemplate={async (templateId) => {
          const removed = await actions.deleteTemplate(templateId);
          if (removed) await refresh();
          return Boolean(removed);
        }}
        onHeadcount={async (count) => {
          if (!data.teamId) return;
          if (await actions.setHeadcount(data.teamId, count)) await refresh();
        }}
        onReceipt={async (templateId) => {
          const issued = await actions.receiptKey(templateId);
          if (issued?.receiptKey) {
            setReceiptKey(issued.receiptKey);
            await refresh();
          }
        }}
      />
      </div>
      </>
      )}
    </Shell>
  );
};

const BoxButton = ({
  active,
  title,
  meaning,
  start,
  end,
  size,
  sizeLabel,
  onClick,
}: {
  active: boolean;
  title: string;
  meaning: string;
  start?: string;
  end?: string;
  size: number;
  sizeLabel: string;
  onClick: () => void;
}) => (
  <button
    type='button'
    aria-pressed={active}
    onClick={onClick}
    className={
      active
        ? 'rounded-8 border-2 border-blue-900 bg-blue-50 px-3 py-2 text-left'
        : 'rounded-8 border border-solid-gray-300 bg-white px-3 py-2 text-left hover:bg-solid-gray-50'
    }
  >
    <span className='flex items-baseline justify-between gap-2'>
      <span className='text-std-16B-170'>{title}</span>
      <span className='text-std-16B-170'>
        {sizeLabel} {size}
      </span>
    </span>
    <span className='mt-0.5 block text-dns-14N-130 text-solid-gray-700'>
      {start && end ? `${start} から ${end}` : '期間はまだありません'}
    </span>
    <span className='block text-dns-14N-130 text-solid-gray-600'>{meaning}</span>
  </button>
);

const LoadBar = ({
  plan,
  routine,
  leave,
  reserve,
  pace,
  note,
}: {
  plan: number;
  routine: number;
  leave: number;
  reserve: number;
  pace: number;
  note: string;
}) => {
  const total = plan + routine + leave + reserve;
  const max = Math.max(total, pace, 1);
  const width = (value: number) => `${(value / max) * 100}%`;
  const parts = [
    { label: '計画', value: plan, className: 'bg-blue-900' },
    { label: '定常', value: routine, className: 'bg-blue-300' },
    { label: '休み', value: leave, className: 'bg-solid-gray-420' },
    { label: '見込みの定常', value: reserve, className: 'bg-blue-100' },
  ].filter((part) => part.value > 0);
  return (
    <div className='shrink-0'>
      <div className='relative h-3 rounded-full bg-solid-gray-100' role='img' aria-label={note}>
        <div className='flex h-full overflow-hidden rounded-full'>
          {parts.map((part) => (
            <div key={part.label} className={part.className} style={{ width: width(part.value) }} />
          ))}
        </div>
        {pace > 0 && (
          <div
            className='absolute top-[-3px] h-5 w-0.5 bg-solid-gray-900'
            style={{ left: width(pace) }}
          />
        )}
      </div>
      <p className='mt-1 flex flex-wrap gap-x-3 text-dns-14N-130 text-solid-gray-700'>
        {parts.map((part) => (
          <span key={part.label} className='inline-flex items-center gap-1'>
            <span className={`inline-block size-3 ${part.className}`} />
            {part.label} {formatSize(part.value)}
          </span>
        ))}
        {pace > 0 && <span>線は前期枠でこなした {formatSize(pace)}</span>}
      </p>
      <p className='text-dns-14N-130 text-solid-gray-800'>{note}</p>
    </div>
  );
};

const IssuePanel = ({
  issue,
  projects,
  isChief,
  currentStart,
  busy,
  onClose,
  onStatus,
  onComplete,
  onCheck,
  onComment,
  onPlace,
  onSave,
  onAccept,
  onUndo,
  dropIntent = null,
  acceptLabel,
  templateName = '',
}: {
  issue: NishukanIssue;
  projects: NishukanProject[];
  isChief: boolean;
  currentStart: string;
  busy: boolean;
  onClose: () => void;
  onStatus: (status: string) => void;
  onComplete: () => void;
  onCheck: (checkId: string, done: boolean) => void;
  onComment: (body: string) => void;
  onPlace: () => void;
  onSave: (body: Record<string, unknown>) => void;
  onAccept: (body: {
    title?: string;
    body?: string;
    projectId?: string;
    size: number;
    completionText?: string;
    completionMode?: string;
    checks?: string[];
  }) => void;
  onUndo: () => void;
  dropIntent?: 'todo' | 'done' | null;
  acceptLabel: string;
  templateName?: string;
}) => {
  const [comment, setComment] = useState('');
  const [title, setTitle] = useState(issue.title);
  const [doneText, setDoneText] = useState(issue.completionText);
  const [doneMode, setDoneMode] = useState(issue.completionMode || 'chief');
  const [checkText, setCheckText] = useState(issue.checks.map((check) => check.label).join('\n'));
  const [placeSize, setPlaceSize] = useState(issue.size ? formatSize(issue.size) : '1');
  const [reviseSize, setReviseSize] = useState(issue.size ? formatSize(issue.size) : '1');
  const [note, setNote] = useState(issue.body);
  const [projectChoice, setProjectChoice] = useState(issue.projectKey ? issue.projectId : '');
  const unscheduled = !issue.timeboxStart;
  const draftRoutine = !issue.id && Boolean(issue.templateId);
  const projectChoices = projects.filter((project) => (issue.templateId ? project.mode === 'routine' : project.mode === 'plan'));
  const checks = checkText.split('\n').map((line) => line.trim()).filter(Boolean);
  const completionReady = Boolean(doneText.trim()) && (doneMode !== 'objective' || checks.length > 0);
  useEffect(() => {
    setTitle(issue.title);
    setDoneText(issue.completionText);
    setDoneMode(issue.completionMode || 'chief');
    setCheckText(issue.checks.map((check) => check.label).join('\n'));
    setPlaceSize(issue.size ? formatSize(issue.size) : '1');
    setReviseSize(issue.size ? formatSize(issue.size) : '1');
    setNote(issue.body);
    setProjectChoice(issue.projectKey ? issue.projectId : '');
  }, [issue]);
  const completionBody = () => ({
    completionText: doneText.trim(),
    completionMode: doneMode,
    checks: doneMode === 'objective' ? checks : [],
  });
  const saveTitle = () => {
    const next = title.trim();
    if (!next) {
      if (issue.id) setTitle(issue.title);
      return;
    }
    if (!issue.id) {
      onSave({
        title: next,
        body: note,
        projectId: projectChoice,
        ...(isChief ? completionBody() : {}),
      });
      return;
    }
    if (next === issue.title) return;
    onSave({ title: next });
  };
  const saveCompletion = () => {
    if (!issue.id || !isChief || !unscheduled) return;
    const sameText = doneText.trim() === issue.completionText;
    const sameMode = doneMode === (issue.completionMode || 'chief');
    const sameChecks = checkText.trim() === issue.checks.map((check) => check.label).join('\n');
    if (sameText && sameMode && sameChecks) return;
    onSave(completionBody());
  };
  const placeHint = !title.trim()
    ? '名称を書くと、この作業を残せます。'
    : !doneText.trim()
      ? '完了条件を書くと、今期枠の未着手に移せます。'
      : doneMode === 'objective' && checks.length === 0
        ? '確認項目を書くと、今期枠の未着手に移せます。'
        : '選んだ規模で、今期枠の未着手に入ります。';
  return (
    <CustomDialog isOpen onClose={onClose}>
      <CustomDialogPanel className='flex !h-[calc(100dvh-2rem)] !max-h-[calc(100dvh-2rem)] !w-[calc(100vw-2rem)] !max-w-none flex-col overflow-hidden text-left'>
        <CustomDialogHeader hasClose onClose={onClose}>
          作業
        </CustomDialogHeader>
        <CustomDialogBody className='min-h-0 flex-1 overflow-y-auto'>
          <Label htmlFor='nishukan-issue-title' size='sm'>
            名称
          </Label>
          <input
            id='nishukan-issue-title'
            className={`${fieldClass} text-std-20B-150`}
            value={title}
            placeholder={draftRoutine ? 'この1件の名称' : 'この作業の名称'}
            autoFocus={!issue.id}
            onChange={(e) => setTitle(e.target.value)}
            onBlur={saveTitle}
            onKeyDown={(e) => {
              if (e.key === 'Enter') e.currentTarget.blur();
            }}
          />
          <p className='mt-1 text-dns-14N-130 text-solid-gray-700'>
            {draftRoutine
              ? `${templateName}の1件です。この作業が何か、名称で書きます。書かずに閉じると残りません。`
              : '名称で、何の仕事か分かるように書きます。'}
          </p>
          <p className='mt-3 text-dns-16N-130'>
            状態: {draftRoutine ? '名称を書くと、今期枠の未着手になります' : unscheduled ? '期枠未定' : statusLabel(issue.status)}
          </p>
          {unscheduled && (
            <div className='mt-4 flex flex-col gap-3'>
              <p className='text-dns-16N-130 text-solid-gray-700'>
                {dropIntent === 'todo'
                  ? '完了条件を書いて移すまで、この作業は期枠未定のままです。閉じると、ドラッグは成立しません。'
                  : '期枠未定です。完了条件はこのあいだに書きます。今期枠で行うと判断したとき、未着手へ移して規模を置きます。'}
              </p>
              {isChief ? (
                <>
                  <Label htmlFor='nishukan-accept-done' size='sm'>
                    完了条件
                  </Label>
                  <textarea
                    id='nishukan-accept-done'
                    className={fieldClass}
                    rows={3}
                    value={doneText}
                    autoFocus={dropIntent === 'todo'}
                    onChange={(e) => setDoneText(e.target.value)}
                    onBlur={saveCompletion}
                    placeholder='何がそろえば終わりか'
                  />
                  <Label htmlFor='nishukan-accept-mode' size='sm'>
                    決め方
                  </Label>
                  <select
                    id='nishukan-accept-mode'
                    className={fieldClass}
                    value={doneMode}
                    onChange={(e) => {
                      const mode = e.target.value;
                      setDoneMode(mode);
                      if (!issue.id || !isChief || !unscheduled) return;
                      onSave({
                        completionText: doneText.trim(),
                        completionMode: mode,
                        checks: mode === 'objective' ? checks : [],
                      });
                    }}
                  >
                    <option value='chief'>所属長の判定</option>
                    <option value='objective'>客観評価</option>
                  </select>
                  {doneMode === 'objective' && (
                    <>
                      <Label htmlFor='nishukan-accept-checks' size='sm'>
                        確認項目（1行に1つ）
                      </Label>
                      <textarea
                        id='nishukan-accept-checks'
                        className={fieldClass}
                        rows={3}
                        value={checkText}
                        onChange={(e) => setCheckText(e.target.value)}
                        onBlur={saveCompletion}
                      />
                    </>
                  )}
                  <div className='flex flex-col items-start gap-2'>
                    <Label htmlFor='nishukan-accept-size' size='sm'>
                      今期枠で行うときの規模
                    </Label>
                    <select id='nishukan-accept-size' className={compactField} value={placeSize} onChange={(e) => setPlaceSize(e.target.value)}>
                      {SIZE_OPTIONS.map((n) => (
                        <option key={n} value={n}>
                          {n}
                        </option>
                      ))}
                    </select>
                    <p className='text-dns-14N-130 text-solid-gray-700'>{placeHint}</p>
                    <Button
                      type='button'
                      variant='solid-fill'
                      size='sm'
                      aria-disabled={busy || !title.trim() || !completionReady}
                      onClick={() =>
                        onAccept({
                          title: title.trim(),
                          body: note,
                          projectId: projectChoice,
                          size: Number(placeSize),
                          ...completionBody(),
                        })
                      }
                    >
                      {acceptLabel}
                    </Button>
                  </div>
                </>
              ) : (
                <p className='text-dns-16N-130'>
                  {issue.completionText ? `完了条件: ${issue.completionText}` : '完了条件と規模は、所属長が期枠未定のあいだに置きます。'}
                </p>
              )}
            </div>
          )}
          {!unscheduled && issue.completionText && (
            <p className='mt-4 text-std-16N-170'>完了条件: {issue.completionText}</p>
          )}
          {dropIntent === 'done' && issue.status !== 'done' && (
            <p className='mt-4 text-dns-16N-130 text-solid-gray-700'>
              {issue.completionMode === 'objective'
                ? '確認項目をすべて入れるまで、完了には動きません。閉じると、今の状態のままです。'
                : '所属長が完了にするまで、完了には動きません。閉じると、今の状態のままです。'}
            </p>
          )}
          {draftRoutine && issue.size != null && (
            <p className='mt-4 text-dns-16N-130'>規模 {formatSize(issue.size)}</p>
          )}
          {!unscheduled && issue.id && (
            <div className='mt-4 flex flex-wrap gap-2'>
              {STATUS.filter((s) => s.id !== 'done' && s.id !== issue.status).map((s) => (
                <Button key={s.id} type='button' variant='outline' size='sm' aria-disabled={busy} onClick={() => onStatus(s.id)}>
                  {s.label}にする
                </Button>
              ))}
              {isChief && issue.completionMode === 'chief' && issue.status !== 'done' && (
                <Button type='button' variant='solid-fill' size='sm' aria-disabled={busy} onClick={onComplete}>
                  所属長として完了にする
                </Button>
              )}
              {isChief && issue.timeboxStart !== currentStart && issue.completionText && (
                <Button type='button' variant='outline' size='sm' aria-disabled={busy} onClick={onPlace}>
                  今期枠へ入れる
                </Button>
              )}
            </div>
          )}
          {!unscheduled && issue.id && isChief && issue.kind !== 'leave' && (
            <div className='mt-4 flex flex-col items-start gap-2'>
              <Label htmlFor='nishukan-revise-size' size='sm'>
                規模
              </Label>
              <select
                id='nishukan-revise-size'
                className={compactField}
                value={reviseSize}
                onChange={(e) => {
                  setReviseSize(e.target.value);
                  onSave({ size: Number(e.target.value) });
                }}
              >
                {SIZE_OPTIONS.map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
              <p className='text-dns-14N-130 text-solid-gray-700'>選び直すと、その規模で保存されます。</p>
            </div>
          )}
          {issue.kind !== 'leave' && (
            <div className='mt-4 flex flex-col gap-2'>
              <Label htmlFor='nishukan-project-choice' size='sm'>
                事業
              </Label>
              <select
                id='nishukan-project-choice'
                className={`${compactField} min-w-48`}
                disabled={draftRoutine}
                value={projectChoice}
                onChange={(e) => {
                  const value = e.target.value;
                  setProjectChoice(value);
                  if (!issue.id) return;
                  onSave({ projectId: value });
                }}
              >
                {!issue.templateId && <option value=''>事業未定</option>}
                {projectChoices.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
              </select>
              <p className='text-dns-14N-130 text-solid-gray-700'>事業は識別のためのまとまりです。決まっていなければ、このまま進められます。</p>
            </div>
          )}
          <div className='mt-4 flex flex-col gap-2'>
            <Label htmlFor='nishukan-note' size='sm'>
              メモ
            </Label>
            <textarea
              id='nishukan-note'
              className={fieldClass}
              rows={6}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              onBlur={() => {
                if (!issue.id || note === issue.body) return;
                onSave({ body: note });
              }}
              placeholder='経過や、参照するファイル・フォルダのリンク'
            />
            {noteLinks(note).map((url) => (
              <a key={url} href={url} target='_blank' rel='noreferrer' className='block truncate text-dns-16N-130 text-blue-900 underline'>
                {url}
              </a>
            ))}
          </div>
          {!unscheduled && issue.id && issue.checks.length > 0 && (
            <ul className='mt-4 flex flex-col gap-2'>
              {issue.checks.map((check) => (
                <li key={check.id}>
                  <label className='flex items-center gap-2 text-std-16N-170'>
                    <input type='checkbox' checked={check.done} onChange={(e) => onCheck(check.id, e.target.checked)} />
                    {check.label}
                  </label>
                </li>
              ))}
            </ul>
          )}
          {issue.id && (
            <div className='mt-4'>
              <Button type='button' variant='text' size='sm' aria-disabled={busy} onClick={onUndo}>
                直後なら取り消す
              </Button>
            </div>
          )}
          <form
            className='mt-4 flex flex-col gap-2'
            onSubmit={(e) => {
              e.preventDefault();
              if (!issue.id || !comment.trim()) return;
              onComment(comment.trim());
              setComment('');
            }}
          >
            <Label htmlFor='nishukan-comment' size='sm'>
              コメント
            </Label>
            <textarea id='nishukan-comment' className={fieldClass} rows={2} value={comment} onChange={(e) => setComment(e.target.value)} />
            <div>
              <Button type='submit' variant='outline' size='sm' aria-disabled={busy || !issue.id || !comment.trim()}>
                書く
              </Button>
            </div>
          </form>
          <ul className='mt-3 flex flex-col gap-2'>
            {issue.comments.map((c) => (
              <li key={c.id} className='text-dns-16N-130'>
                <span className='text-solid-gray-600'>{c.author}</span> {c.body}
              </li>
            ))}
          </ul>
        </CustomDialogBody>
      </CustomDialogPanel>
    </CustomDialog>
  );
};

const Setup = ({
  home,
  busy,
  receiptKey,
  onChief,
  onProject,
  onUpdateProject,
  onDeleteProject,
  onTemplate,
  onUpdateTemplate,
  onDeleteTemplate,
  onHeadcount,
  onReceipt,
}: {
  home: NishukanHome;
  busy: boolean;
  receiptKey: string | null;
  onChief: (userId: string) => void;
  onProject: (body: Record<string, string>) => void;
  onUpdateProject: (projectId: string, body: Record<string, string>) => Promise<boolean>;
  onDeleteProject: (projectId: string) => Promise<boolean>;
  onTemplate: (body: Record<string, unknown>) => void;
  onUpdateTemplate: (templateId: string, body: Record<string, unknown>) => Promise<boolean>;
  onDeleteTemplate: (templateId: string) => Promise<boolean>;
  onHeadcount: (count: number) => void;
  onReceipt: (templateId: string) => void;
}) => {
  const [chief, setChief] = useState('');
  const [headcount, setHeadcount] = useState(home.headcount ? String(home.headcount) : '');
  const [projectName, setProjectName] = useState('');
  const [projectKey, setProjectKey] = useState('');
  const [projectMode, setProjectMode] = useState('plan');
  const [templateProject, setTemplateProject] = useState('');
  const [templateName, setTemplateName] = useState('');
  const [templateSize, setTemplateSize] = useState('1');
  const [templateDone, setTemplateDone] = useState('');
  const [templateMode, setTemplateMode] = useState('objective');
  const [templateCheck, setTemplateCheck] = useState('');
  const [editingProject, setEditingProject] = useState<string | null>(null);
  const [projectDraft, setProjectDraft] = useState({ name: '', key: '', mode: 'plan' });
  const [editingTemplate, setEditingTemplate] = useState<string | null>(null);
  const [templateDraft, setTemplateDraft] = useState({
    projectId: '',
    name: '',
    size: '1',
    completionText: '',
    completionMode: 'chief',
    checks: '',
  });
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const routine = (home.projects ?? []).filter((p) => p.mode === 'routine');
  const tabs = [
    (home.isAdmin || home.isChief) && { id: 'team', label: '体制' },
    home.isAdmin && { id: 'project', label: '事業' },
    home.isChief && { id: 'template', label: '定型' },
    home.isChief && { id: 'receipt', label: '受付' },
  ].filter((item): item is { id: string; label: string } => Boolean(item));
  const tabIds = tabs.map((item) => item.id).join(',');
  const [tab, setTab] = useState(tabs[0]?.id ?? 'team');
  useEffect(() => {
    setHeadcount(home.headcount ? String(home.headcount) : '');
  }, [home.headcount]);
  useEffect(() => {
    const ids = tabIds ? tabIds.split(',') : [];
    if (!ids.includes(tab)) setTab(ids[0] ?? 'team');
  }, [tabIds, tab]);

  const submit =
    (fn: () => void) =>
    (e: FormEvent) => {
      e.preventDefault();
      fn();
    };

  return (
    <div className='flex min-h-0 flex-col gap-3 pb-2'>
      {!home.isAdmin && !home.isChief && (
        <p className='text-std-16N-170 text-solid-gray-700'>
          人数と所属長は、所属長かチームの管理者が登録します。事業は管理者が、定型と受付の鍵は所属長が登録します。
        </p>
      )}
      {tabs.length > 0 && (
        <div role='tablist' aria-label='チーム設定の分類' className='sticky top-0 z-10 flex gap-1 overflow-x-auto border-b border-solid-gray-300 bg-white'>
          {tabs.map((item) => (
            <button
              key={item.id}
              type='button'
              role='tab'
              aria-selected={tab === item.id}
              className={tabClass(tab === item.id)}
              onClick={() => setTab(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}

      {tab === 'team' && (home.isAdmin || home.isChief) && (
        <div className='flex max-w-2xl flex-col gap-6'>
          <p className='m-0 text-std-16N-170 text-solid-gray-800'>
            チームの人数と、期枠の中身を決める所属長を置きます。ここにあるのは、期枠ごとではなくチームに対する設定です。
          </p>
          <form className='flex flex-col gap-2' onSubmit={submit(() => onHeadcount(Number(headcount)))}>
            <h2 className='m-0 text-std-16B-170'>人数</h2>
            <p className='m-0 text-std-16N-170 text-solid-gray-700'>
              同時に働ける人数です。祝日が1日あると、その日は全員が休むものとして、人数ぶんの規模が期枠から引かれます。5人なら、祝日1日で規模5です。いまの人数は {home.headcount ?? '未設定'} です。
            </p>
            <Label htmlFor='nishukan-headcount' size='sm'>
              チームの人数
            </Label>
            <input
              id='nishukan-headcount'
              type='number'
              min={1}
              className={fieldClass}
              value={headcount}
              onChange={(e) => setHeadcount(e.target.value)}
            />
            <div>
              <Button type='submit' variant='outline' size='sm' aria-disabled={busy || Number(headcount) < 1}>
                保存する
              </Button>
            </div>
          </form>
          {home.isAdmin && (
            <form className='flex flex-col gap-2' onSubmit={submit(() => onChief(chief))}>
              <h2 className='m-0 text-std-16B-170'>所属長</h2>
              <p className='m-0 text-std-16N-170 text-solid-gray-700'>
                今期枠にどの作業を入れるか、規模、完了の判定を決める人です。チームに一人だけ任命します。いまの所属長は {home.chiefUserId || '未設定'} です。
              </p>
              <Label htmlFor='nishukan-chief' size='sm'>
                利用者 ID
              </Label>
              <p className='m-0 text-dns-14N-130 text-solid-gray-600'>ログインに使っている ID を書きます。</p>
              <input id='nishukan-chief' className={fieldClass} value={chief} onChange={(e) => setChief(e.target.value)} />
              <div>
                <Button type='submit' variant='outline' size='sm' aria-disabled={busy || !chief.trim()}>
                  任命する
                </Button>
              </div>
            </form>
          )}
        </div>
      )}

      {tab === 'project' && home.isAdmin && (
        <div className='flex max-w-2xl flex-col gap-4'>
          <p className='m-0 text-std-16N-170 text-solid-gray-800'>
            事業は、作業を束ねる名前です。庁内DX推進のように、どの取り組みの仕事かを表します。作業を書いた時点で事業が決まっていなくても、作業は残せます。事業そのものは期枠には入りません。名前と記号は後から直せます。作業や定型が残っているあいだは、進め方は変えられず、事業も消せません。
          </p>
          {(home.projects ?? []).length > 0 && (
            <ul className='m-0 flex list-none flex-col gap-3 p-0'>
              {home.projects?.map((project) => (
                <li key={project.id} className='flex flex-col gap-2 border-b border-solid-gray-200 pb-3'>
                  {editingProject === project.id ? (
                    <form
                      className='flex flex-col gap-2'
                      onSubmit={submit(async () => {
                        if (await onUpdateProject(project.id, projectDraft)) setEditingProject(null);
                      })}
                    >
                      <Label htmlFor={`nishukan-edit-project-name-${project.id}`} size='sm'>
                        名前
                      </Label>
                      <input
                        id={`nishukan-edit-project-name-${project.id}`}
                        className={fieldClass}
                        value={projectDraft.name}
                        onChange={(e) => setProjectDraft({ ...projectDraft, name: e.target.value })}
                      />
                      <Label htmlFor={`nishukan-edit-project-key-${project.id}`} size='sm'>
                        記号
                      </Label>
                      <input
                        id={`nishukan-edit-project-key-${project.id}`}
                        className={fieldClass}
                        value={projectDraft.key}
                        onChange={(e) => setProjectDraft({ ...projectDraft, key: e.target.value })}
                      />
                      <Label htmlFor={`nishukan-edit-project-mode-${project.id}`} size='sm'>
                        進め方
                      </Label>
                      <select
                        id={`nishukan-edit-project-mode-${project.id}`}
                        className={fieldClass}
                        value={projectDraft.mode}
                        onChange={(e) => setProjectDraft({ ...projectDraft, mode: e.target.value })}
                      >
                        <option value='plan'>計画</option>
                        <option value='routine'>定常</option>
                      </select>
                      <div className='flex gap-2'>
                        <Button type='submit' variant='outline' size='sm' aria-disabled={busy}>
                          保存する
                        </Button>
                        <Button type='button' variant='text' size='sm' onClick={() => setEditingProject(null)}>
                          やめる
                        </Button>
                      </div>
                    </form>
                  ) : (
                    <div className='flex flex-wrap items-center gap-2'>
                      <span className='text-dns-16N-130'>
                        {project.name}
                        <span className='text-solid-gray-600'>（{project.mode === 'routine' ? '定常' : '計画'}）</span>
                      </span>
                      <Button
                        type='button'
                        variant='outline'
                        size='sm'
                        onClick={() => {
                          setConfirmId(null);
                          setEditingProject(project.id);
                          setProjectDraft({ name: project.name, key: project.key, mode: project.mode });
                        }}
                      >
                        直す
                      </Button>
                      <Button type='button' variant='text' size='sm' onClick={() => setConfirmId(project.id)}>
                        消す
                      </Button>
                    </div>
                  )}
                  {confirmId === project.id && (
                    <div className='flex flex-wrap items-center gap-2'>
                      <p className='m-0 text-dns-14N-130 text-solid-gray-700'>作業や定型が残っていなければ消せます。</p>
                      <Button
                        type='button'
                        variant='outline'
                        size='sm'
                        aria-disabled={busy}
                        onClick={async () => {
                          if (await onDeleteProject(project.id)) setConfirmId(null);
                        }}
                      >
                        消す
                      </Button>
                      <Button type='button' variant='text' size='sm' onClick={() => setConfirmId(null)}>
                        やめる
                      </Button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
          <form
            className='flex flex-col gap-2'
            onSubmit={submit(() =>
              onProject({ name: projectName, key: projectKey, mode: projectMode }),
            )}
          >
            <h2 className='m-0 text-std-16B-170'>事業を作る</h2>
            <Label htmlFor='nishukan-project-name' size='sm'>
              名前
            </Label>
            <p className='m-0 text-dns-14N-130 text-solid-gray-600'>取り組みの名前です。画面の事業の選択に出ます。</p>
            <input id='nishukan-project-name' className={fieldClass} value={projectName} onChange={(e) => setProjectName(e.target.value)} />
            <Label htmlFor='nishukan-project-key' size='sm'>
              記号
            </Label>
            <p className='m-0 text-dns-14N-130 text-solid-gray-600'>事業を短く示す印です。カードには出ません。</p>
            <input id='nishukan-project-key' className={fieldClass} value={projectKey} onChange={(e) => setProjectKey(e.target.value)} />
            <Label htmlFor='nishukan-project-mode' size='sm'>
              進め方
            </Label>
            <p className='m-0 text-dns-14N-130 text-solid-gray-600'>計画は期枠で進める仕事、定常は繰り返し来る仕事のまとまりです。定型は定常の事業に作ります。</p>
            <select id='nishukan-project-mode' className={fieldClass} value={projectMode} onChange={(e) => setProjectMode(e.target.value)}>
              <option value='plan'>計画</option>
              <option value='routine'>定常</option>
            </select>
            <div>
              <Button type='submit' variant='outline' size='sm' aria-disabled={busy}>
                作る
              </Button>
            </div>
          </form>
        </div>
      )}

      {tab === 'template' && home.isChief && (
        <div className='flex max-w-2xl flex-col gap-4'>
          <p className='m-0 text-std-16N-170 text-solid-gray-800'>
            定型は分類の名前です。定常は、その分類から来る1件ずつの仕事です。窓口相談や他課からの依頼のような名前が、通常の画面のボタンになります。ボタンを押したあと、その1件の名称を書きます。直した規模と完了条件は、これからの1件に使います。すでに入っている作業はそのままです。定型を消すとボタンは出なくなりますが、入っている作業は残ります。
          </p>
          {(home.templates ?? []).length > 0 && (
            <ul className='m-0 flex list-none flex-col gap-3 p-0'>
              {home.templates?.map((template) => (
                <li key={template.id} className='flex flex-col gap-2 border-b border-solid-gray-200 pb-3'>
                  {editingTemplate === template.id ? (
                    <form
                      className='flex flex-col gap-2'
                      onSubmit={submit(async () => {
                        const saved = await onUpdateTemplate(template.id, {
                          projectId: templateDraft.projectId,
                          name: templateDraft.name,
                          size: Number(templateDraft.size),
                          completionText: templateDraft.completionText,
                          completionMode: templateDraft.completionMode,
                          checks: templateDraft.checks
                            .split('\n')
                            .map((line) => line.trim())
                            .filter(Boolean),
                        });
                        if (saved) setEditingTemplate(null);
                      })}
                    >
                      <Label htmlFor={`nishukan-edit-template-project-${template.id}`} size='sm'>
                        定常の事業
                      </Label>
                      <select
                        id={`nishukan-edit-template-project-${template.id}`}
                        className={fieldClass}
                        value={templateDraft.projectId}
                        onChange={(e) => setTemplateDraft({ ...templateDraft, projectId: e.target.value })}
                      >
                        {routine.map((item) => (
                          <option key={item.id} value={item.id}>
                            {item.name}
                          </option>
                        ))}
                      </select>
                      <Label htmlFor={`nishukan-edit-template-name-${template.id}`} size='sm'>
                        分類の名前
                      </Label>
                      <input
                        id={`nishukan-edit-template-name-${template.id}`}
                        className={fieldClass}
                        value={templateDraft.name}
                        onChange={(e) => setTemplateDraft({ ...templateDraft, name: e.target.value })}
                      />
                      <Label htmlFor={`nishukan-edit-template-size-${template.id}`} size='sm'>
                        規模
                      </Label>
                      <select
                        id={`nishukan-edit-template-size-${template.id}`}
                        className={fieldClass}
                        value={templateDraft.size}
                        onChange={(e) => setTemplateDraft({ ...templateDraft, size: e.target.value })}
                      >
                        {SIZE_OPTIONS.map((n) => (
                          <option key={n} value={n}>
                            {n}
                          </option>
                        ))}
                      </select>
                      <Label htmlFor={`nishukan-edit-template-done-${template.id}`} size='sm'>
                        完了条件
                      </Label>
                      <input
                        id={`nishukan-edit-template-done-${template.id}`}
                        className={fieldClass}
                        value={templateDraft.completionText}
                        onChange={(e) => setTemplateDraft({ ...templateDraft, completionText: e.target.value })}
                      />
                      <Label htmlFor={`nishukan-edit-template-mode-${template.id}`} size='sm'>
                        決め方
                      </Label>
                      <select
                        id={`nishukan-edit-template-mode-${template.id}`}
                        className={fieldClass}
                        value={templateDraft.completionMode}
                        onChange={(e) => setTemplateDraft({ ...templateDraft, completionMode: e.target.value })}
                      >
                        <option value='objective'>客観評価</option>
                        <option value='chief'>所属長の判定</option>
                      </select>
                      <Label htmlFor={`nishukan-edit-template-checks-${template.id}`} size='sm'>
                        確認項目
                      </Label>
                      <textarea
                        id={`nishukan-edit-template-checks-${template.id}`}
                        className={fieldClass}
                        rows={3}
                        value={templateDraft.checks}
                        onChange={(e) => setTemplateDraft({ ...templateDraft, checks: e.target.value })}
                      />
                      <div className='flex gap-2'>
                        <Button type='submit' variant='outline' size='sm' aria-disabled={busy}>
                          保存する
                        </Button>
                        <Button type='button' variant='text' size='sm' onClick={() => setEditingTemplate(null)}>
                          やめる
                        </Button>
                      </div>
                    </form>
                  ) : (
                    <div className='flex flex-wrap items-center gap-2'>
                      <span className='text-dns-16N-130'>
                        {template.name}
                        <span className='text-solid-gray-600'>（規模 {formatSize(template.size)}）</span>
                      </span>
                      <Button
                        type='button'
                        variant='outline'
                        size='sm'
                        onClick={() => {
                          setConfirmId(null);
                          setEditingTemplate(template.id);
                          setTemplateDraft({
                            projectId: template.projectId,
                            name: template.name,
                            size: formatSize(template.size),
                            completionText: template.completionText,
                            completionMode: template.completionMode,
                            checks: template.checks.join('\n'),
                          });
                        }}
                      >
                        直す
                      </Button>
                      <Button type='button' variant='text' size='sm' onClick={() => setConfirmId(template.id)}>
                        消す
                      </Button>
                    </div>
                  )}
                  {confirmId === template.id && (
                    <div className='flex flex-wrap items-center gap-2'>
                      <p className='m-0 text-dns-14N-130 text-solid-gray-700'>ボタンは出なくなります。入っている作業は残ります。</p>
                      <Button
                        type='button'
                        variant='outline'
                        size='sm'
                        aria-disabled={busy}
                        onClick={async () => {
                          if (await onDeleteTemplate(template.id)) setConfirmId(null);
                        }}
                      >
                        消す
                      </Button>
                      <Button type='button' variant='text' size='sm' onClick={() => setConfirmId(null)}>
                        やめる
                      </Button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
          <form
            className='flex flex-col gap-2'
            onSubmit={submit(() =>
              onTemplate({
                projectId: templateProject,
                name: templateName,
                size: Number(templateSize),
                priority: 'normal',
                completionText: templateDone,
                completionMode: templateMode,
                checks: templateCheck
                  .split('\n')
                  .map((s) => s.trim())
                  .filter(Boolean),
              }),
            )}
          >
            <h2 className='m-0 text-std-16B-170'>定型を登録する</h2>
            {routine.length === 0 && (
              <p className='m-0 text-std-16N-170 text-solid-gray-700'>先に、進め方を定常にした事業を作っておきます。事業を作れるのはチームの管理者です。</p>
            )}
            <Label htmlFor='nishukan-template-project' size='sm'>
              定常の事業
            </Label>
            <p className='m-0 text-dns-14N-130 text-solid-gray-600'>この分類を置く事業です。</p>
            <select id='nishukan-template-project' className={fieldClass} value={templateProject} onChange={(e) => setTemplateProject(e.target.value)}>
              <option value=''>選ぶ</option>
              {routine.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            <Label htmlFor='nishukan-template-name' size='sm'>
              分類の名前
            </Label>
            <p className='m-0 text-dns-14N-130 text-solid-gray-600'>ボタンに出る名前です。1件ごとの名称は、ボタンを押したあとに書きます。</p>
            <input id='nishukan-template-name' className={fieldClass} value={templateName} onChange={(e) => setTemplateName(e.target.value)} />
            <Label htmlFor='nishukan-template-size' size='sm'>
              規模
            </Label>
            <p className='m-0 text-dns-14N-130 text-solid-gray-600'>この分類の初期の規模です。1は1人の1日、最小は0.25です。1件ごとに後から変えられます。</p>
            <select id='nishukan-template-size' className={fieldClass} value={templateSize} onChange={(e) => setTemplateSize(e.target.value)}>
              {SIZE_OPTIONS.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
            <Label htmlFor='nishukan-template-done' size='sm'>
              完了条件
            </Label>
            <p className='m-0 text-dns-14N-130 text-solid-gray-600'>この分類の仕事が終わったと言える状態です。新しい1件にコピーされます。</p>
            <input id='nishukan-template-done' className={fieldClass} value={templateDone} onChange={(e) => setTemplateDone(e.target.value)} />
            <Label htmlFor='nishukan-template-mode' size='sm'>
              決め方
            </Label>
            <p className='m-0 text-dns-14N-130 text-solid-gray-600'>客観評価は確認項目が揃ったら完了です。所属長の判定は、所属長が完了にします。</p>
            <select id='nishukan-template-mode' className={fieldClass} value={templateMode} onChange={(e) => setTemplateMode(e.target.value)}>
              <option value='objective'>客観評価</option>
              <option value='chief'>所属長の判定</option>
            </select>
            <Label htmlFor='nishukan-template-checks' size='sm'>
              確認項目
            </Label>
            <p className='m-0 text-dns-14N-130 text-solid-gray-600'>客観評価のときに、揃ったかを見る項目です。1行に1つ書きます。</p>
            <textarea id='nishukan-template-checks' className={fieldClass} rows={3} value={templateCheck} onChange={(e) => setTemplateCheck(e.target.value)} />
            <div>
              <Button type='submit' variant='outline' size='sm' aria-disabled={busy}>
                登録する
              </Button>
            </div>
          </form>
        </div>
      )}

      {tab === 'receipt' && home.isChief && (
        <div className='flex max-w-2xl flex-col gap-3'>
          <h2 className='m-0 text-std-16B-170'>受付の鍵</h2>
          <p className='m-0 text-std-16N-170 text-solid-gray-800'>
            窓口のシステムなど、外の仕組みから定常の仕事を1件足すときに使います。定型ごとに鍵を発行します。表示されるのは発行した直後だけなので、控えてから渡してください。
          </p>
          <p className='m-0 text-dns-14N-130 text-solid-gray-600'>
            受け取る側は、POST /api/nishukan/arrivals/定型ID に X-Receipt-Key を付けて呼びます。
          </p>
          {(home.templates ?? []).length === 0 && (
            <p className='m-0 text-std-16N-170 text-solid-gray-700'>先に定型を登録すると、分類ごとに鍵を発行できます。</p>
          )}
          <ul className='m-0 flex list-none flex-col gap-2 p-0'>
            {home.templates?.map((template) => (
              <li key={template.id} className='flex items-center gap-2'>
                <span className='text-dns-16N-130'>
                  {template.name}
                  {template.hasReceiptKey ? `（発行済み ${template.keyHint}…）` : ''}
                </span>
                <Button type='button' variant='outline' size='sm' aria-disabled={busy} onClick={() => onReceipt(template.id)}>
                  発行する
                </Button>
              </li>
            ))}
          </ul>
          {receiptKey && (
            <p className='m-0 break-all text-dns-16N-130' role='status'>
              この鍵は今だけ表示します: {receiptKey}
            </p>
          )}
        </div>
      )}
    </div>
  );
};
