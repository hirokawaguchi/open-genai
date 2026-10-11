import { useEffect, useRef, useState } from 'react';
import useSWR from 'swr';
import { Button } from '@/components/ui/dads/Button';
import { teamApiFetcher } from '@/lib/fetcher';
import { statusLabel } from './labels';
import type { Chapter, Enrollment, Lesson } from './types';
import { errorMessage, useLmsActions, useLmsEnrollment } from './useLms';

type Props = {
  enrollmentId: string | null;
  previewCourseId: string | null;
  onBack: () => void;
};

const flat = (chapters: Chapter[]): Lesson[] => chapters.flatMap((chapter) => chapter.lessons);

export const PlayerPanel = ({ enrollmentId, previewCourseId, onBack }: Props) => {
  const { enrollment, mutate } = useLmsEnrollment(previewCourseId ? null : enrollmentId);
  const preview = useSWR<{ snapshot: Enrollment['snapshot'] }>(
    previewCourseId ? `lms/courses/${previewCourseId}/preview` : null,
    teamApiFetcher,
    { revalidateOnFocus: false },
  );
  const snapshot = previewCourseId ? preview.data?.snapshot : enrollment?.snapshot;
  const records = enrollment?.records ?? {};
  const lessons = snapshot ? flat(snapshot.chapters) : [];
  const [currentId, setCurrentId] = useState<string | null>(null);
  const lesson = lessons.find((item) => item.id === currentId) ?? lessons[0];

  useEffect(() => {
    if (!currentId && lessons[0]) {
      setCurrentId(lessons[0].id);
    }
  }, [currentId, lessons]);

  if (preview.error) {
    return (
      <div className='flex flex-col gap-3'>
        <Button type='button' variant='outline' size='sm' className='self-start' onClick={onBack}>
          戻る
        </Button>
        <p className='text-std-16N-170 text-error-1' role='alert'>
          {errorMessage(preview.error, 'プレビューを表示できません。')}
        </p>
      </div>
    );
  }

  if (!snapshot) {
    return <p className='text-std-16N-170'>読み込み中…</p>;
  }

  if (!lesson) {
    return (
      <div className='flex flex-col gap-3'>
        <div className='flex items-center justify-between gap-3'>
          <h2 className='text-std-18B-160'>{snapshot.title}</h2>
          <Button type='button' variant='outline' size='sm' onClick={onBack}>
            戻る
          </Button>
        </div>
        <p className='text-std-16N-170 text-solid-gray-700'>
          下書きにレッスンがありません。編集画面でレッスンを足すと、ここに出ます。
        </p>
      </div>
    );
  }

  return (
    <div className='flex h-[calc(100dvh-var(--header-height)-9rem)] min-h-[20rem] flex-col gap-3 overflow-hidden'>
      <div className='flex shrink-0 items-center justify-between gap-3'>
        <h2 className='text-std-18B-160'>{snapshot.title}</h2>
        <Button type='button' variant='outline' size='sm' onClick={onBack}>
          戻る
        </Button>
      </div>
      {previewCourseId && (
        <p className='shrink-0 text-dns-14N-130 text-solid-gray-600'>いまの下書きを表示しています。</p>
      )}
      {enrollment && (
        <p className='shrink-0 text-dns-14N-130 text-solid-gray-700'>
          版 {enrollment.versionNumber}・{enrollment.state === 'completed' ? '修了' : '受講中'}
        </p>
      )}
      <div className='grid min-h-0 flex-1 grid-rows-[auto_minmax(0,1fr)] gap-4 overflow-hidden lg:grid-cols-[16rem_minmax(0,1fr)] lg:grid-rows-1'>
        <nav className='flex max-h-40 min-h-0 flex-col gap-3 overflow-y-auto lg:max-h-none' aria-label='目次'>
          {snapshot.chapters.map((chapter, chapterIndex) => (
            <section key={chapter.id} className='flex flex-col gap-1'>
              <h3 className='px-3 text-dns-14B-130 text-solid-gray-800'>
                第{chapterIndex + 1}章 {chapter.title}
              </h3>
              <ol className='flex flex-col gap-1'>
                {chapter.lessons.map((item, lessonIndex) => (
                  <li key={item.id}>
                    <button
                      type='button'
                      className={`w-full rounded-4 px-3 py-2 text-left text-dns-14N-130 ${
                        item.id === lesson.id ? 'bg-solid-gray-100' : ''
                      }`}
                      onClick={() => setCurrentId(item.id)}
                    >
                      {lessonIndex + 1}. {item.title}
                      {records[item.id] ? `（${statusLabel(records[item.id].lesson_status)}）` : ''}
                    </button>
                  </li>
                ))}
              </ol>
            </section>
          ))}
        </nav>
        <div className='h-full min-h-0 overflow-hidden'>
          <LessonView
            key={lesson.id}
            lesson={lesson}
            enrollmentId={previewCourseId ? null : enrollment?.enrollmentId ?? null}
            recordLocation={records[lesson.id]?.lesson_location}
            recordStatus={records[lesson.id]?.lesson_status}
            onSaved={async (next) => {
              await mutate(next, { revalidate: false });
            }}
          />
        </div>
      </div>
    </div>
  );
};

