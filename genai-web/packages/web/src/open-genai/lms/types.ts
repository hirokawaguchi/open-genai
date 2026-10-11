export type LmsUser = { userId: string; userName: string };
export type LmsTeam = { teamId: string; teamName: string };

export type LearningRow = {
  courseId: string;
  title: string;
  enrollmentId: string | null;
  state: 'not_started' | 'in_progress' | 'completed';
  required: boolean;
  dueAt: string | null;
  overdue: boolean;
  practicalPending: boolean;
};

export type CourseSummary = { id: string; title: string; status: 'draft' | 'published' };

export type LmsHome = {
  userId: string;
  userName: string;
  tenantId: string;
  canUseLibrary: boolean;
  teams: LmsTeam[];
  users: LmsUser[];
  learning: LearningRow[];
  editableCourses: CourseSummary[];
  certifiableCourses: CourseSummary[];
};

export type Material = {
  id: string;
  title: string;
  kind: 'video' | 'slides';
  contentType: string;
  slideCount: number;
  createdAt: string;
  transcriptStatus?: 'none' | 'running' | 'draft' | 'confirmed' | 'failed';
};

export type TranscriptSegment = {
  id: string;
  start: number;
  end: number;
  text: string;
};

export type MaterialTranscript = {
  materialId: string;
  title: string;
  kind: 'video' | 'slides';
  status: 'none' | 'running' | 'draft' | 'confirmed' | 'failed';
  notice: string;
  error: string;
  playbackUrl: string;
  segments: TranscriptSegment[];
  updatedAt: string;
};

export type QuizQuestion = {
  id: string;
  prompt: string;
  choices: string[];
  correctIndex?: number;
};

export type Lesson = {
  id: string;
  title: string;
  kind: 'video' | 'slides' | 'quiz' | 'practical';
  required: boolean;
  materialId?: string;
  masteryScore?: number;
  questions?: QuizQuestion[];
  practicalText?: string;
  playbackUrl?: string | null;
  slideUrls?: Array<string | null>;
};

export type Chapter = { id: string; title: string; lessons: Lesson[] };

export type CourseDetail = {
  id: string;
  title: string;
  status: 'draft' | 'published';
  draft: { chapters: Chapter[] };
  currentVersionId: string | null;
  roles: Array<{ userId: string; role: 'editor' | 'certifier' }>;
  assignments: Array<{
    id: string;
    assigneeType: 'user' | 'team';
    assigneeId: string;
    required: boolean;
    dueAt: string | null;
  }>;
};

export type LessonRecord = {
  lesson_status: string;
  score_raw: number | null;
  lesson_location: string;
  session_time: string;
  total_time: string;
  suspend_data: string;
  graded_by: string | null;
  graded_at: string | null;
};

export type Enrollment = {
  enrollmentId: string;
  courseId: string;
  userId: string;
  userName: string;
  versionId: string;
  versionNumber: number;
  startedAt: string;
  state: 'in_progress' | 'completed';
  snapshot: { title: string; chapters: Chapter[] };
  records: Record<string, LessonRecord>;
};

export type ProgressRow = {
  userId: string;
  userName: string;
  enrollmentId: string | null;
  state: 'not_started' | 'in_progress' | 'completed';
  overdue: boolean;
  dueAt: string | null;
  required: boolean;
  materialDone: boolean;
  practicalPending: boolean;
  startedAt: string | null;
  practicals: Array<{
    lessonId: string;
    title: string;
    lesson_status: string;
    graded_by: string | null;
    graded_at: string | null;
  }>;
};
