import { useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router';
import {
  PiArrowDownBold,
  PiArrowUpBold,
  PiCheckCircleFill,
  PiFileTextBold,
  PiNotePencilBold,
  PiPaperclipBold,
  PiSignpostBold,
} from 'react-icons/pi';
import { BreadcrumbsNav } from '@/components/ui/BreadcrumbsNav';
import { Button } from '@/components/ui/dads/Button';
import { Disclosure, DisclosureSummary } from '@/components/ui/dads/Disclosure';
import { PageTitle } from '@/components/PageTitle';
import { LayoutBody } from '@/layout/LayoutBody';
import { PatchformApiScope, createGuestFormApi, usePatchformApi } from './PatchformApiContext';
import { PatchformFillModal } from './PatchformFillModal';
import { clearSession, readSession } from './guest/guestSession';
import { PATCHFORM_LABEL } from './labels';
import { usePatchformRoutes } from './routes';
import { answerRows } from './runtime/formatAnswer';
import { omitsNavigation } from './types';
import type { ApplicationItem } from './types';
import {
  usePatchformApplication,
  usePatchformApplicationItems,
  usePatchformList,
  usePatchformProcedure,
  usePatchformProcedureCatalog,
  usePatchformProjectActions,
  usePatchformRuntime,
} from './usePatchform';

const OTHER_ATTACH_SLOT = 'attach:__other__';

const statusLabel: Record<string, string> = {
  none: '未充足',
  draft: '記入中',
  submitted: '提出済',
  withdrawn: '取下げ',
};

const kindLabel: Record<string, string> = {
  data: '記入必須',
  yoshiki: '様式',
  attach: '添付',
};

const kindIcon = (kind: string) => {
  if (kind === 'attach') return PiPaperclipBold;
  if (kind === 'data') return PiNotePencilBold;
  return PiFileTextBold;
};

const statusTone: Record<string, string> = {
  submitted: 'text-green-800',
  draft: 'text-blue-900',
  withdrawn: 'text-error-1',
  none: 'text-solid-gray-500',
};

export const PatchformApplicationPage = () => {
  const { applicationId } = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const api = usePatchformApi();
  const routes = usePatchformRoutes();
  // 共有リンク（匿名）束か。匿名では閲覧・記入・枠追加・DL まで可能とし、
  // 提出・状態管理・履歴はログインで引き取り（claim）後にマイ手続きで行う。
  const anon = routes.mode === 'anonymous';
  // マイ手続き（本人）経由か、申請受付（レビュー）経由かでパンくずを出し分ける。
  const fromMy = searchParams.get('from') === 'my';
  // 申請受付（受領側）から開いたときは、内容の閲覧とダウンロードだけに限定する。
  // 条件変更・記入・添付・提出などの編集操作は申請者本人（マイ手続き）だけが行える。
  // 匿名の共有リンク束は編集可（提出のみ claim 後）なので readOnly から除く。
  const readOnly = !fromMy && !anon;
  const { application, isLoading, loadError, mutate } = usePatchformApplication(applicationId);
  const { procedure } = usePatchformProcedure(application?.procedure_id);
  const { slots: catalogSlots } = usePatchformProcedureCatalog(application?.procedure_id);
  const { forms: allForms } = usePatchformList();
  const {
    addItem,
    fulfillWithFile,
    clearFile,
    setSource,
    reorder,
    removeItem,
    busy,
    error: itemError,
  } = usePatchformApplicationItems();
  const { setStatus, busy: statusBusy } = usePatchformProjectActions();
  const { downloadItemFile, downloadItemTemplate } = usePatchformRuntime();
  const notice = application?.notice;
  const [catalogPick, setCatalogPick] = useState('');
  const [attachTitle, setAttachTitle] = useState('');
  const [condOpen, setCondOpen] = useState(true);
  const [fillItem, setFillItem] = useState<ApplicationItem | null>(null);
  const fileInputs = useRef<Record<string, HTMLInputElement | null>>({});
  // 匿名記入モーダルは item の guest_token に固定した公開フォームAPIで動かす。
  const fillApi = useMemo(
    () => (anon && fillItem ? createGuestFormApi(fillItem.guest_token ?? '') : null),
    [anon, fillItem],
  );

  const allItems = application?.items ?? [];
  // 選択肢のない「申請用紙1枚」の手続きは、案内(nav)ではなく通常の申請フォーム
  // として扱う（上部の「申請条件」は出さず、提出書類一覧にそのまま並べる）。
  const singleForm = Boolean(procedure && omitsNavigation(procedure));
  // 案内（ナビ）は提出書類ではないので一覧から分け、上部の「申請条件」に集約する。
  const navItem = singleForm ? null : (allItems.find((it) => it.kind === 'data') ?? null);
  const items = singleForm ? allItems : allItems.filter((it) => it.kind !== 'data');
  const aid = application?.id;
  const navRows =
    navItem?.status === 'submitted' && navItem.definition && navItem.answers
      ? answerRows(navItem.definition.components, navItem.answers)
      : [];
  // 「条件を変更」は案内フォームを直接開かず、作成時と同じウィザードを既存
  // プロジェクト編集モード（?app=）で開く。回答は現在の内容が引き継がれる。
  const condWizardTo =
    application?.procedure_id && aid
      ? routes.wizard(application.procedure_id, { app: aid })
      : routes.mode === 'internal' && navItem?.form_id
        ? `/patchform/${navItem.form_id}?app=${encodeURIComponent(application?.token ?? '')}&item=${encodeURIComponent(navItem.id)}${fromMy ? '&from=my' : ''}`
        : null;

  const onAddCatalog = async () => {
    if (!aid || !catalogPick) return;
    const updated = await addItem(aid, { form_id: catalogPick });
    if (updated) {
      setCatalogPick('');
      await mutate(updated, { revalidate: false });
    }
  };

  const onAddAttach = async () => {
    if (!aid || !attachTitle.trim()) return;
    const updated = await addItem(aid, { title: attachTitle.trim() });
    if (updated) {
      setAttachTitle('');
      await mutate(updated, { revalidate: false });
    }
  };

  const onDuplicate = async (item: ApplicationItem) => {
    if (!aid) return;
    const updated = await addItem(aid, { duplicate_of: item.id });
    if (updated) await mutate(updated, { revalidate: false });
  };

  const onRemove = async (item: ApplicationItem) => {
    if (!aid) return;
    if (!window.confirm(`「${item.title}」の枠を削除します。よろしいですか？`)) return;
    const updated = await removeItem(aid, item.id);
    if (updated) await mutate(updated, { revalidate: false });
  };

  const onPickFile = async (item: ApplicationItem, file: File | undefined) => {
    if (!aid || !file) return;
    const updated = await fulfillWithFile(aid, item.id, file);
    if (updated) await mutate(updated, { revalidate: false });
  };

  const onClearFile = async (item: ApplicationItem) => {
    if (!aid) return;
    const updated = await clearFile(aid, item.id);
    if (updated) await mutate(updated, { revalidate: false });
  };

  const onSetSource = async (item: ApplicationItem, source: 'form' | 'file') => {
    if (!aid) return;
    const updated = await setSource(aid, item.id, source);
    if (updated) await mutate(updated, { revalidate: false });
  };

  const onMove = async (index: number, dir: 'up' | 'down') => {
    if (!aid) return;
    const j = dir === 'up' ? index - 1 : index + 1;
    if (j < 0 || j >= items.length) return;
    const next = [...items];
    [next[index], next[j]] = [next[j], next[index]];
    // ナビ（案内）は先頭に固定し、提出書類の並びだけを保存する。
    const order = [...(navItem ? [navItem.id] : []), ...next.map((it) => it.id)];
    const updated = await reorder(aid, order);
    if (updated) await mutate(updated, { revalidate: false });
  };

  const effectiveStatus = application?.status?.effective ?? '';
  const submitted = effectiveStatus === '提出済' || effectiveStatus === '完了';
  const readyToSubmit = effectiveStatus === '準備完了';

  const onSubmitApp = async () => {
    if (!aid) return;
    if (!window.confirm('この内容で提出済みにします。よろしいですか？')) return;
    const updated = await setStatus(aid, '提出済');
    if (updated) await mutate(updated, { revalidate: false });
  };

  const onUnsubmitApp = async () => {
    if (!aid) return;
    // 上書きを解除して自動状態（準備完了 など）へ戻す。
    const updated = await setStatus(aid, '');
    if (updated) await mutate(updated, { revalidate: false });
  };

  const [claimBusy, setClaimBusy] = useState(false);
  const [claimError, setClaimError] = useState<string | null>(null);
  // 匿名束を「マイ手続き」へ引き取る。未ログインならログインへ誘導し、戻り先 token を
  // 保持して GuestVerify 側で自動 claim させる。ログイン済みならその場で claim する。
  // ログイン画面へ誘導する。戻り先 token を保持して GuestVerify 側で自動 claim させる。
  const goLoginForClaim = (token: string) => {
    try {
      sessionStorage.setItem('pf_pending_claim', token);
    } catch {
      // sessionStorage 不可でも致命ではない（ログイン後に再度ボタンを押せばよい）。
    }
    navigate('/public/mine');
  };

  const onClaim = async () => {
    const token = application?.token || applicationId || '';
    if (!token) return;
    if (!readSession()) {
      goLoginForClaim(token);
      return;
    }
    setClaimBusy(true);
    setClaimError(null);
    try {
      const res = await api.post<{ id: string }>(
        `/public/api/applications/${encodeURIComponent(token)}/claim`,
      );
      const id = res.data?.id;
      if (id) {
        navigate(`/public/mine/${encodeURIComponent(id)}?from=my`);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : '引き取りに失敗しました';
      // セッション失効（例: サーバ再起動で署名鍵が変わった）なら、古いセッションを
      // 破棄してログインへ。email だけ残って操作が失敗し続ける状態を防ぐ。
      if (/セッション|認証|失効|期限/.test(msg)) {
        clearSession();
        goLoginForClaim(token);
        return;
      }
      setClaimError(msg);
    } finally {
      setClaimBusy(false);
    }
  };

  // 「枠を足す」の提案: いま束にあるフォームと同じタグを持つ、公開中の別フォーム。
  const inBundleFormIds = new Set(
    allItems.map((it) => it.form_id).filter((v): v is string => Boolean(v)),
  );
  const referenceTags = new Set<string>();
  for (const f of allForms) {
    const isInBundle =
      inBundleFormIds.has(f.id) ||
      (f.receptions || []).some((r) => inBundleFormIds.has(r.id));
    if (isInBundle) for (const t of f.tags || []) referenceTags.add(t);
  }
  const relatedForms = allForms.filter((f) => {
    if (!f.has_opening) return false; // 公開（受付中）のみ
    if (inBundleFormIds.has(f.id)) return false;
    if ((f.receptions || []).some((r) => inBundleFormIds.has(r.id))) return false;
    return (f.tags || []).some((t) => referenceTags.has(t));
  });

  const onAddRelated = async (formId: string) => {
    if (!aid) return;
    const updated = await addItem(aid, { form_id: formId });
    if (updated) await mutate(updated, { revalidate: false });
  };

  return (
    <LayoutBody>
      <PageTitle title={application?.procedure_name || '申請'} />
      <div className='mx-auto flex w-full max-w-(--page-width) flex-col gap-6 p-6 lg:p-8'>
        <BreadcrumbsNav
          items={
            anon
              ? [
                  {
                    label:
                      application?.title || application?.procedure_name || '申請',
                  },
                ]
              : fromMy
              ? [
                  ...routes.homeCrumbs,
                  { label: routes.myListLabel, to: routes.myList },
                  {
                    label:
                      application?.title || application?.procedure_name || '手続き',
                  },
                ]
              : [
                  { label: 'ホーム', to: '/' },
                  { label: 'AIアプリ', to: '/apps' },
                  { label: PATCHFORM_LABEL, to: '/patchform' },
                  { label: '申請受付', to: '/patchform/inbox' },
                  ...(application?.procedure_id
                    ? [
                        {
                          label: application.procedure_name,
                          to: `/patchform/inbox/${application.procedure_id}`,
                        },
                      ]
                    : []),
                  { label: application?.token || '申請' },
                ]
          }
        />
        {isLoading && <p className='text-solid-gray-600'>読み込み中...</p>}
        {loadError && (
          <p className='text-error-1' role='alert'>
            {loadError}
          </p>
        )}
        {application && (
          <>
            <div className='flex flex-col gap-2'>
              <div className='flex flex-wrap items-center gap-2'>
                <h1 className='text-std-20B-160 lg:text-std-24B-150'>
                  {application.title || application.procedure_name}
                </h1>
                {application.status && (
                  <span
                    className={`rounded-4 border px-2 py-0.5 text-dns-14N-130 ${
                      application.status.effective === '提出済' ||
                      application.status.effective === '完了'
                        ? 'border-green-600 bg-green-50 text-green-800'
                        : application.status.effective === '準備完了'
                          ? 'border-amber-600 bg-amber-50 text-amber-800'
                          : application.status.effective === '作業中'
                            ? 'border-blue-900 bg-blue-50 text-blue-900'
                            : application.status.effective === '取下げ'
                              ? 'border-error-1 bg-red-50 text-error-1'
                              : 'border-solid-gray-420 bg-solid-gray-50 text-solid-gray-700'
                    }`}
                  >
                    {application.status.effective}
                  </span>
                )}
              </div>
              <p className='text-std-16N-170 text-solid-gray-700'>
                案内番号: {application.token}
              </p>
              {application.procedure_description && (
                <p className='text-std-16N-170 text-solid-gray-700'>
                  {application.procedure_description}
                </p>
              )}
              <p className='text-dns-14N-130 text-solid-gray-600'>公開 URL: {application.public_url}</p>
            </div>
            {anon ? (
              <section className='flex flex-wrap items-center justify-between gap-3 rounded-8 border border-blue-900/30 bg-blue-50/60 p-4'>
                <div className='min-w-0'>
                  <p className='text-std-16N-170 text-solid-gray-800'>
                    この共有リンクでは、記入・書類の追加・ダウンロードができます。<strong>提出</strong>や進み具合の管理は、ログインして<strong>マイ手続き</strong>に引き取ってから行います。
                  </p>
                  {claimError && (
                    <p className='mt-1 text-error-1' role='alert'>
                      {claimError}
                    </p>
                  )}
                </div>
                <div className='flex shrink-0 flex-wrap gap-2'>
                  <Button
                    type='button'
                    variant='solid-fill'
                    size='md'
                    aria-disabled={claimBusy}
                    onClick={() => void onClaim()}
                  >
                    {claimBusy ? '処理中...' : 'マイ手続きで管理する（ログイン）'}
                  </Button>
                </div>
              </section>
            ) : readOnly ? (
              <p className='rounded-8 border border-blue-900/30 bg-blue-50/60 p-3 text-std-16N-170 text-solid-gray-800'>
                これは申請受付（受領側）の画面です。ファイルの追加・差し替えや内容の修正ができ、変更はすべて<strong>変更履歴</strong>に記録されます。ただし<strong>条件の変更</strong>と<strong>提出</strong>は申請者本人が行います。
              </p>
            ) : (
            <section className='flex flex-wrap items-center justify-between gap-3 rounded-8 border border-solid-gray-300 bg-solid-gray-50 p-4'>
              <div className='min-w-0'>
                {submitted ? (
                  <p className='text-std-16N-170 text-solid-gray-800'>
                    この手続きは<strong>提出済み</strong>です。内容を直したいときは提出を取り消してください。
                  </p>
                ) : readyToSubmit ? (
                  <p className='text-std-16N-170 text-solid-gray-800'>
                    必要な書類がそろいました。内容を確認し、提出できるときに「提出する」を押してください。
                  </p>
                ) : (
                  <p className='text-std-16N-170 text-solid-gray-700'>
                    書類がそろうと「提出する」ボタンが押せます。提出は自動では行いません。
                  </p>
                )}
              </div>
              <div className='flex shrink-0 flex-wrap gap-2'>
                {submitted ? (
                  <Button
                    type='button'
                    variant='outline'
                    size='md'
                    aria-disabled={statusBusy}
                    onClick={() => void onUnsubmitApp()}
                  >
                    提出を取り消す
                  </Button>
                ) : (
                  <Button
                    type='button'
                    variant='solid-fill'
                    size='md'
                    aria-disabled={statusBusy || !readyToSubmit}
                    onClick={() => void onSubmitApp()}
                  >
                    提出する
                  </Button>
                )}
              </div>
            </section>
            )}
            {navItem && (
              <section className='flex flex-col gap-3 rounded-8 border border-blue-900/40 bg-blue-50/50 p-4'>
                <div className='flex flex-wrap items-center justify-between gap-2'>
                  <button
                    type='button'
                    className='flex items-center gap-2 text-std-18B-160 text-blue-900'
                    aria-expanded={condOpen}
                    onClick={() => setCondOpen((v) => !v)}
                  >
                    <PiSignpostBold className='size-5' />
                    申請条件（案内の回答）
                    <span className='text-dns-14N-130 text-blue-900/70'>
                      {condOpen ? '（閉じる）' : '（開く）'}
                    </span>
                  </button>
                  {condWizardTo && !readOnly && (
                    <Link to={condWizardTo} className='inline-flex'>
                      <Button type='button' variant='outline' size='sm'>
                        {navRows.length > 0 ? '条件を変更' : '条件を入力'}
                      </Button>
                    </Link>
                  )}
                </div>
                {condOpen && (
                  <div className='flex flex-col gap-4'>
                    {navRows.length > 0 ? (
                      <dl className='grid gap-1 text-std-16N-170 sm:grid-cols-[10rem_1fr]'>
                        {navRows.map((row) => (
                          <div key={row.id} className='contents'>
                            <dt className='text-solid-gray-600'>{row.label}</dt>
                            <dd className='whitespace-pre-wrap text-solid-gray-900'>{row.value}</dd>
                          </div>
                        ))}
                      </dl>
                    ) : (
                      <p className='text-std-16N-170 text-solid-gray-700'>
                        案内に答えると、この申請に必要な書類が提出書類一覧に並びます。
                      </p>
                    )}
                    {(notice?.notes || []).length > 0 && (
                      <div className='rounded-8 border border-blue-900/20 bg-white/70 p-3'>
                        <h3 className='text-std-16B-150 text-solid-gray-900'>解説</h3>
                        <ul className='mt-1 list-disc pl-5 text-std-16N-170 text-solid-gray-800'>
                          {notice?.notes?.map((n) => (
                            <li key={n}>{n}</li>
                          ))}
                        </ul>
                        <p className='mt-2 text-dns-14N-130 text-solid-gray-500'>
                          解説は、選んだ条件（案内の回答）ごとに手続き側で用意された補足です。
                        </p>
                      </div>
                    )}
                    {(notice?.prepare || []).length > 0 && (
                      <div className='rounded-8 border border-blue-900/20 bg-white/70 p-3'>
                        <h3 className='text-std-16B-150 text-solid-gray-900'>準備するもの</h3>
                        <ul className='mt-1 list-disc pl-5 text-std-16N-170 text-solid-gray-800'>
                          {notice?.prepare?.map((n) => (
                            <li key={n}>{n}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                )}
              </section>
            )}
            <section className='flex flex-col gap-2'>
              <div className='flex flex-wrap items-baseline justify-between gap-2'>
                <h2 className='text-std-18B-160'>提出書類一覧</h2>
                {items.length > 0 && (
                  <span className='text-dns-14N-130 text-solid-gray-600'>
                    {items.filter((f) => f.status === 'submitted').length} / {items.length} 充足
                  </span>
                )}
              </div>
              <p className='text-dns-14N-130 text-solid-gray-600'>
                初期の並び順は「案内で必要になった様式 → 準備するもの（添付） → あとから足した枠」の順です。左の
                ↑↓ で申請しやすい順に並び替えできます。
              </p>
              {itemError && (
                <p className='text-error-1' role='alert'>
                  {itemError}
                </p>
              )}
              {items.length === 0 ? (
                <p className='text-solid-gray-600'>この回答では推奨する枠がありません。操作方法から足せます。</p>
              ) : (
                <div className='overflow-x-auto rounded-8 border border-solid-gray-300'>
                  <table className='w-full min-w-[calc(780/16*1rem)] border-collapse text-std-16N-170'>
                    <thead>
                      <tr className='border-b border-solid-gray-300 bg-solid-gray-50 text-left text-dns-14N-130 text-solid-gray-600'>
                        <th scope='col' className='w-[calc(56/16*1rem)] px-2 py-2 text-center font-normal'>
                          並び
                        </th>
                        <th scope='col' className='px-3 py-2 font-normal'>
                          書類名
                        </th>
                        <th scope='col' className='w-[calc(80/16*1rem)] px-3 py-2 font-normal'>
                          種別
                        </th>
                        <th scope='col' className='w-[calc(180/16*1rem)] px-3 py-2 font-normal'>
                          状態
                        </th>
                        <th scope='col' className='w-[calc(150/16*1rem)] px-3 py-2 font-normal'>
                          更新
                        </th>
                        <th scope='col' className='w-[calc(220/16*1rem)] px-3 py-2 font-normal'>
                          操作
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((f, index) => {
                        const rows =
                          (f.definition && f.answers)
                            ? answerRows(f.definition.components, f.answers)
                            : [];
                        // 記入と添付は併存できる。ファイルがあるか / 記入済みか を別々に見る。
                        const hasFile = f.file_attached ?? f.fulfillment === 'file';
                        const done = f.status === 'submitted';
                        // 単一フォームでは案内(nav)扱いにせず、通常の申請フォームとして表示する。
                        const isNav = f.kind === 'data' && !singleForm;
                        // 実入力欄を持つオンラインフォームがある枠は、添付の有無に関わらず記入も許す。
                        const canFill = f.can_fill_online && !isNav;
                        // 採用中の申請データ（fulfillment 未指定なら添付優先の従来動作）。
                        const adopted: 'form' | 'file' =
                          f.fulfillment === 'file'
                            ? 'file'
                            : f.fulfillment === 'form'
                              ? 'form'
                              : hasFile
                                ? 'file'
                                : 'form';
                        const bothAvailable = Boolean(f.form_submitted) && hasFile;
                        const Icon = isNav ? PiSignpostBold : kindIcon(f.kind);
                        const fillTo = `/patchform/${f.form_id}?app=${encodeURIComponent(application.token)}&item=${encodeURIComponent(f.id)}${fromMy ? '&from=my' : ''}`;
                        const displayTitle =
                          f.slot_id === OTHER_ATTACH_SLOT
                            ? 'その他（別途ファイルを添付する場合にお使いください）'
                            : f.title;
                        // 案内以外で、複製またはあとから足した枠は削除できる。
                        const removable =
                          f.kind !== 'data' &&
                          (f.copy_index > 0 || (f.added_by !== '' && f.added_by !== 'system'));
                        return (
                          <tr
                            key={f.id}
                            className={`border-b border-solid-gray-200 last:border-b-0 align-top hover:bg-solid-gray-50 ${
                              isNav ? 'bg-blue-50/40' : ''
                            }`}
                          >
                            <td className='px-2 py-2.5'>
                              <div className='flex flex-col items-center gap-1'>
                                <button
                                  type='button'
                                  aria-label='上へ移動'
                                  className='rounded-4 border border-solid-gray-300 p-1 text-solid-gray-600 hover:bg-solid-gray-100 disabled:opacity-30'
                                  disabled={busy || index === 0}
                                  onClick={() => void onMove(index, 'up')}
                                >
                                  <PiArrowUpBold className='size-4' />
                                </button>
                                <button
                                  type='button'
                                  aria-label='下へ移動'
                                  className='rounded-4 border border-solid-gray-300 p-1 text-solid-gray-600 hover:bg-solid-gray-100 disabled:opacity-30'
                                  disabled={busy || index === items.length - 1}
                                  onClick={() => void onMove(index, 'down')}
                                >
                                  <PiArrowDownBold className='size-4' />
                                </button>
                              </div>
                            </td>
                            <td className='px-3 py-2.5'>
                              <div className='flex items-start gap-2'>
                                <span
                                  className={`relative mt-0.5 inline-flex flex-none ${
                                    isNav ? 'text-blue-900' : 'text-solid-gray-500'
                                  }`}
                                >
                                  <Icon className='size-5' aria-hidden={true} />
                                  {done && (
                                    <PiCheckCircleFill className='absolute -right-1 -bottom-1 size-3 text-green-700' />
                                  )}
                                </span>
                                <div className='min-w-0'>
                                  <div className='flex flex-wrap items-center gap-1.5'>
                                    {isNav ? (
                                      <Link
                                        to={fillTo}
                                        className='text-std-16B-150 text-blue-900 underline-offset-2 hover:underline'
                                      >
                                        {displayTitle}
                                        {f.copy_index ? `（${f.copy_index + 1}件目）` : ''}
                                      </Link>
                                    ) : canFill ? (
                                      <button
                                        type='button'
                                        className='text-left text-std-16B-150 text-blue-900 underline-offset-2 hover:underline'
                                        onClick={() => setFillItem(f)}
                                      >
                                        {displayTitle}
                                        {f.copy_index ? `（${f.copy_index + 1}件目）` : ''}
                                      </button>
                                    ) : (
                                      <span className='text-std-16B-150 text-solid-gray-900'>
                                        {displayTitle}
                                        {f.copy_index ? `（${f.copy_index + 1}件目）` : ''}
                                      </span>
                                    )}
                                    {isNav && (
                                      <span className='rounded-4 border border-blue-900 bg-blue-50 px-1.5 py-0.5 text-dns-14N-130 text-blue-900'>
                                        ナビゲーション
                                      </span>
                                    )}
                                  </div>
                                  {f.template && aid && (
                                    <div>
                                      <button
                                        type='button'
                                        className='text-left text-dns-14N-130 text-blue-900 underline-offset-2 hover:underline'
                                        onClick={() =>
                                          void downloadItemTemplate(
                                            aid,
                                            f.id,
                                            f.template?.filename,
                                          )
                                        }
                                      >
                                        様式ひな型をDL（{f.template.filename}）
                                      </button>
                                    </div>
                                  )}
                                  {rows.length > 0 && (
                                    <details className='mt-0.5 text-dns-14N-130'>
                                      <summary className='cursor-pointer text-solid-gray-700'>
                                        記入内容（{rows.length}項目）
                                      </summary>
                                      <dl className='mt-1 grid gap-1'>
                                        {rows.map((row) => (
                                          <div key={row.id} className='grid gap-0.5'>
                                            <dt className='text-solid-gray-600'>{row.label}</dt>
                                            <dd className='whitespace-pre-wrap text-solid-gray-900'>
                                              {row.value}
                                            </dd>
                                          </div>
                                        ))}
                                      </dl>
                                    </details>
                                  )}
                                </div>
                              </div>
                            </td>
                            <td className='px-3 py-2.5 text-dns-14N-130 text-solid-gray-700'>
                              {isNav
                                ? '案内'
                                : f.kind === 'data'
                                  ? '申請フォーム'
                                  : kindLabel[f.kind] || f.kind}
                            </td>
                            <td className='px-3 py-2.5'>
                              <span
                                className={`text-dns-14N-130 ${statusTone[f.status] || 'text-solid-gray-600'}`}
                              >
                                {statusLabel[f.status] || f.status}
                              </span>
                              {hasFile && f.file_name && aid && (
                                <div className='break-all'>
                                  <button
                                    type='button'
                                    className='text-left text-dns-14N-130 text-blue-900 underline-offset-2 hover:underline'
                                    onClick={() =>
                                      void downloadItemFile(aid, f.id, f.file_name ?? undefined)
                                    }
                                  >
                                    {f.file_name}（ダウンロード）
                                  </button>
                                </div>
                              )}
                              {bothAvailable && (
                                <div className='mt-1 flex flex-col gap-0.5'>
                                  <span className='text-dns-14N-130 text-solid-gray-600'>
                                    申請データに採用:
                                  </span>
                                  <div className='inline-flex w-fit self-start overflow-hidden rounded-4 border border-solid-gray-400 text-dns-14N-130'>
                                    <button
                                      type='button'
                                      aria-pressed={adopted === 'form'}
                                      disabled={busy}
                                      className={`px-2 py-0.5 ${
                                        adopted === 'form'
                                          ? 'bg-blue-900 text-white'
                                          : 'bg-white text-solid-gray-700 hover:bg-solid-gray-100'
                                      }`}
                                      onClick={() => void onSetSource(f, 'form')}
                                    >
                                      記入
                                    </button>
                                    <button
                                      type='button'
                                      aria-pressed={adopted === 'file'}
                                      disabled={busy}
                                      className={`px-2 py-0.5 ${
                                        adopted === 'file'
                                          ? 'bg-blue-900 text-white'
                                          : 'bg-white text-solid-gray-700 hover:bg-solid-gray-100'
                                      }`}
                                      onClick={() => void onSetSource(f, 'file')}
                                    >
                                      添付
                                    </button>
                                  </div>
                                </div>
                              )}
                            </td>
                            <td className='px-3 py-2.5 text-dns-14N-130 text-solid-gray-500'>
                              {f.submitted_at
                                ? new Date(f.submitted_at).toLocaleString('ja-JP')
                                : '—'}
                            </td>
                            <td className='px-3 py-2.5'>
                              {!isNav ? (
                                <div className='flex flex-wrap gap-2'>
                                  {canFill && (
                                    <Button
                                      type='button'
                                      variant='outline'
                                      size='sm'
                                      onClick={() => setFillItem(f)}
                                    >
                                      {f.form_submitted ? '記入を修正' : 'オンラインで記入'}
                                    </Button>
                                  )}
                                  <input
                                    ref={(el) => {
                                      fileInputs.current[f.id] = el;
                                    }}
                                    type='file'
                                    className='hidden'
                                    onChange={(e) => void onPickFile(f, e.target.files?.[0])}
                                  />
                                  {hasFile ? (
                                    <Button
                                      type='button'
                                      variant='outline'
                                      size='sm'
                                      aria-disabled={busy}
                                      onClick={() => void onClearFile(f)}
                                    >
                                      添付を取消
                                    </Button>
                                  ) : (
                                    <Button
                                      type='button'
                                      variant='outline'
                                      size='sm'
                                      aria-disabled={busy}
                                      onClick={() => fileInputs.current[f.id]?.click()}
                                    >
                                      ファイルを添付
                                    </Button>
                                  )}
                                  <Button
                                    type='button'
                                    variant='outline'
                                    size='sm'
                                    aria-disabled={busy}
                                    onClick={() => void onDuplicate(f)}
                                  >
                                    もう1件
                                  </Button>
                                  {removable && (
                                    <Button
                                      type='button'
                                      variant='outline'
                                      size='sm'
                                      aria-disabled={busy}
                                      className='text-error-1'
                                      onClick={() => void onRemove(f)}
                                    >
                                      削除
                                    </Button>
                                  )}
                                </div>
                              ) : (
                                <span className='text-dns-14N-130 text-solid-gray-400'>—</span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            <div className='flex flex-col gap-3'>
                <div className='flex flex-col gap-3 rounded-8 border border-solid-gray-300 bg-white p-4'>
                  <h3 className='text-std-16B-150'>関連するフォームを足す</h3>
                  <p className='text-dns-14N-130 text-solid-gray-600'>
                    いまの書類と<strong>同じタグ</strong>が付いた、公開中のフォームを候補に出します。関連する様式はここから足せます。
                  </p>
                  {relatedForms.length > 0 ? (
                    <div className='flex flex-wrap gap-2'>
                      {relatedForms.map((f) => (
                        <Button
                          key={f.id}
                          type='button'
                          variant='outline'
                          size='sm'
                          aria-disabled={busy}
                          onClick={() => void onAddRelated(f.id)}
                        >
                          ＋ {f.title}
                        </Button>
                      ))}
                    </div>
                  ) : (
                    <p className='text-dns-14N-130 text-solid-gray-500'>
                      同じタグの公開フォームはありません。フォーム作成でタグを付けると、関連フォームがここに並びます。
                    </p>
                  )}
                  {catalogSlots.filter((s) => s.form_id).length > 0 && (
                    <div className='flex flex-wrap items-center gap-2 border-t border-solid-gray-200 pt-3'>
                      <label className='text-std-16N-170 text-solid-gray-700' htmlFor='catalog-pick'>
                        この手続きの様式から足す
                      </label>
                      <select
                        id='catalog-pick'
                        className='rounded border border-solid-gray-400 px-2 py-1 text-std-16N-170'
                        value={catalogPick}
                        onChange={(e) => setCatalogPick(e.target.value)}
                      >
                        <option value=''>選択してください</option>
                        {catalogSlots
                          .filter((s) => s.form_id)
                          .map((s) => (
                            <option key={s.slot_id} value={s.form_id ?? ''}>
                              {s.title}
                            </option>
                          ))}
                      </select>
                      <Button
                        type='button'
                        variant='outline'
                        size='sm'
                        aria-disabled={busy || !catalogPick}
                        onClick={() => void onAddCatalog()}
                      >
                        足す
                      </Button>
                    </div>
                  )}
                  <div className='flex flex-wrap items-center gap-2 border-t border-solid-gray-200 pt-3'>
                    <label className='text-std-16N-170 text-solid-gray-700' htmlFor='attach-title'>
                      添付を足す
                    </label>
                    <input
                      id='attach-title'
                      className='rounded border border-solid-gray-400 px-2 py-1 text-std-16N-170'
                      placeholder='例: 住民票の写し'
                      value={attachTitle}
                      onChange={(e) => setAttachTitle(e.target.value)}
                    />
                    <Button
                      type='button'
                      variant='outline'
                      size='sm'
                      aria-disabled={busy || !attachTitle.trim()}
                      onClick={() => void onAddAttach()}
                    >
                      足す
                    </Button>
                  </div>
                </div>
            </div>
            {!anon && application.events && application.events.length > 0 && (
              <Disclosure className='rounded-8 border border-solid-gray-300 bg-white px-4 py-3'>
                <DisclosureSummary>
                  <span className='text-std-16B-150'>
                    変更履歴（{application.events.length}件）
                  </span>
                </DisclosureSummary>
                <ol className='mt-3 flex flex-col gap-2'>
                  {application.events.map((ev, i) => (
                    <li
                      key={`${ev.created_at}-${i}`}
                      className='flex flex-col gap-1 border-b border-solid-gray-100 pb-2 last:border-0 last:pb-0'
                    >
                      <div className='flex flex-wrap items-baseline gap-x-2 gap-y-0.5'>
                        <span
                          className={`rounded-4 px-1.5 py-0.5 text-dns-12N-130 ${
                            ev.actor_role === '受付'
                              ? 'bg-amber-50 text-amber-800'
                              : 'bg-blue-50 text-blue-900'
                          }`}
                        >
                          {ev.actor_role}
                        </span>
                        <span className='text-std-14N-150 text-solid-gray-900'>
                          {ev.action}
                          {ev.target ? `：${ev.target}` : ''}
                          {ev.detail ? `（${ev.detail}）` : ''}
                        </span>
                        <span className='ml-auto text-dns-12N-130 text-solid-gray-500'>
                          {new Date(ev.created_at).toLocaleString('ja-JP')}
                        </span>
                      </div>
                      {ev.changes && ev.changes.length > 0 && (
                        <ul className='ml-2 flex flex-col gap-0.5 border-l-2 border-solid-gray-200 pl-3'>
                          {ev.changes.map((c, j) => (
                            <li
                              key={`${c.label}-${j}`}
                              className='text-dns-14N-130 text-solid-gray-700'
                            >
                              <span className='text-solid-gray-900'>{c.label}</span>：
                              <span className='text-solid-gray-500 line-through'>
                                {c.before || '（空）'}
                              </span>
                              <span className='mx-1'>→</span>
                              <span className='text-solid-gray-900'>
                                {c.after || '（空）'}
                              </span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </li>
                  ))}
                </ol>
              </Disclosure>
            )}
          </>
        )}
        {fillItem && application
          ? (() => {
              const modal = (
                <PatchformFillModal
                  open={true}
                  formId={fillItem.form_id ?? ''}
                  itemTitle={fillItem.title}
                  applicationToken={application.token}
                  applicationItemId={fillItem.id}
                  applicationId={aid}
                  application={application}
                  initialAnswers={fillItem.answers}
                  onClose={() => setFillItem(null)}
                  onSubmitted={(updated) => {
                    if (updated) {
                      void mutate(updated, { revalidate: false });
                    } else {
                      void mutate();
                    }
                  }}
                />
              );
              return fillApi ? (
                <PatchformApiScope api={fillApi}>{modal}</PatchformApiScope>
              ) : (
                modal
              );
            })()
          : null}
      </div>
    </LayoutBody>
  );
};
