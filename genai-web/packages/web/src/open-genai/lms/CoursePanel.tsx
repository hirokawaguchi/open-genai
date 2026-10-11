import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react';
import { Button } from '@/components/ui/dads/Button';
import { Disclosure, DisclosureSummary } from '@/components/ui/dads/Disclosure';
import { Label } from '@/components/ui/dads/Label';
import { teamApi } from '@/lib/fetcher';
import { newId } from '@/utils/uuid';
import { fieldClass, statusLabel } from './labels';
import type { Chapter, CourseDetail, CourseSummary, Lesson, LmsTeam, LmsUser, Material } from './types';
import { errorMessage, useLmsActions, useLmsCourse } from './useLms';

type Props = {
  courses: CourseSummary[];
  courseId: string | null;
  users: LmsUser[];
  teams: LmsTeam[];
  materials: Material[];
  trashedMaterials?: Material[];
  onSelect: (courseId: string) => void;
  onOpenWizard: () => void;
  onPreview: (courseId: string) => void;
  onChanged: () => void;
  onDeleted: () => void;
};

const draftPayload = (title: string, chapters: Chapter[]) => ({
  title: title.trim(),
  chapters: chapters.map((chapter) => ({
    ...chapter,
    title: chapter.title === '章' ? '' : chapter.title,
    lessons: chapter.lessons.map((lesson) => ({
      ...lesson,
      title: lesson.title === 'レッスン' ? '' : lesson.title,
    })),
  })),
});

const emptyLesson = (kind: Lesson['kind']): Lesson => ({
  id: newId(),
  title: '',
  kind,
  required: true,
  materialId: '',
  masteryScore: 80,
  questions:
    kind === 'quiz'
      ? [{ id: newId(), prompt: '', choices: ['', ''], correctIndex: 0 }]
      : undefined,
  practicalText: kind === 'practical' ? '' : undefined,
});

