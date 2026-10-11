import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/dads/Button';
import { Label } from '@/components/ui/dads/Label';
import {
  CustomDialog,
  CustomDialogBody,
  CustomDialogHeader,
  CustomDialogPanel,
} from '@/components/ui/CustomDialog';
import { newId } from '@/utils/uuid';
import type { Chapter, Lesson, LmsTeam, LmsUser, Material } from './types';
import { useLmsActions } from './useLms';

const inputClass = 'mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2 text-std-16N-170';

const steps = ['basics', 'outline', 'people'] as const;
type StepId = (typeof steps)[number];

const stepTitle: Record<StepId, string> = {
  basics: '名前を決める',
  outline: '目次を足す',
  people: '担当を決める',
};

const kindLabel: Record<Lesson['kind'], string> = {
  video: '動画',
  slides: 'テキスト',
  quiz: '確認テスト',
  practical: '実技',
};

type AssignmentDraft = {
  key: string;
  assigneeType: 'user' | 'team';
  assigneeId: string;
  required: boolean;
  dueAt: string;
};

type Props = {
  open: boolean;
  users: LmsUser[];
  teams: LmsTeam[];
  materials: Material[];
  selfUserId: string;
  onClose: () => void;
  onCreated: (courseId: string) => void;
};

const emptyLesson = (kind: Lesson['kind']): Lesson => ({
  id: newId(),
  title: '',
  kind,
  required: true,
  materialId: '',
  masteryScore: 80,
  questions: kind === 'quiz' ? [] : undefined,
  practicalText: kind === 'practical' ? '' : undefined,
});

const moveList = <T,>(list: T[], index: number, direction: -1 | 1): T[] => {
  const next = index + direction;
  if (next < 0 || next >= list.length) {
    return list;
  }
  const copy = [...list];
  const [item] = copy.splice(index, 1);
  copy.splice(next, 0, item);
  return copy;
};

const patchLesson = (chapters: Chapter[], chapterIndex: number, lessonIndex: number, patch: Partial<Lesson>) =>
  chapters.map((chapter, i) =>
    i === chapterIndex
      ? {
          ...chapter,
          lessons: chapter.lessons.map((lesson, j) => (j === lessonIndex ? { ...lesson, ...patch } : lesson)),
        }
      : chapter,
  );