const LessonView = ({
  lesson,
  enrollmentId,
  recordLocation,
  recordStatus,
  onSaved,
}: {
  lesson: Lesson;
  enrollmentId: string | null;
  recordLocation?: string;
  recordStatus?: string;
  onSaved: (enrollment: Enrollment) => Promise<void>;
}) => {
  const actions = useLmsActions();
  if (lesson.kind === 'video') {
    return (
      <VideoLesson
        lesson={lesson}
        enrollmentId={enrollmentId}
        location={recordLocation}
        onSaved={onSaved}
        report={actions.progress}
      />
    );
  }
  if (lesson.kind === 'slides') {
    return (
      <SlideLesson
        lesson={lesson}
        enrollmentId={enrollmentId}
        location={recordLocation}
        onSaved={onSaved}
        report={actions.progress}
      />
    );
  }
  if (lesson.kind === 'quiz') {
    return (
      <QuizLesson
        lesson={lesson}
        enrollmentId={enrollmentId}
        status={recordStatus}
        onSaved={onSaved}
        submit={actions.quiz}
      />
    );
  }
  return (
    <div className='flex h-full min-h-0 flex-col gap-2 overflow-y-auto'>
      <p className='text-std-16N-170'>{lesson.practicalText || '実技の文面がまだありません。'}</p>
      <p className='text-dns-14N-130 text-solid-gray-700'>
        {recordStatus ? `実技認定: ${statusLabel(recordStatus)}` : '実技認定者の合否を待っています。'}
      </p>
      {actions.error && <p className='text-dns-14N-130 text-red-700'>{actions.error}</p>}
    </div>
  );
};

const VideoLesson = ({
  lesson,
  enrollmentId,
  location,
  onSaved,
  report,
}: {
  lesson: Lesson;
  enrollmentId: string | null;
  location?: string;
  onSaved: (enrollment: Enrollment) => Promise<void>;
  report: (enrollmentId: string, lessonId: string, body: unknown) => Promise<Enrollment | null>;
}) => {
  const started = useRef(Date.now());
  const lastSent = useRef(0);
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    const node = videoRef.current;
    if (node && location) {
      const seconds = Number(location);
      if (Number.isFinite(seconds) && seconds > 0) {
        node.currentTime = seconds;
      }
    }
  }, [location, lesson.id]);

  const send = async (ended: boolean) => {
    const node = videoRef.current;
    if (!node || !enrollmentId) {
      return;
    }
    const now = Date.now();
    if (!ended && now - lastSent.current < 10000) {
      return;
    }
    lastSent.current = now;
    const saved = await report(enrollmentId, lesson.id, {
      lesson_location: String(node.currentTime),
      duration: node.duration || 0,
      sessionSeconds: Math.floor((now - started.current) / 1000),
      ended,
    });
    if (saved) {
      await onSaved(saved);
    }
  };

  if (!lesson.playbackUrl) {
    return <p className='text-std-16N-170 text-solid-gray-700'>教材がまだ選ばれていません。</p>;
  }

  return (
    <div className='flex h-full min-h-0 items-center justify-center'>
      <video
        ref={videoRef}
        className='max-h-full max-w-full rounded-8 bg-black'
        src={lesson.playbackUrl || undefined}
        controls
        onTimeUpdate={() => void send(false)}
        onEnded={() => void send(true)}
      />
    </div>
  );
};