export const CoursePanel = ({
  courses,
  courseId,
  users,
  teams,
  materials,
  trashedMaterials = [],
  onSelect,
  onOpenWizard,
  onPreview,
  onChanged,
  onDeleted,
}: Props) => {
  const { course, mutate } = useLmsCourse(courseId);
  const actions = useLmsActions();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkAction, setBulkAction] = useState('');
  const [bulkResult, setBulkResult] = useState<string | null>(null);
  const [savedNote, setSavedNote] = useState<string | null>(null);
  const [title, setTitle] = useState('');
  const [chapters, setChapters] = useState<Chapter[]>([]);
  const [roleUser, setRoleUser] = useState('');
  const [role, setRole] = useState<'editor' | 'certifier'>('editor');
  const [assigneeType, setAssigneeType] = useState<'user' | 'team'>('user');
  const [assigneeId, setAssigneeId] = useState('');
  const [required, setRequired] = useState(true);
  const [dueAt, setDueAt] = useState('');
  const [hydratedFor, setHydratedFor] = useState<string | null>(null);
  const savedSnapshot = useRef('');
  const dirty = useRef(false);
  const saving = useRef(false);
  const queued = useRef<Array<(ok: boolean) => void>>([]);
  const latestDraft = useRef({ courseId: null as string | null, body: draftPayload('', []) });
  const saveRef = useRef<() => Promise<boolean>>(async () => false);

  useEffect(() => {
    if (!course || course.id !== courseId || hydratedFor === course.id) {
      return;
    }
    const nextChapters = course.draft.chapters.map((chapter) => ({
      ...chapter,
      title: chapter.title === '章' ? '' : chapter.title,
      lessons: chapter.lessons.map((lesson) => ({
        ...lesson,
        title: lesson.title === 'レッスン' ? '' : lesson.title,
      })),
    }));
    setTitle(course.title);
    setChapters(nextChapters);
    savedSnapshot.current = JSON.stringify(draftPayload(course.title, nextChapters));
    dirty.current = false;
    setSavedNote(null);
    setHydratedFor(course.id);
  }, [course, courseId, hydratedFor]);

  useEffect(() => {
    const ids = new Set(courses.map((item) => item.id));
    setSelected((prev) => {
      const next = new Set([...prev].filter((id) => ids.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [courses]);

  const selectedCount = selected.size;
  const allSelected = courses.length > 0 && selectedCount === courses.length;

  const toggleAll = () => {
    setSelected(allSelected ? new Set() : new Set(courses.map((item) => item.id)));
  };

  const toggleOne = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const runBulk = async () => {
    if ((bulkAction !== 'publish' && bulkAction !== 'delete') || selectedCount === 0 || actions.busy) {
      return;
    }
    if (
      bulkAction === 'delete' &&
      !window.confirm(`${selectedCount} 件のコースを削除しますか。受講記録も消えます。教材ファイルは残ります。`)
    ) {
      return;
    }
    let ok = 0;
    let failed = 0;
    let removedOpen = false;
    for (const id of selected) {
      const saved = bulkAction === 'delete' ? await actions.deleteCourse(id) : await actions.publish(id);
      if (saved) {
        ok += 1;
        if (bulkAction === 'delete' && id === courseId) {
          removedOpen = true;
        }
      } else {
        failed += 1;
      }
    }
    const verb = bulkAction === 'delete' ? '削除' : '公開';
    setBulkResult(failed > 0 ? `${ok} 件を${verb}しました。${failed} 件は${verb}できませんでした。` : `${ok} 件を${verb}しました。`);
    setSelected(new Set());
    setBulkAction('');
    if (removedOpen) {
      onDeleted();
    }
    await mutate();
    onChanged();
  };

  const save = async () => {
    if (!courseId || hydratedFor !== courseId) {
      return false;
    }
    if (saving.current) {
      return new Promise<boolean>((resolve) => queued.current.push(resolve));
    }
    saving.current = true;
    let ok = true;
    try {
      for (;;) {
        const body = latestDraft.current.body;
        const id = latestDraft.current.courseId;
        if (!id) {
          ok = false;
          break;
        }
        if (!body.title) {
          setSavedNote('コース名を入れると、下書きに残ります');
          ok = false;
          break;
        }
        const key = JSON.stringify(body);
        if (key === savedSnapshot.current) {
          dirty.current = false;
          break;
        }
        setSavedNote('下書きを保存しています');
        const saved = await teamApi.put<CourseDetail>(`lms/courses/${id}/draft`, body).then((r) => r.data);
        savedSnapshot.current = key;
        await mutate(saved, { revalidate: false });
        onChanged();
        setSavedNote('下書きを保存しました');
      }
      return ok;
    } catch (e) {
      ok = false;
      setSavedNote(null);
      actions.setError(errorMessage(e, '下書きを保存できませんでした'));
      return false;
    } finally {
      saving.current = false;
      dirty.current = JSON.stringify(latestDraft.current.body) !== savedSnapshot.current;
      queued.current.splice(0).forEach((resolve) => resolve(ok));
    }
  };
  saveRef.current = save;

  latestDraft.current = { courseId, body: draftPayload(title, chapters) };

  useEffect(() => {
    if (!courseId || hydratedFor !== courseId) {
      return;
    }
    const key = JSON.stringify(draftPayload(title, chapters));
    if (key === savedSnapshot.current) {
      dirty.current = false;
      return;
    }
    if (!title.trim()) {
      dirty.current = true;
      setSavedNote('コース名を入れると、下書きに残ります');
      return;
    }
    dirty.current = true;
    setSavedNote('下書きに残します');
    const timer = window.setTimeout(() => {
      void saveRef.current();
    }, 700);
    return () => window.clearTimeout(timer);
  }, [title, chapters, courseId, hydratedFor]);

  useEffect(() => {
    const flush = () => {
      const current = latestDraft.current;
      if (!current.courseId || !dirty.current || !current.body.title || saving.current) {
        return;
      }
      dirty.current = false;
      void teamApi.put(`lms/courses/${current.courseId}/draft`, current.body);
    };
    window.addEventListener('pagehide', flush);
    return () => {
      window.removeEventListener('pagehide', flush);
      flush();
    };
  }, []);

  const removeCourse = async (id: string, name: string) => {
    if (actions.busy) {
      return false;
    }
    if (!window.confirm(`「${name}」を削除しますか。受講記録も消えます。教材ファイルは残ります。`)) {
      return false;
    }
    const saved = await actions.deleteCourse(id);
    if (!saved) {
      return false;
    }
    setSelected((prev) => {
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
    if (id === courseId) {
      onDeleted();
    }
    onChanged();
    return true;
  };

  return (
    <div className='flex flex-col gap-4'>
      <section className='flex flex-col gap-3'>
        <div className='flex flex-wrap items-center justify-between gap-2'>
          <h2 className='text-std-18B-160 text-solid-gray-900'>コース一覧</h2>
          <Button type='button' variant='solid-fill' size='sm' onClick={onOpenWizard}>
            新しいコースを作る
          </Button>
        </div>
        {courses.length === 0 ? (
          <p className='text-solid-gray-600'>
            まだコースがありません。
            <button
              type='button'
              className='ml-1 text-blue-900 underline-offset-2 hover:underline'
              onClick={onOpenWizard}
            >
              新しいコースを作る
            </button>
          </p>
        ) : (
          <>
            <div className='flex flex-wrap items-center gap-3 rounded-4 border border-solid-gray-300 bg-solid-gray-50 px-3 py-2'>
              <label className='flex items-center gap-2 text-dns-16N-130 text-solid-gray-700'>
                <input
                  type='checkbox'
                  className='size-5'
                  checked={allSelected}
                  ref={(el) => {
                    if (el) {
                      el.indeterminate = selectedCount > 0 && !allSelected;
                    }
                  }}
                  onChange={toggleAll}
                />
                すべて選択
              </label>
              <span className='text-dns-14N-130 text-solid-gray-600'>
                {selectedCount > 0 ? `${selectedCount} 件を選択中` : '選択して一括処理できます'}
              </span>
              <div className='flex flex-wrap items-center gap-2'>
                <select
                  className='rounded-4 border border-solid-gray-420 px-2 py-1 text-dns-16N-130'
                  value={bulkAction}
                  onChange={(e) => setBulkAction(e.target.value)}
                  aria-label='一括処理を選ぶ'
                >
                  <option value=''>一括処理を選ぶ…</option>
                  <option value='publish'>公開する</option>
                  <option value='delete'>削除する</option>
                </select>
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  aria-disabled={actions.busy || selectedCount === 0 || !bulkAction}
                  onClick={() => void runBulk()}
                >
                  {actions.busy ? '処理中...' : '実行'}
                </Button>
              </div>
            </div>
            {bulkResult && (
              <p className='text-dns-14N-130 text-solid-gray-700' role='status'>
                {bulkResult}
              </p>
            )}
            <div className='overflow-x-auto rounded-8 border border-solid-gray-300'>
              <table className='w-full min-w-[40rem] border-collapse text-dns-14N-130'>
                <thead>
                  <tr className='border-b border-solid-gray-300 bg-solid-gray-50 text-left text-solid-gray-600'>
                    <th className='w-10 px-3 py-2'>
                      <span className='sr-only'>選択</span>
                    </th>
                    <th className='px-3 py-2'>コース名</th>
                    <th className='px-3 py-2'>状態</th>
                    <th className='px-3 py-2 text-right'>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {courses.map((item) => (
                    <tr
                      key={item.id}
                      className={`border-b border-solid-gray-200 last:border-b-0 ${item.id === courseId ? 'bg-blue-50' : ''}`}
                    >
                      <td className='px-3 py-2'>
                        <input
                          type='checkbox'
                          className='size-5'
                          checked={selected.has(item.id)}
                          onChange={() => toggleOne(item.id)}
                          aria-label={`「${item.title}」を選択`}
                        />
                      </td>
                      <td className='px-3 py-2'>
                        <span className='text-std-16N-170 text-solid-gray-900'>{item.title}</span>
                        {item.id === courseId && (
                          <span className='ml-2 rounded-full bg-blue-100 px-2 py-0.5 text-dns-14N-130 text-blue-900'>
                            選択中
                          </span>
                        )}
                      </td>
                      <td className='px-3 py-2 text-solid-gray-600'>{statusLabel(item.status)}</td>
                      <td className='px-3 py-2 text-right'>
                        <span className='inline-flex gap-2'>
                          <Button type='button' variant='solid-fill' size='sm' onClick={() => onSelect(item.id)}>
                            開く
                          </Button>
                          <Button
                            type='button'
                            variant='outline'
                            size='sm'
                            onClick={() => {
                              if (item.id !== courseId) {
                                onPreview(item.id);
                                return;
                              }
                              void saveRef.current().then((ok) => {
                                if (ok) {
                                  onPreview(item.id);
                                }
                              });
                            }}
                          >
                            プレビュー
                          </Button>
                          <Button type='button' variant='outline' size='sm' onClick={() => void removeCourse(item.id, item.title)}>
                            削除
                          </Button>
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>
      {actions.error && (
        <p className='text-dns-14N-130 text-error-1' role='alert'>
          {actions.error}
        </p>
      )}
      {course && hydratedFor === course.id && (
        <div className='flex flex-col gap-4'>
          <h2 className='text-std-18B-160 text-solid-gray-900'>編集</h2>
          <div>
            <Label htmlFor='lms-course-title' size='sm'>
              コース名
            </Label>
            <input
              id='lms-course-title'
              className={fieldClass}
              value={title}
              placeholder='例: 情報セキュリティ研修'
              onChange={(e) => setTitle(e.target.value)}
            />
            <p className='mt-1 text-dns-14N-130 text-solid-gray-600'>
              編集内容は下書きに自動で残ります。受講者に見えるのは、公開したときです。
            </p>
          </div>
          <div className='flex flex-wrap gap-2'>
            <Button
              type='button'
              variant='solid-fill'
              size='sm'
              aria-disabled={actions.busy}
              onClick={async () => {
                if (!(await saveRef.current())) {
                  return;
                }
                const published = await actions.publish(course.id);
                if (published) {
                  await mutate();
                  onChanged();
                  setSavedNote('公開しました');
                }
              }}
            >
              公開
            </Button>
            <Button
              type='button'
              variant='outline'
              size='sm'
              onClick={() => {
                void saveRef.current().then((ok) => {
                  if (ok) {
                    onPreview(course.id);
                  }
                });
              }}
            >
              プレビュー
            </Button>
            <Button type='button' variant='outline' size='sm' onClick={() => void removeCourse(course.id, title || course.title)}>
              削除
            </Button>
          </div>
          {savedNote && (
            <p className='text-dns-14N-130 text-solid-gray-700' role='status'>
              {savedNote}
            </p>
          )}
          <Disclosure className='rounded-8 border border-solid-gray-300 px-4 py-3'>
            <DisclosureSummary>
              <span className='text-std-16B-150'>コースの設定</span>
            </DisclosureSummary>
            <div className='mt-4 flex flex-col gap-6'>
              <p className='text-dns-14N-130 text-solid-gray-600'>
                コース編集者、実技認定者、コース受講対象者はコース全体の設定です。追加はその場で残ります。
              </p>
              <section className='flex flex-col gap-3'>
                <h3 className='text-std-16B-150'>コース編集者と実技認定者</h3>
                <ul className='text-dns-14N-130'>
                  {course.roles.map((item) => (
                    <li key={`${item.role}-${item.userId}`} className='flex items-center justify-between gap-2 py-1'>
                      <span>
                        {users.find((user) => user.userId === item.userId)?.userName || item.userId}（
                        {item.role === 'editor' ? 'コース編集' : '実技認定'}）
                      </span>
                      <Button
                        type='button'
                        variant='outline'
                        size='sm'
                        onClick={async () => {
                          const saved = await actions.removeRole(course.id, item.userId, item.role);
                          if (saved) {
                            await mutate();
                          }
                        }}
                      >
                        外す
                      </Button>
                    </li>
                  ))}
                </ul>
                <div className='flex flex-wrap items-end gap-2'>
                  <select className={fieldClass} aria-label='利用者' value={roleUser} onChange={(e) => setRoleUser(e.target.value)}>
                    <option value=''>利用者</option>
                    {users.map((user) => (
                      <option key={user.userId} value={user.userId}>
                        {user.userName}
                      </option>
                    ))}
                  </select>
                  <select
                    className={fieldClass}
                    aria-label='役割'
                    value={role}
                    onChange={(e) => setRole(e.target.value as 'editor' | 'certifier')}
                  >
                    <option value='editor'>コース編集</option>
                    <option value='certifier'>実技認定</option>
                  </select>
                  <Button
                    type='button'
                    variant='outline'
                    size='sm'
                    onClick={async () => {
                      if (!roleUser) {
                        return;
                      }
                      const saved = await actions.setRole(course.id, roleUser, role);
                      if (saved) {
                        await mutate();
                      }
                    }}
                  >
                    追加
                  </Button>
                </div>
              </section>
              <section className='flex flex-col gap-3'>
                <h3 className='text-std-16B-150'>コース受講対象者</h3>
                <ul className='text-dns-14N-130'>
                  {course.assignments.map((item) => (
                    <li key={item.id} className='flex items-center justify-between gap-2 py-1'>
                      <span>
                        {item.assigneeType === 'team' ? 'チーム ' : ''}
                        {item.assigneeId}
                        {item.required ? '・必須' : ''}
                        {item.dueAt ? `・${item.dueAt}` : ''}
                      </span>
                      <Button
                        type='button'
                        variant='outline'
                        size='sm'
                        onClick={async () => {
                          const saved = await actions.removeAssignment(course.id, item.id);
                          if (saved) {
                            await mutate();
                          }
                        }}
                      >
                        外す
                      </Button>
                    </li>
                  ))}
                </ul>
                <div className='grid gap-2 md:grid-cols-2'>
                  <select
                    className={fieldClass}
                    aria-label='対象の種類'
                    value={assigneeType}
                    onChange={(e) => setAssigneeType(e.target.value as 'user' | 'team')}
                  >
                    <option value='user'>個人</option>
                    <option value='team'>チーム</option>
                  </select>
                  <select className={fieldClass} aria-label='受講対象者' value={assigneeId} onChange={(e) => setAssigneeId(e.target.value)}>
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
                  <input className={fieldClass} type='date' aria-label='受講期限' value={dueAt} onChange={(e) => setDueAt(e.target.value)} />
                  <label className='flex items-center gap-2 text-dns-14N-130'>
                    <input type='checkbox' checked={required} onChange={(e) => setRequired(e.target.checked)} />
                    必須
                  </label>
                </div>
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  onClick={async () => {
                    if (!assigneeId) {
                      return;
                    }
                    const saved = await actions.setAssignment(course.id, {
                      assigneeType,
                      assigneeId,
                      required,
                      dueAt: dueAt || null,
                    });
                    if (saved) {
                      await mutate();
                    }
                  }}
                >
                  対象に加える
                </Button>
              </section>
            </div>
          </Disclosure>
          {chapters.map((chapter, chapterIndex) => (
            <section key={chapter.id} className='rounded-8 border border-solid-gray-420 p-4'>
              <div className='flex flex-wrap items-end gap-2'>
                <div className='min-w-[12rem] flex-1'>
                  <Label htmlFor={`lms-chapter-${chapter.id}`} size='sm'>
                    第{chapterIndex + 1}章のタイトル
                  </Label>
                  <input
                    id={`lms-chapter-${chapter.id}`}
                    className={fieldClass}
                    value={chapter.title === '章' ? '' : chapter.title}
                    placeholder='例：情報セキュリティの基礎'
                    onChange={(e) =>
                      setChapters((prev) => prev.map((item, i) => (i === chapterIndex ? { ...item, title: e.target.value } : item)))
                    }
                  />
                </div>
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  aria-disabled={chapterIndex === 0}
                  onClick={() => setChapters((prev) => moveList(prev, chapterIndex, -1))}
                >
                  上へ
                </Button>
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  aria-disabled={chapterIndex === chapters.length - 1}
                  onClick={() => setChapters((prev) => moveList(prev, chapterIndex, 1))}
                >
                  下へ
                </Button>
                <Button
                  type='button'
                  variant='outline'
                  size='sm'
                  onClick={() => setChapters((prev) => prev.filter((_, i) => i !== chapterIndex))}
                >
                  章を削除
                </Button>
              </div>
              <div className='mt-3 flex flex-col gap-3'>
                {chapter.lessons.map((lesson, lessonIndex) => (
                  <div key={lesson.id} className='rounded-8 bg-solid-gray-50 p-3'>
                    <div className='mb-2 flex flex-wrap items-center justify-between gap-2'>
                      <p className='text-std-16B-150 text-solid-gray-900'>レッスン {lessonIndex + 1}</p>
                      <div className='flex flex-wrap gap-2'>
                        <Button
                          type='button'
                          variant='outline'
                          size='sm'
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
                          size='sm'
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
                          size='sm'
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
                    </div>
                    <div className='grid gap-3 md:grid-cols-2'>
                      <div>
                        <Label htmlFor={`lms-lesson-title-${lesson.id}`} size='sm'>
                          レッスン {lessonIndex + 1} の名前
                        </Label>
                        <input
                          id={`lms-lesson-title-${lesson.id}`}
                          className={fieldClass}
                          value={lesson.title === 'レッスン' ? '' : lesson.title}
                          placeholder='例：パスワードの作り方'
                          onChange={(e) => updateLesson(setChapters, chapterIndex, lessonIndex, { title: e.target.value })}
                        />
                      </div>
                      <div>
                        <Label htmlFor={`lms-lesson-kind-${lesson.id}`} size='sm'>
                          種別
                        </Label>
                        <select
                          id={`lms-lesson-kind-${lesson.id}`}
                          className={fieldClass}
                          value={lesson.kind}
                          onChange={(e) => {
                            const next = emptyLesson(e.target.value as Lesson['kind']);
                            updateLesson(setChapters, chapterIndex, lessonIndex, {
                              ...next,
                              id: lesson.id,
                              title: lesson.title,
                              required: lesson.required,
                            });
                          }}
                        >
                        <option value='video'>動画</option>
                        <option value='slides'>テキスト</option>
                        <option value='quiz'>確認テスト</option>
                        <option value='practical'>実技</option>
                      </select>
                      </div>
                    </div>
                    <label className='mt-2 flex items-center gap-2 text-dns-14N-130'>
                      <input
                        type='checkbox'
                        checked={lesson.required}
                        onChange={(e) => updateLesson(setChapters, chapterIndex, lessonIndex, { required: e.target.checked })}
                      />
                      必須
                    </label>
                    {(lesson.kind === 'video' || lesson.kind === 'slides') && (
                      <select
                        className={fieldClass}
                        aria-label='教材'
                        value={lesson.materialId || ''}
                        onChange={(e) => updateLesson(setChapters, chapterIndex, lessonIndex, { materialId: e.target.value })}
                      >
                        <option value=''>教材を選ぶ</option>
                        {materials
                          .filter((material) => material.kind === (lesson.kind === 'video' ? 'video' : 'slides'))
                          .map((material) => (
                            <option key={material.id} value={material.id}>
                              {material.title}
                            </option>
                          ))}
                        {trashedMaterials
                          .filter(
                            (material) =>
                              material.id === lesson.materialId &&
                              material.kind === (lesson.kind === 'video' ? 'video' : 'slides'),
                          )
                          .map((material) => (
                            <option key={material.id} value={material.id}>
                              {material.title}（ゴミ箱）
                            </option>
                          ))}
                      </select>
                    )}
                    {lesson.kind === 'practical' && (
                      <textarea
                        className={fieldClass}
                        rows={2}
                        aria-label='実技の文面'
                        placeholder='例：申請システムでパスワードを再設定できる'
                        value={lesson.practicalText || ''}
                        onChange={(e) => updateLesson(setChapters, chapterIndex, lessonIndex, { practicalText: e.target.value })}
                      />
                    )}
                    {lesson.kind === 'quiz' && (
                      <div className='mt-2 flex flex-col gap-3'>
                        <div>
                          <Label htmlFor={`lms-mastery-${lesson.id}`} size='sm'>
                            合格点
                          </Label>
                          <input
                            id={`lms-mastery-${lesson.id}`}
                            className={fieldClass}
                            type='number'
                            min={0}
                            max={100}
                            value={lesson.masteryScore ?? 80}
                            onChange={(e) =>
                              updateLesson(setChapters, chapterIndex, lessonIndex, { masteryScore: Number(e.target.value) })
                            }
                          />
                        </div>
                        {(lesson.questions || []).map((question, questionIndex) => (
                          <div key={question.id} className='flex flex-col gap-2 rounded-4 bg-white p-3'>
                            <div>
                              <Label htmlFor={`lms-question-${question.id}`} size='sm'>
                                設問 {questionIndex + 1}
                              </Label>
                              <input
                                id={`lms-question-${question.id}`}
                                className={fieldClass}
                                placeholder='例：届ける先はどこですか'
                                value={question.prompt}
                                onChange={(e) =>
                                  updateQuestion(setChapters, chapterIndex, lessonIndex, questionIndex, { prompt: e.target.value })
                                }
                              />
                            </div>
                            <fieldset className='m-0 flex flex-col gap-2 border-0 p-0'>
                              <legend className='text-dns-14N-130 text-solid-gray-700'>
                                選択肢。正答にするものに印を付けます。
                              </legend>
                              {question.choices.map((choice, choiceIndex) => (
                                <div key={choiceIndex} className='flex items-end gap-2'>
                                  <label className='mb-2 flex shrink-0 items-center gap-1 text-dns-14N-130'>
                                    <input
                                      type='radio'
                                      name={`correct-${question.id}`}
                                      checked={question.correctIndex === choiceIndex}
                                      aria-label={`選択肢 ${choiceIndex + 1} を正答にする`}
                                      onChange={() =>
                                        updateQuestion(setChapters, chapterIndex, lessonIndex, questionIndex, {
                                          correctIndex: choiceIndex,
                                        })
                                      }
                                    />
                                    正答
                                  </label>
                                  <div className='min-w-0 flex-1'>
                                    <Label htmlFor={`lms-choice-${question.id}-${choiceIndex}`} size='sm'>
                                      選択肢 {choiceIndex + 1}
                                    </Label>
                                    <input
                                      id={`lms-choice-${question.id}-${choiceIndex}`}
                                      className={fieldClass}
                                      placeholder={choiceIndex === 0 ? '例：ブラウザ' : '例：教材サーバ'}
                                      value={choice}
                                      onChange={(e) => {
                                        const choices = [...question.choices];
                                        choices[choiceIndex] = e.target.value;
                                        updateQuestion(setChapters, chapterIndex, lessonIndex, questionIndex, { choices });
                                      }}
                                    />
                                  </div>
                                </div>
                              ))}
                            </fieldset>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
              <div className='mt-3 flex flex-col items-start gap-1'>
                <Button type='button' variant='outline' size='sm' onClick={() => addLesson(setChapters, chapterIndex, 'video')}>
                  レッスンを追加
                </Button>
                <p className='text-dns-14N-130 text-solid-gray-600'>
                  追加したあと、種別で動画、テキスト、確認テスト、実技を選びます。
                </p>
              </div>
            </section>
          ))}
          <div className='flex flex-wrap gap-2'>
            <Button
              type='button'
              variant='outline'
              size='sm'
              onClick={() => setChapters((prev) => [...prev, { id: newId(), title: '', lessons: [] }])}
            >
              章を追加
            </Button>
          </div>
        </div>
      )}
    </div>
  );
};

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

const updateLesson = (
  setChapters: Dispatch<SetStateAction<Chapter[]>>,
  chapterIndex: number,
  lessonIndex: number,
  patch: Partial<Lesson>,
) => {
  setChapters((prev) =>
    prev.map((chapter, i) =>
      i === chapterIndex
        ? {
            ...chapter,
            lessons: chapter.lessons.map((lesson, j) => (j === lessonIndex ? { ...lesson, ...patch } : lesson)),
          }
        : chapter,
    ),
  );
};

const updateQuestion = (
  setChapters: Dispatch<SetStateAction<Chapter[]>>,
  chapterIndex: number,
  lessonIndex: number,
  questionIndex: number,
  patch: Partial<NonNullable<Lesson['questions']>[number]>,
) => {
  setChapters((prev) =>
    prev.map((chapter, i) => {
      if (i !== chapterIndex) {
        return chapter;
      }
      return {
        ...chapter,
        lessons: chapter.lessons.map((lesson, j) => {
          if (j !== lessonIndex) {
            return lesson;
          }
          const questions = (lesson.questions || []).map((question, k) =>
            k === questionIndex ? { ...question, ...patch } : question,
          );
          return { ...lesson, questions };
        }),
      };
    }),
  );
};

const addLesson = (
  setChapters: Dispatch<SetStateAction<Chapter[]>>,
  chapterIndex: number,
  kind: Lesson['kind'],
) => {
  setChapters((prev) =>
    prev.map((chapter, i) =>
      i === chapterIndex ? { ...chapter, lessons: [...chapter.lessons, emptyLesson(kind)] } : chapter,
    ),
  );
};