export const CourseWizard = ({ open, users, teams, materials, selfUserId, onClose, onCreated }: Props) => {
  const actions = useLmsActions();
  const [step, setStep] = useState<StepId>('basics');
  const [title, setTitle] = useState('');
  const [chapters, setChapters] = useState<Chapter[]>([]);
  const [editors, setEditors] = useState<string[]>([]);
  const [certifiers, setCertifiers] = useState<string[]>([]);
  const [assignments, setAssignments] = useState<AssignmentDraft[]>([]);
  const [assigneeType, setAssigneeType] = useState<'user' | 'team'>('user');
  const [assigneeId, setAssigneeId] = useState('');
  const [required, setRequired] = useState(true);
  const [dueAt, setDueAt] = useState('');
  const [publish, setPublish] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    setStep('basics');
    setTitle('');
    setChapters([]);
    setEditors([selfUserId]);
    setCertifiers([]);
    setAssignments([]);
    setAssigneeType('user');
    setAssigneeId('');
    setRequired(true);
    setDueAt('');
    setPublish(false);
    setLocalError(null);
    actions.setError(null);
  }, [open, selfUserId, actions.setError]);

  const stepIndex = steps.indexOf(step);
  const lessonCount = chapters.reduce((sum, chapter) => sum + chapter.lessons.length, 0);
  const shownError = localError || actions.error;
  const nameOf = (userId: string) => users.find((user) => user.userId === userId)?.userName || userId;

  const toggle = (list: string[], id: string, on: boolean) =>
    on ? [...new Set([...list, id])] : list.filter((item) => item !== id);

  const goBack = () => {
    setLocalError(null);
    const previous = steps[stepIndex - 1];
    if (previous) {
      setStep(previous);
    }
  };

  const outlineError = () => {
    if (chapters.some((chapter) => !chapter.title.trim())) {
      return '章タイトルを入力してください。';
    }
    return null;
  };

  const goNext = () => {
    setLocalError(null);
    if (step === 'basics' && !title.trim()) {
      setLocalError('名前を入力してください。');
      return;
    }
    if (step === 'outline') {
      const message = outlineError();
      if (message) {
        setLocalError(message);
        return;
      }
    }
    const next = steps[stepIndex + 1];
    if (next) {
      setStep(next);
    }
  };

  const create = async () => {
    if (actions.busy) {
      return;
    }
    setLocalError(null);
    const name = title.trim();
    if (!name) {
      setLocalError('名前を入力してください。');
      return;
    }
    const message = outlineError();
    if (message) {
      setLocalError(message);
      return;
    }
    if (publish && lessonCount === 0) {
      setLocalError('レッスンが無いコースは公開できません。');
      return;
    }
    const created = await actions.createCourse(name);
    if (!created) {
      return;
    }
    const stop = () => {
      onCreated(created.id);
    };
    if (chapters.length > 0) {
      const saved = await actions.saveDraft(created.id, {
        title: name,
        chapters: chapters.map((chapter) => ({
          ...chapter,
          title: chapter.title.trim(),
          lessons: chapter.lessons.map((lesson) => ({
            ...lesson,
            title: lesson.title.trim() || kindLabel[lesson.kind],
          })),
        })),
      });
      if (!saved) {
        stop();
        return;
      }
    }
    for (const userId of editors) {
      if (userId === selfUserId) {
        continue;
      }
      const saved = await actions.setRole(created.id, userId, 'editor');
      if (!saved) {
        stop();
        return;
      }
    }
    for (const userId of certifiers) {
      const saved = await actions.setRole(created.id, userId, 'certifier');
      if (!saved) {
        stop();
        return;
      }
    }
    for (const item of assignments) {
      const saved = await actions.setAssignment(created.id, {
        assigneeType: item.assigneeType,
        assigneeId: item.assigneeId,
        required: item.required,
        dueAt: item.dueAt || null,
      });
      if (!saved) {
        stop();
        return;
      }
    }
    if (publish) {
      const published = await actions.publish(created.id);
      if (!published) {
        stop();
        return;
      }
    }
    onCreated(created.id);
    onClose();
  };

  return (
    <CustomDialog isOpen={open} onClose={onClose} position='top'>
      <CustomDialogPanel className='max-w-3xl'>
        <CustomDialogHeader hasClose={true} onClose={onClose}>
          新しいコース
        </CustomDialogHeader>
        <CustomDialogBody>
          <p className='text-dns-16N-130 text-solid-gray-600'>
            手順 {stepIndex + 1} / {steps.length}　{stepTitle[step]}
          </p>
          <p className='mt-1 text-std-16N-170 text-solid-gray-700'>
            {step === 'basics'
              ? '一覧に出る名前です。作成した人が、このコースのコース編集者になります。'
              : step === 'outline'
                ? '章タイトルを書き、その中にレッスンを足します。レッスンは動画、テキスト、確認テスト、実技の4つで、追加したあと種別を切り替えられます。確認テストの設問と実技の文面は、作成したあとの編集画面で書けます。'
                : 'コース編集者、実技認定者、コース受講対象者を決めます。空のままでも作成できます。'}
          </p>

          {step === 'basics' && (
            <div className='mt-4'>
              <Label htmlFor='lms-wizard-title' size='sm'>
                名前
              </Label>
              <input
                id='lms-wizard-title'
                className={inputClass}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder='例: 情報セキュリティ研修'
                required
              />
            </div>
          )}

          {step === 'outline' && (
            <div className='mt-4 flex max-h-[50vh] flex-col gap-4 overflow-y-auto'>
              {materials.length === 0 && (
                <p className='text-std-16N-170 text-solid-gray-700'>
                  教材庫にファイルが無いときは、レッスン名だけ作って、あとから動画とテキストを選べます。
                </p>
              )}
              {chapters.map((chapter, chapterIndex) => (
                <section key={chapter.id} className='flex flex-col gap-3'>
                  <div className='flex flex-wrap items-end gap-2'>
                    <div className='min-w-[12rem] flex-1'>
                      <Label htmlFor={`lms-wizard-chapter-${chapter.id}`} size='sm'>
                        第{chapterIndex + 1}章のタイトル
                      </Label>
                      <input
                        id={`lms-wizard-chapter-${chapter.id}`}
                        className={inputClass}
                        value={chapter.title}
                        placeholder='例：情報セキュリティの基礎'
                        onChange={(e) =>
                          setChapters((prev) =>
                            prev.map((item, i) => (i === chapterIndex ? { ...item, title: e.target.value } : item)),
                          )
                        }
                      />
                    </div>
                    <Button
                      type='button'
                      variant='outline'
                      size='md'
                      aria-disabled={chapterIndex === 0}
                      onClick={() => setChapters((prev) => moveList(prev, chapterIndex, -1))}
                    >
                      上へ
                    </Button>
                    <Button
                      type='button'
                      variant='outline'
                      size='md'
                      aria-disabled={chapterIndex === chapters.length - 1}
                      onClick={() => setChapters((prev) => moveList(prev, chapterIndex, 1))}
                    >
                      下へ
                    </Button>
                    <Button
                      type='button'
                      variant='outline'
                      size='md'
                      onClick={() => setChapters((prev) => prev.filter((_, i) => i !== chapterIndex))}
                    >
                      章を削除
                    </Button>
                  </div>
                  {chapter.lessons.length === 0 ? (
                    <p className='text-dns-16N-130 text-solid-gray-600'>まだレッスンがありません。</p>
                  ) : (
                    <ul className='flex flex-col gap-2'>
                      {chapter.lessons.map((lesson, lessonIndex) => (
                        <li key={lesson.id} className='rounded-4 border border-solid-gray-300 px-3 py-2'>
                          <div className='flex flex-wrap items-end gap-2'>
                            <div className='min-w-[12rem] flex-1'>
                              <Label htmlFor={`lms-wizard-lesson-${lesson.id}`} size='sm'>
                                レッスン {lessonIndex + 1} の名前
                              </Label>
                              <input
                                id={`lms-wizard-lesson-${lesson.id}`}
                                className={inputClass}
                                value={lesson.title}
                                placeholder='例：パスワードの作り方'
                                onChange={(e) =>
                                  setChapters((prev) => patchLesson(prev, chapterIndex, lessonIndex, { title: e.target.value }))
                                }
                              />
                            </div>
                            <div className='w-36'>
                              <Label htmlFor={`lms-wizard-kind-${lesson.id}`} size='sm'>
                                種別
                              </Label>
                              <select
                                id={`lms-wizard-kind-${lesson.id}`}
                                className={inputClass}
                                value={lesson.kind}
                                onChange={(e) => {
                                  const next = emptyLesson(e.target.value as Lesson['kind']);
                                  next.title = lesson.title;
                                  setChapters((prev) =>
                                    prev.map((item, i) =>
                                      i === chapterIndex
                                        ? {
                                            ...item,
                                            lessons: item.lessons.map((row, j) => (j === lessonIndex ? next : row)),
                                          }
                                        : item,
                                    ),
                                  );
                                }}
                              >
                                {(Object.keys(kindLabel) as Lesson['kind'][]).map((kind) => (
                                  <option key={kind} value={kind}>
                                    {kindLabel[kind]}
                                  </option>
                                ))}
                              </select>
                            </div>
                            <Button
                              type='button'
                              variant='outline'
                              size='md'
                              aria-disabled={lessonIndex === 0}
                              onClick={() =>
                                setChapters((prev) =>
                                  prev.map((item, i) =>
                                    i === chapterIndex ? { ...item, lessons: moveList(item.lessons, lessonIndex, -1) } : item,
                                  ),
                                )
                              }
                            >
                              上へ
                            </Button>
                            <Button
                              type='button'
                              variant='outline'
                              size='md'
                              aria-disabled={lessonIndex === chapter.lessons.length - 1}
                              onClick={() =>
                                setChapters((prev) =>
                                  prev.map((item, i) =>
                                    i === chapterIndex ? { ...item, lessons: moveList(item.lessons, lessonIndex, 1) } : item,
                                  ),
                                )
                              }
                            >
                              下へ
                            </Button>
                            <Button
                              type='button'
                              variant='outline'
                              size='md'
                              onClick={() =>
                                setChapters((prev) =>
                                  prev.map((item, i) =>
                                    i === chapterIndex
                                      ? { ...item, lessons: item.lessons.filter((_, j) => j !== lessonIndex) }
                                      : item,
                                  ),
                                )
                              }
                            >
                              削除
                            </Button>
                          </div>
                          <label className='mt-2 flex items-center gap-2 text-std-16N-170'>
                            <input
                              type='checkbox'
                              checked={lesson.required}
                              onChange={(e) =>
                                setChapters((prev) =>
                                  patchLesson(prev, chapterIndex, lessonIndex, { required: e.target.checked }),
                                )
                              }
                            />
                            必須
                          </label>
                          {(lesson.kind === 'video' || lesson.kind === 'slides') && (
                            <div className='mt-2'>
                              <Label htmlFor={`lms-wizard-material-${lesson.id}`} size='sm'>
                                教材
                              </Label>
                              <select
                                id={`lms-wizard-material-${lesson.id}`}
                                className={inputClass}
                                value={lesson.materialId || ''}
                                onChange={(e) =>
                                  setChapters((prev) =>
                                    patchLesson(prev, chapterIndex, lessonIndex, { materialId: e.target.value }),
                                  )
                                }
                              >
                                <option value=''>あとで選ぶ</option>
                                {materials
                                  .filter((material) => material.kind === (lesson.kind === 'video' ? 'video' : 'slides'))
                                  .map((material) => (
                                    <option key={material.id} value={material.id}>
                                      {material.title}
                                    </option>
                                  ))}
                              </select>
                            </div>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                  <Button
                    type='button'
                    variant='outline'
                    size='sm'
                    className='self-start'
                    onClick={() =>
                      setChapters((prev) =>
                        prev.map((item, i) =>
                          i === chapterIndex ? { ...item, lessons: [...item.lessons, emptyLesson('video')] } : item,
                        ),
                      )
                    }
                  >
                    レッスンを追加
                  </Button>
                </section>
              ))}
              <Button
                type='button'
                variant='outline'
                size='md'
                className='self-start'
                onClick={() => setChapters((prev) => [...prev, { id: newId(), title: '', lessons: [] }])}
              >
                章を追加
              </Button>
              <p className='text-dns-14N-130 text-solid-gray-600'>空のままでも作成できます。目次は編集画面で足せます。</p>
            </div>
          )}

          {step === 'people' && (
            <div className='mt-4 flex flex-col gap-4'>
              <div className='grid gap-4 md:grid-cols-2'>
                <fieldset className='m-0 flex flex-col gap-2 border-0 p-0'>
                  <legend className='text-std-16B-150'>コース編集者</legend>
                  {users.map((user) => (
                    <label key={user.userId} className='flex items-center gap-2 text-std-16N-170'>
                      <input
                        type='checkbox'
                        checked={editors.includes(user.userId)}
                        disabled={user.userId === selfUserId}
                        onChange={(e) => setEditors((prev) => toggle(prev, user.userId, e.target.checked))}
                      />
                      {user.userName}
                      {user.userId === selfUserId ? '（自分）' : ''}
                    </label>
                  ))}
                </fieldset>
                <fieldset className='m-0 flex flex-col gap-2 border-0 p-0'>
                  <legend className='text-std-16B-150'>実技認定者</legend>
                  <p className='text-dns-14N-130 text-solid-gray-600'>実技の合否を付けます。</p>
                  {users.map((user) => (
                    <label key={user.userId} className='flex items-center gap-2 text-std-16N-170'>
                      <input
                        type='checkbox'
                        checked={certifiers.includes(user.userId)}
                        onChange={(e) => setCertifiers((prev) => toggle(prev, user.userId, e.target.checked))}
                      />
                      {user.userName}
                    </label>
                  ))}
                </fieldset>
              </div>
              <div>
                <h3 className='text-std-16B-150'>コース受講対象者</h3>
                {assignments.length === 0 ? (
                  <p className='mt-1 text-dns-16N-130 text-solid-gray-600'>まだ受講対象者はいません。</p>
                ) : (
                  <ul className='mt-2 flex flex-col gap-2'>
                    {assignments.map((item) => (
                      <li
                        key={item.key}
                        className='flex items-center justify-between gap-2 rounded-4 border border-solid-gray-300 px-3 py-2'
                      >
                        <span className='text-std-16N-170'>
                          {item.assigneeType === 'team'
                            ? teams.find((team) => team.teamId === item.assigneeId)?.teamName || item.assigneeId
                            : nameOf(item.assigneeId)}
                          <span className='ml-2 text-dns-14N-130 text-solid-gray-600'>
                            {item.required ? '必須' : '任意'}
                            {item.dueAt ? `・${item.dueAt}` : ''}
                          </span>
                        </span>
                        <Button
                          type='button'
                          variant='outline'
                          size='sm'
                          onClick={() => setAssignments((prev) => prev.filter((row) => row.key !== item.key))}
                        >
                          外す
                        </Button>
                      </li>
                    ))}
                  </ul>
                )}
                <div className='mt-3 flex flex-wrap items-end gap-2'>
                  <div className='w-28'>
                    <Label htmlFor='lms-wizard-assignee-type' size='sm'>
                      種類
                    </Label>
                    <select
                      id='lms-wizard-assignee-type'
                      className={inputClass}
                      value={assigneeType}
                      onChange={(e) => {
                        setAssigneeType(e.target.value as 'user' | 'team');
                        setAssigneeId('');
                      }}
                    >
                      <option value='user'>個人</option>
                      <option value='team'>チーム</option>
                    </select>
                  </div>
                  <div className='min-w-[12rem] flex-1'>
                    <Label htmlFor='lms-wizard-assignee' size='sm'>
                      対象
                    </Label>
                    <select
                      id='lms-wizard-assignee'
                      className={inputClass}
                      value={assigneeId}
                      onChange={(e) => setAssigneeId(e.target.value)}
                    >
                      <option value=''>選ぶ</option>
                      {assigneeType === 'user'
                        ? users.map((user) => (
                            <option key={user.userId} value={user.userId}>
                              {user.userName}
                            </option>
                          ))
                        : teams.map((team) => (
                            <option key={team.teamId} value={team.teamId}>
                              {team.teamName}
                            </option>
                          ))}
                    </select>
                  </div>
                  <div>
                    <Label htmlFor='lms-wizard-due' size='sm'>
                      期限
                    </Label>
                    <input
                      id='lms-wizard-due'
                      className={inputClass}
                      type='date'
                      value={dueAt}
                      onChange={(e) => setDueAt(e.target.value)}
                    />
                  </div>
                  <label className='flex items-center gap-2 pb-2 text-std-16N-170'>
                    <input type='checkbox' checked={required} onChange={(e) => setRequired(e.target.checked)} />
                    必須
                  </label>
                  <Button
                    type='button'
                    variant='outline'
                    size='md'
                    aria-disabled={!assigneeId}
                    onClick={() => {
                      if (!assigneeId) {
                        return;
                      }
                      setAssignments((prev) => [...prev, { key: newId(), assigneeType, assigneeId, required, dueAt }]);
                      setAssigneeId('');
                    }}
                  >
                    対象に加える
                  </Button>
                </div>
              </div>
              <label className='flex items-start gap-2 text-std-16N-170'>
                <input
                  type='checkbox'
                  className='mt-1'
                  checked={publish}
                  disabled={lessonCount === 0}
                  onChange={(e) => setPublish(e.target.checked)}
                />
                <span>
                  作成して公開する
                  <span className='mt-0.5 block text-dns-14N-130 text-solid-gray-600'>
                    {lessonCount === 0
                      ? 'レッスンが無いので、下書きとして作成します。'
                      : '外したままなら下書きです。公開は編集画面からでもできます。'}
                  </span>
                </span>
              </label>
            </div>
          )}

          {shownError && (
            <p className='mt-4 text-dns-16N-130 text-error-1' role='alert'>
              {shownError}
            </p>
          )}

          <div className='mt-6 flex flex-wrap items-center justify-between gap-2'>
            <Button
              type='button'
              variant='outline'
              size='md'
              aria-disabled={step === 'basics' || actions.busy}
              onClick={() => {
                if (step === 'basics' || actions.busy) {
                  return;
                }
                goBack();
              }}
            >
              戻る
            </Button>
            {step === 'people' ? (
              <Button
                type='button'
                variant='solid-fill'
                size='md'
                aria-disabled={actions.busy || !title.trim()}
                onClick={() => void create()}
              >
                {actions.busy ? '作成中...' : publish ? '公開して編集する' : '作成して編集する'}
              </Button>
            ) : (
              <Button type='button' variant='solid-fill' size='md' onClick={goNext}>
                次へ
              </Button>
            )}
          </div>
        </CustomDialogBody>
      </CustomDialogPanel>
    </CustomDialog>
  );
};
