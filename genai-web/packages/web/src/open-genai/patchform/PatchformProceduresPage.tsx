import { useState, type FormEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { PiListBold, PiNotePencilBold } from 'react-icons/pi';
import { BreadcrumbsNav } from '@/components/ui/BreadcrumbsNav';
import { Button } from '@/components/ui/dads/Button';
import { Label } from '@/components/ui/dads/Label';
import { PageTitle } from '@/components/PageTitle';
import { LayoutBody } from '@/layout/LayoutBody';
import { NAVIGATION_TAG, PATCHFORM_LABEL } from './labels';
import { PatchformProcedureCoach } from './PatchformProcedureCoach';
import { FilePickButton } from './runtime/FilePickButton';
import { PatchformPaneTabs } from './PatchformPaneTabs';
import { PatchformSubnav } from './PatchformSubnav';
import { ProcedureReceptionActions } from './ProcedureReceptionActions';
import { omitsNavigation } from './types';
import {
  extractPatchformFile,
  usePatchformAssist,
  usePatchformConfig,
  usePatchformList,
  usePatchformProcedureActions,
  usePatchformProcedures,
} from './usePatchform';

const statusLabel: Record<string, string> = {
  draft: '下書き',
  published: '公開中',
};

export const PatchformProceduresPage = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const pane = searchParams.get('tab') === 'new' ? 'new' : 'list';
  const { config } = usePatchformConfig();
  const { forms } = usePatchformList();
  const { procedures, isLoading, loadError, mutate } = usePatchformProcedures();
  const { create, setStatus, submitting, error, setError } = usePatchformProcedureActions();
  const {
    draftProcedure,
    busy: assistBusy,
    error: assistError,
    setError: setAssistError,
  } = usePatchformAssist();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [guideFormId, setGuideFormId] = useState('');
  const [startMode, setStartMode] = useState<'omit' | 'navigate'>('omit');
  const [guideText, setGuideText] = useState('');
  const [aiNotes, setAiNotes] = useState<string | null>(null);
  const [readingFile, setReadingFile] = useState(false);
  const [guideFileName, setGuideFileName] = useState('');

  const draftProc = procedures.find((p) => p.status === 'draft');
  const publishedProc = procedures.find((p) => p.status === 'published');
  const omitNav = startMode === 'omit';
  const isNavForm = (f: (typeof forms)[number]) => (f.tags || []).includes(NAVIGATION_TAG);
  const selectableForms = forms.filter((f) => (omitNav ? !isNavForm(f) : isNavForm(f)));

  const chooseStartMode = (mode: 'omit' | 'navigate') => {
    setStartMode(mode);
    const keep = forms.find((f) => f.id === guideFormId);
    const ok = keep && (mode === 'omit' ? !isNavForm(keep) : isNavForm(keep));
    if (!ok) setGuideFormId('');
  };

  const goCreate = () => {
    if (pane === 'new') {
      document.getElementById('pf-proc-name')?.focus();
      document.getElementById('pf-proc-create')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return;
    }
    navigate('/patchform/procedures?tab=new');
  };

  const onPickGuide = async (file: File | null) => {
    if (!file) return;
    setAssistError(null);
    setAiNotes(null);
    setReadingFile(true);
    try {
      const res = await extractPatchformFile('document', file);
      const extracted = (res.extracted || '').trim();
      if (!extracted) {
        setAssistError(
          res.notes
          || 'このファイルから本文を取れませんでした。txt / md / pdf / docx / xlsx を選んでください。',
        );
        return;
      }
      setGuideText(extracted);
    } catch {
      setAssistError('ファイルの読み取りに失敗しました。txt / md / pdf / docx / xlsx を選んでください。');
    } finally {
      setReadingFile(false);
    }
  };

  const onDraftFromGuide = async () => {
    setAssistError(null);
    setAiNotes(null);
    if (!guideText.trim()) {
      setAssistError('手引きのファイルを選んでください。');
      return;
    }
    const res = await draftProcedure({ text: guideText.trim(), visibility: 'internal' });
    if (!res) return;
    await mutate();
    navigate(`/patchform/procedures/${res.procedure.id}`);
  };

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!name.trim() || !guideFormId) {
      setError(omitNav ? '名前と申請フォームを選んでください。' : '名前とナビゲーションフォームを選んでください。');
      return;
    }
    const created = await create({
      name: name.trim(),
      description: description.trim() || undefined,
      guide_form_id: guideFormId,
    });
    if (created) {
      await mutate();
      navigate(`/patchform/procedures/${created.id}`);
    }
  };

  return (
    <LayoutBody>
      <PageTitle title={`手続き · ${PATCHFORM_LABEL}`} />
      <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-6 p-6 lg:p-8'>
        <BreadcrumbsNav
          items={[
            { label: 'ホーム', to: '/' },
            { label: 'AIアプリ', to: '/apps' },
            { label: PATCHFORM_LABEL, to: '/patchform' },
            { label: '手続き' },
          ]}
        />
        <div className='flex flex-col gap-2'>
          <h1 className='text-std-20B-160 lg:text-std-24B-150'>手続き</h1>
          <PatchformSubnav current='procedures' />
          <p className='text-std-16N-170 text-solid-gray-700'>
            手続きを公開して、受付可能な状態にします。「一覧」で公開中の手続きを見ることができます。「作成」で新たに手続きを作成します。
          </p>
        </div>

        <PatchformPaneTabs
          label='手続きの作成と一覧'
          current={pane}
          tabs={[
            { id: 'list', label: `一覧（${procedures.length}）`, to: '/patchform/procedures', icon: PiListBold },
            { id: 'new', label: '作成', to: '/patchform/procedures?tab=new', icon: PiNotePencilBold },
          ]}
        />

        {pane === 'new' ? (
        <>
        <PatchformProcedureCoach
          title='操作の流れ'
          lead='今の段階が枠で示されます。ボタンを押すと次の画面へ進みます。'
          steps={[
            {
              id: 'guide',
              label: 'フォームを作成する',
              done: forms.length > 0 || procedures.length > 0,
              hint: '申請フォームかナビゲーションフォームを、「フォーム作成」で作ります。',
              action: { label: 'フォーム作成へ', to: '/patchform?tab=new' },
            },
            {
              id: 'map',
              label: '手続きを作る',
              done: procedures.length > 0,
              hint: '下の作成欄から始めます。1枚だけなら「ナビゲーションフォームは使わない」を選びます。',
              action: { label: '下の作成欄へ', onClick: goCreate },
            },
            {
              id: 'publish',
              label: '手続きを公開する',
              done: Boolean(publishedProc),
              hint: '公開すると、申請者や回答者が使える受付が始まります。',
              action: draftProc
                ? { label: `「${draftProc.name}」を開く`, to: `/patchform/procedures/${draftProc.id}` }
                : { label: '作成タブへ', onClick: goCreate },
            },
            {
              id: 'try',
              label: '届いた申請は申請受付で見る',
              done: false,
              hint: '申請者や回答者が質問に答えると、必要な申請の一覧ができます。進捗は申請受付で見ます。',
              action: { label: '申請受付を開く', to: '/patchform/inbox' },
            },
          ]}
        />

        <section id='pf-proc-create' className='flex flex-col gap-4'>
          <h2 className='text-std-18B-160'>新しい手続き</h2>
          <p className='text-std-16N-170 text-solid-gray-700'>
            手続きを作成して公開します。手順に沿って作業してください。
          </p>
          <div className='rounded-8 border border-solid-gray-420 bg-white px-4 py-4'>
            {forms.length === 0 ? (
              <div className='mt-4 flex flex-col gap-3'>
                <p className='text-dns-16N-130 text-solid-gray-700'>
                  まだ選べるフォームがありません。先にフォームを作成してください。
                </p>
                <div>
                  <Link to='/patchform?tab=new' className='inline-flex'>
                    <Button type='button' variant='solid-fill' size='md'>
                      フォームを作成する
                    </Button>
                  </Link>
                </div>
              </div>
            ) : (
            <form onSubmit={(e) => void onSubmit(e)} className='mt-6 flex flex-col gap-4'>
              <div>
                <Label htmlFor='pf-proc-name' size='sm'>
                  名前
                </Label>
                <input
                  id='pf-proc-name'
                  className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2 text-std-16N-170'
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder='例: 転入の手続き'
                  required
                />
                <p className='mt-1 text-dns-14N-130 text-solid-gray-600'>
                  庁内の一覧で使う名前です。
                </p>
              </div>
              <div>
                <Label htmlFor='pf-proc-desc' size='sm'>
                  説明（任意）
                </Label>
                <textarea
                  id='pf-proc-desc'
                  className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2 text-std-16N-170'
                  rows={2}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder='例: 転入・転居のときに出す書類を振り分けます'
                />
                <p className='mt-1 text-dns-14N-130 text-solid-gray-600'>
                  職員向けのメモです。空欄でも構いません。
                </p>
              </div>
              <fieldset>
                <legend className='text-std-16B-150'>始め方</legend>
                <div className='mt-2 flex flex-col gap-2'>
                  <label className='flex items-start gap-2 text-std-16N-170'>
                    <input
                      type='radio'
                      name='pf-proc-start'
                      className='mt-1'
                      checked={omitNav}
                      onChange={() => chooseStartMode('omit')}
                    />
                    <span>
                      ナビゲーションフォームは使わない
                      <span className='mt-0.5 block text-dns-14N-130 text-solid-gray-600'>
                        申請フォーム１枚だけの手続きの場合は、ナビゲーションフォームは不要です。
                      </span>
                    </span>
                  </label>
                  <label className='flex items-start gap-2 text-std-16N-170'>
                    <input
                      type='radio'
                      name='pf-proc-start'
                      className='mt-1'
                      checked={!omitNav}
                      onChange={() => chooseStartMode('navigate')}
                    />
                    <span>
                      ナビゲーションフォームを使う
                      <span className='mt-0.5 block text-dns-14N-130 text-solid-gray-600'>
                        申請者の状況に応じて複数の申請フォームの組み合わせを変える場合に使います。
                      </span>
                    </span>
                  </label>
                </div>
              </fieldset>
              <div>
                <Label htmlFor='pf-proc-guide' size='sm'>
                  {omitNav ? '申請フォーム' : 'ナビゲーションフォーム'}
                </Label>
                <select
                  id='pf-proc-guide'
                  className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2 text-std-16N-170'
                  value={guideFormId}
                  onChange={(e) => setGuideFormId(e.target.value)}
                  required
                >
                  <option value=''>{omitNav ? '申請フォームを選ぶ' : 'ナビゲーションフォームを選ぶ'}</option>
                  {selectableForms.map((f) => (
                    <option key={f.id} value={f.id}>
                      {f.title}（{f.locked || f.work_status === 'ready' ? '作成完了' : '作成中'}
                      {f.has_opening ? ' · 受付中' : ''}
                      {(f.tags || []).length ? ` · ${(f.tags || []).join('、')}` : ''}）
                    </option>
                  ))}
                </select>
                <p className='mt-1 text-dns-14N-130 text-solid-gray-600'>
                  表示させるフォームを選んでください。
                </p>
                {selectableForms.length === 0 ? (
                  <p className='mt-2 text-dns-16N-130 text-solid-gray-700'>
                    {omitNav
                      ? '選べる申請フォームがありません。'
                      : '選べるナビゲーションフォームがありません。'}
                    <Link
                      to='/patchform?tab=new'
                      className='ml-1 text-blue-900 underline-offset-2 hover:underline'
                    >
                      フォームを作成する
                    </Link>
                  </p>
                ) : null}
              </div>
              {error && (
                <p className='text-error-1' role='alert'>
                  {error}
                </p>
              )}
              <div>
                <Button type='submit' variant='solid-fill' size='md' aria-disabled={submitting}>
                  {submitting ? '作成中...' : '作成して編集する'}
                </Button>
              </div>
            </form>
            )}
          </div>

          <p className='text-center text-std-16B-150 text-solid-gray-700' role='separator'>
            または
          </p>

          <div id='pf-proc-ai' className='rounded-8 border border-solid-gray-300 bg-solid-gray-50 px-4 py-4'>
            <h3 className='text-std-16B-150'>手引きファイルで省略（任意）</h3>
            <p className='mt-1 text-dns-16N-130 text-solid-gray-700'>
              手引きや庁内マニュアルのファイルを選ぶと、質問・申請用紙・答えの対応をまとめて下書きします。公開はしません。あとから内容を確認してください。
            </p>
            <div className='mt-4'>
              <FilePickButton
                id='pf-proc-guide-file'
                accept='.txt,.md,.pdf,.docx,.xlsx,.csv,.html,text/plain,text/markdown,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                disabled={readingFile || assistBusy}
                busy={readingFile}
                busyLabel='読み取り中...'
                filename={guideFileName}
                buttonLabel='手引きファイルを選ぶ'
                onFile={(file) => {
                  setGuideFileName(file?.name || '');
                  void onPickGuide(file);
                }}
              />
              <p className='mt-1 text-dns-14N-130 text-solid-gray-600'>
                txt / md / pdf / Word（docx） / Excel（xlsx）を選べます。古い Word（doc）や PowerPoint、スキャン画像だけの PDF は読めません。
              </p>
              {guideText.trim() ? (
                <p className='mt-2 text-dns-16N-130 text-solid-gray-700'>
                  ファイルを読み込みました（{guideText.trim().length.toLocaleString('ja-JP')}文字）。下のボタンで下書きを作れます。
                </p>
              ) : null}
            </div>
            <p className='mt-3 text-dns-14N-130 text-solid-gray-600'>
              自動作成に使います: {config?.llm?.model || '（未設定）'}。うまく作れないときはひな型を使います。
            </p>
            {(assistError || aiNotes) && (
              <p
                className={assistError ? 'mt-2 text-error-1' : 'mt-2 text-solid-gray-700'}
                role={assistError ? 'alert' : undefined}
              >
                {assistError || aiNotes}
              </p>
            )}
            <div className='mt-4'>
              <Button
                type='button'
                variant='outline'
                size='md'
                aria-disabled={assistBusy || readingFile || !guideText.trim()}
                onClick={() => void onDraftFromGuide()}
              >
                {assistBusy || readingFile ? '作成中...' : '第1版を作って編集する'}
              </Button>
            </div>
          </div>
        </section>
        </>
        ) : (
        <section className='flex flex-col gap-3'>
          <div className='flex flex-wrap items-center justify-between gap-2'>
            <h2 className='text-std-18B-160'>手続き一覧</h2>
            <Link to='/patchform/procedures?tab=new' className='inline-flex'>
              <Button type='button' variant='solid-fill' size='sm'>
                新しい手続きを作る
              </Button>
            </Link>
          </div>
          {isLoading ? (
            <p className='text-solid-gray-600'>読み込み中...</p>
          ) : loadError ? (
            <p className='text-error-1' role='alert'>
              {loadError}
            </p>
          ) : procedures.length === 0 ? (
            <p className='text-solid-gray-600'>
              まだ手続きがありません。
              <Link
                to='/patchform/procedures?tab=new'
                className='ml-1 text-blue-900 underline-offset-2 hover:underline'
              >
                作成タブから作る
              </Link>
            </p>
          ) : (
            <ul className='divide-y divide-solid-gray-300 border-y border-solid-gray-300'>
              {procedures.map((p) => (
                <li key={p.id} className='py-3'>
                  <Link
                    to={`/patchform/procedures/${p.id}`}
                    className='text-std-16B-150 text-blue-900 underline-offset-2 hover:underline'
                  >
                    {p.name}
                  </Link>
                  <p className='text-dns-14N-130 text-solid-gray-600'>
                    {statusLabel[p.status] || p.status}
                    {p.guide_title
                      ? ` / ${omitsNavigation(p) ? '申請フォーム' : '案内'}: ${p.guide_title}`
                      : ''}
                    {' / '}
                    {new Date(p.updated_at).toLocaleString('ja-JP')}
                  </p>
                  <div className='mt-2'>
                    <ProcedureReceptionActions
                      procedureId={p.id}
                      name={p.name}
                      status={p.status}
                      publicUrl={p.status === 'published' ? p.guide_public_url : null}
                      canEdit={p.can_edit}
                      submitting={submitting}
                      republish={p.guide_status === 'closed'}
                      onPublish={async () => {
                        const next = await setStatus(p.id, 'published');
                        if (next) await mutate();
                      }}
                      onClose={async () => {
                        if (
                          !window.confirm(
                            '受付を終了しますか。新しい申請は止まります。届いている申請は残ります。',
                          )
                        ) {
                          return;
                        }
                        const next = await setStatus(p.id, 'draft');
                        if (next) await mutate();
                      }}
                    />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
        )}
      </div>
    </LayoutBody>
  );
};