const SlideLesson = ({
  lesson,
  enrollmentId,
  location,
  onSaved,
  report,
}: {
  lesson: Lesson;
  enrollmentId: string | null;
  location?: string;
  onSaved: (enrollment: Enrollment) => Promise<void>;
  report: (enrollmentId: string, lessonId: string, body: unknown) => Promise<Enrollment | null>;
}) => {
  const urls = lesson.slideUrls || [];
  const [page, setPage] = useState(Math.max(1, Number(location) || 1));
  const started = useRef(Date.now());

  const move = async (next: number) => {
    const bounded = Math.min(urls.length, Math.max(1, next));
    setPage(bounded);
    if (!enrollmentId) {
      return;
    }
    const saved = await report(enrollmentId, lesson.id, {
      lesson_location: String(bounded),
      pageCount: urls.length,
      sessionSeconds: Math.floor((Date.now() - started.current) / 1000),
    });
    if (saved) {
      await onSaved(saved);
    }
  };

  if (urls.length === 0) {
    return <p className='text-std-16N-170 text-solid-gray-700'>教材がまだ選ばれていません。</p>;
  }

  return (
    <div className='flex h-full min-h-0 flex-col gap-3'>
      <div className='flex min-h-0 flex-1 items-center justify-center'>
        {urls[page - 1] && (
          <img
            src={urls[page - 1] || ''}
            alt={`${lesson.title} ${page}`}
            className='max-h-[min(100%,calc(100dvh-var(--header-height)-16rem))] max-w-full rounded-8 object-contain'
          />
        )}
      </div>
      <div className='flex shrink-0 items-center gap-3'>
        <Button type='button' variant='outline' size='sm' onClick={() => void move(page - 1)}>
          前へ
        </Button>
        <p className='text-dns-14N-130'>
          {page} / {urls.length}
        </p>
        <Button type='button' variant='outline' size='sm' onClick={() => void move(page + 1)}>
          次へ
        </Button>
      </div>
    </div>
  );
};

const QuizLesson = ({
  lesson,
  enrollmentId,
  status,
  onSaved,
  submit,
}: {
  lesson: Lesson;
  enrollmentId: string | null;
  status?: string;
  onSaved: (enrollment: Enrollment) => Promise<void>;
  submit: (enrollmentId: string, lessonId: string, answers: number[]) => Promise<Enrollment | null>;
}) => {
  const questions = lesson.questions || [];
  const [answers, setAnswers] = useState<number[]>(() => questions.map(() => 0));
  if (questions.length === 0) {
    return <p className='text-std-16N-170 text-solid-gray-700'>設問がまだありません。</p>;
  }
  return (
    <form
      className='flex h-full min-h-0 flex-col gap-4 overflow-y-auto'
      onSubmit={async (e) => {
        e.preventDefault();
        if (!enrollmentId) {
          return;
        }
        const saved = await submit(enrollmentId, lesson.id, answers);
        if (saved) {
          await onSaved(saved);
        }
      }}
    >
      {questions.map((question, questionIndex) => (
        <fieldset key={question.id} className='flex flex-col gap-1'>
          <legend className='text-std-16B-150'>{question.prompt}</legend>
          {question.choices.map((choice, choiceIndex) => (
            <label key={choiceIndex} className='flex items-center gap-2 text-std-16N-170'>
              <input
                type='radio'
                name={question.id}
                checked={answers[questionIndex] === choiceIndex}
                onChange={() =>
                  setAnswers((prev) => prev.map((value, index) => (index === questionIndex ? choiceIndex : value)))
                }
              />
              {choice}
              {question.correctIndex === choiceIndex ? '（正答）' : ''}
            </label>
          ))}
        </fieldset>
      ))}
      {status && <p className='text-dns-14N-130'>結果: {statusLabel(status)}</p>}
      <Button type='submit' variant='solid-fill' size='sm'>
        回答する
      </Button>
    </form>
  );
};
