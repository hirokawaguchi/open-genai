import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from 'react';
import {
  PiArrowCounterClockwiseBold,
  PiArrowDownBold,
  PiArrowUpBold,
  PiBookOpenBold,
  PiCopyBold,
  PiIdentificationCardBold,
  PiFilePlus,
  PiTrashBold,
} from 'react-icons/pi';
import { Navigate, useNavigate, useParams } from 'react-router';
import { PageTitle } from '@/components/PageTitle';
import {
  CustomDialog,
  CustomDialogBody,
  CustomDialogHeader,
  CustomDialogPanel,
} from '@/components/ui/CustomDialog';
import { Button } from '@/components/ui/dads/Button';
import { Input } from '@/components/ui/dads/Input';
import { ExAppUsageMarkdownRenderer } from '@/features/exapp/components/ExAppUsageMarkdownRenderer';
import { ManagedAppHeader } from '@/features/exapp/components/ManagedAppHeader';
import { useRegisteredAppMeta } from '@/features/exapp/hooks/useRegisteredAppMeta';
import { COMMON_EXAPPS_TEAM_ID } from '@/features/exapps/constants';
import { LayoutBody } from '@/layout/LayoutBody';
import { LEDGER_EXAPP_ID } from '@/layout/navItems';
import { teamApi } from '@/lib/fetcher';
import { officePathForFormat } from '../office/kinds';
import type {
  LedgerExtra,
  LedgerField,
  LedgerFile,
  LedgerGrant,
  LedgerRow,
  LedgerSystemField,
} from './types';
import {
  deleteLedger,
  ledgerError,
  patchLedger,
  saveLedger,
  saveRow,
  updateRow,
  useLedger,
  useLedgerConfig,
  useLedgerRow,
  useLedgerRows,
  useLedgers,
} from './useLedger';

const fieldClass =
  'mt-1 w-full rounded-8 border border-solid-gray-420 bg-white px-3 py-2 text-std-16N-170';

const SELECTED_KEY = 'open-genai-ledger-selected';

const rememberedLedger = () => {
  try {
    return sessionStorage.getItem(SELECTED_KEY) || '';
  } catch {
    return '';
  }
};

const rememberLedger = (id: string) => {
  try {
    if (id) sessionStorage.setItem(SELECTED_KEY, id);
    else sessionStorage.removeItem(SELECTED_KEY);
  } catch {
    /* 保存できなくても画面は動く */
  }
};

const ROW_KEY = 'open-genai-ledger-row';

const rememberedRow = (ledgerId: string) => {
  try {
    const parsed = JSON.parse(sessionStorage.getItem(ROW_KEY) || '') as {
      ledgerId?: string;
      rowId?: string;
    };
    return parsed.ledgerId === ledgerId ? parsed.rowId || '' : '';
  } catch {
    return '';
  }
};

const rememberRow = (ledgerId: string, rowId: string) => {
  try {
    if (ledgerId && rowId) sessionStorage.setItem(ROW_KEY, JSON.stringify({ ledgerId, rowId }));
  } catch {
    /* 保存できなくても画面は動く */
  }
};

type LedgerTab = 'list' | 'records' | 'card' | 'fields' | 'export' | 'access' | 'api';

const Shell = ({
  tab,
  ledgerId,
  rowId,
  children,
}: {
  tab: LedgerTab;
  ledgerId?: string;
  rowId?: string;
  children: ReactNode;
}) => {
  const navigate = useNavigate();
  const { documentTitle, howToUse } = useRegisteredAppMeta(
    COMMON_EXAPPS_TEAM_ID,
    LEDGER_EXAPP_ID,
    '台帳',
    '作成文書や手続受付などあらゆる情報を管理できる汎用台帳です。管理項目は台帳ごとに自由に設定できます。',
  );
  const [helpOpen, setHelpOpen] = useState(false);
  const openId = ledgerId || rememberedLedger();

  useEffect(() => {
    if (ledgerId) rememberLedger(ledgerId);
  }, [ledgerId]);

  const openTab = (next: LedgerTab) => {
    if (next === 'list') {
      navigate('/ledger');
      return;
    }
    if (!openId) {
      navigate('/ledger');
      return;
    }
    if (next === 'access') {
      navigate(`/ledger/${openId}/access`);
      return;
    }
    if (next === 'fields') {
      navigate(`/ledger/${openId}/fields`);
      return;
    }
    if (next === 'export') {
      navigate(`/ledger/${openId}/export`);
      return;
    }
    if (next === 'api') {
      navigate(`/ledger/${openId}/api`);
      return;
    }
    if (next === 'card') {
      const cardId = rowId || rememberedRow(openId);
      navigate(cardId ? `/ledger/${openId}/card/${cardId}` : `/ledger/${openId}/card`);
      return;
    }
    navigate(`/ledger/${openId}`);
  };

  const tabClass = (key: LedgerTab) =>
    key === tab
      ? 'whitespace-nowrap border-b-2 border-blue-900 px-3 py-2 text-std-16B-150 text-blue-900'
      : 'whitespace-nowrap px-3 py-2 text-std-16N-170 text-solid-gray-700 hover:text-blue-900';

  return (
    <LayoutBody>
      <PageTitle title={documentTitle || '台帳'} />
      <div className='mx-auto flex h-[calc(100dvh-var(--header-height))] w-full max-w-(--page-width) min-h-0 flex-col gap-3 overflow-hidden p-4 lg:p-6'>
        <ManagedAppHeader
          teamId={COMMON_EXAPPS_TEAM_ID}
          exAppId={LEDGER_EXAPP_ID}
          fallbackTitle='台帳'
          fallbackDescription='作成文書や手続受付などあらゆる情報を管理できる汎用台帳です。管理項目は台帳ごとに自由に設定できます。'
          hideHowTo={true}
        />
        <div className='flex shrink-0 flex-wrap items-center justify-between gap-2'>
          <div className='flex flex-wrap gap-1 overflow-x-auto border-b border-solid-gray-300'>
            <button type='button' className={tabClass('list')} onClick={() => openTab('list')}>
              台帳選択
            </button>
            <button
              type='button'
              className={tabClass('records')}
              onClick={() => openTab('records')}
            >
              レコード
            </button>
            <button type='button' className={tabClass('card')} onClick={() => openTab('card')}>
              カード
            </button>
            <button type='button' className={tabClass('fields')} onClick={() => openTab('fields')}>
              定義項目
            </button>
            <button type='button' className={tabClass('export')} onClick={() => openTab('export')}>
              書き出し
            </button>
            <button type='button' className={tabClass('access')} onClick={() => openTab('access')}>
              アクセス権設定
            </button>
            <button type='button' className={tabClass('api')} onClick={() => openTab('api')}>
              API
            </button>
          </div>
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
        </div>
        <div
          className={
            tab === 'records' || tab === 'card'
              ? 'flex min-h-0 flex-1 flex-col gap-3 overflow-hidden'
              : 'min-h-0 flex-1 overflow-auto'
          }
        >
          {children}
        </div>
      </div>
      <CustomDialog isOpen={helpOpen} onClose={() => setHelpOpen(false)}>
        <CustomDialogPanel className='max-w-2xl'>
          <CustomDialogHeader hasClose onClose={() => setHelpOpen(false)}>
            使い方
          </CustomDialogHeader>
          <CustomDialogBody>
            {howToUse ? <ExAppUsageMarkdownRenderer content={howToUse} size='sm' /> : null}
            <div className='flex flex-col gap-2 text-std-16N-170 text-solid-gray-700'>
              <p>台帳のオーナーは、作った人が所属するチームです。個人の台帳はありません。</p>
              <p>
                「レコード」は表で項目を直接編集します。「カード」は同じ項目を、左の列から順に2列で開きます。入りきらない分は次の頁にします。
              </p>
              <p>
                「定義項目」で、初期項目の表示と、この台帳の設定項目を管理します。資料を読み込むと、モデルが管理項目の案を出します。カードの追加項目は、そのレコードだけの文字です。
              </p>
              <p>
                「書き出し」で条件を決め、JSON、JSONL、CSV
                を書き出します。同じ画面で、その形式のレコードを読み込めます。
              </p>
              <p>「アクセス権設定」で、オーナー、読み書き、読み取りだけのチームを選びます。</p>
              <p>「API」に、この台帳の読み書きとファイルの呼び出し方を書いてあります。</p>
            </div>
          </CustomDialogBody>
        </CustomDialogPanel>
      </CustomDialog>
    </LayoutBody>
  );
};

const formatWhen = (value?: string) => {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('ja-JP');
};

const versionWhen = (file: LedgerFile) => {
  const saved = formatWhen(file.saved_at);
  const until = file.role === 'former' ? formatWhen(file.replaced_at) : '';
  if (saved && until) return `${saved} に保存、${until} まで`;
  if (saved) return `${saved} に保存`;
  if (until) return `${until} まで`;
  return '';
};

const Unavailable = () => (
  <p className='mt-4 text-std-16N-170'>
    台帳は止まっています。有効化するには <code>docker compose --profile ledger up -d</code>{' '}
    を実行してください。
  </p>
);

export const LedgerHomePage = () => {
  const { config, isLoading, unavailable } = useLedgerConfig();
  const ready = !isLoading && !unavailable && config?.enabled !== false;
  const { data, mutate } = useLedgers(ready);
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const [selectedId, setSelectedId] = useState(rememberedLedger);
  const [listNames, setListNames] = useState<Record<string, string>>({});
  const navigate = useNavigate();
  const ledgers = data?.ledgers || [];
  const myTeams = config?.team_ids || [];

  const choose = (id: string) => {
    setSelectedId(id);
    rememberLedger(id);
  };

  const create = async () => {
    const title = name.trim();
    if (!title) return;
    setError('');
    if (myTeams.length === 0) {
      setError('所属するチームがないため台帳を作れません');
      return;
    }
    try {
      const saved = await saveLedger({
        name: title,
        statuses: ['受付', '処理中', '完了'],
        grants: myTeams.map((teamId) => ({ team_id: teamId, role: 'admin' })),
      });
      setName('');
      choose(saved.id);
      await mutate();
    } catch (e) {
      setError(ledgerError(e, '台帳を作れませんでした'));
    }
  };

  const rename = async (ledgerId: string, current: string) => {
    const next = (listNames[ledgerId] ?? current).trim();
    if (!next || next === current) return;
    setError('');
    try {
      await patchLedger(ledgerId, { name: next });
      await mutate();
    } catch (e) {
      setError(ledgerError(e, '名前を保存できませんでした'));
    }
  };

  const remove = async (ledgerId: string, ledgerName: string) => {
    if (!window.confirm(`「${ledgerName}」を一覧から外します。行と履歴は残ります。`)) return;
    setError('');
    try {
      await deleteLedger(ledgerId);
      if (selectedId === ledgerId) choose('');
      await mutate();
    } catch (e) {
      setError(ledgerError(e, '台帳を削除できませんでした'));
    }
  };

  return (
    <Shell tab='list' ledgerId={selectedId}>
      {unavailable || config?.enabled === false ? <Unavailable /> : null}
      {ready && !config?.has_tenant ? (
        <p className='text-std-16N-170'>棟に入ってから台帳を作れます。</p>
      ) : null}
      {ready && (
        <section className='flex flex-col gap-3'>
          <div className='flex flex-wrap items-end justify-between gap-2'>
            <h2 className='text-std-18B-160 text-solid-gray-900'>台帳一覧</h2>
            <div className='flex items-end gap-2'>
              <label className='flex flex-col gap-1 text-dns-14N-130 text-solid-gray-700'>
                新規台帳名
                <Input
                  id='ledger-new-name'
                  blockSize='sm'
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder='備品台帳'
                  className='w-64'
                />
              </label>
              <Button
                type='button'
                variant='solid-fill'
                size='sm'
                aria-disabled={!name.trim() || undefined}
                onClick={() => {
                  if (!name.trim()) return;
                  void create();
                }}
              >
                <span className='inline-flex items-center gap-1 whitespace-nowrap'>
                  <PiFilePlus className='size-4' aria-hidden={true} />
                  作成
                </span>
              </Button>
            </div>
          </div>
          {error ? (
            <p className='text-red-700' role='alert'>
              {error}
            </p>
          ) : null}
          <div className='overflow-x-auto rounded-8 border border-solid-gray-300'>
            <table className='w-full min-w-[56rem] border-collapse text-dns-14N-130'>
              <thead>
                <tr className='border-b border-solid-gray-300 bg-solid-gray-50 text-left text-solid-gray-600'>
                  <th className='w-3/5 min-w-[32rem] px-3 py-2'>台帳名</th>
                  <th className='px-3 py-2'>作成日時</th>
                  <th className='px-3 py-2'>行</th>
                  <th className='px-3 py-2 text-right'>操作</th>
                </tr>
              </thead>
              <tbody>
                {ledgers.length === 0 ? (
                  <tr>
                    <td colSpan={4} className='px-3 py-6 text-center text-solid-gray-500'>
                      台帳がありません。右上から新規作成してください。
                    </td>
                  </tr>
                ) : (
                  ledgers.map((ledger) => {
                    const selected = ledger.id === selectedId;
                    return (
                      <tr
                        key={ledger.id}
                        className='border-b border-solid-gray-200 last:border-b-0'
                        onClick={() => choose(ledger.id)}
                      >
                        <td className='w-3/5 min-w-[32rem] px-3 py-2'>
                          <div className='flex items-center gap-2'>
                            <Input
                              id={`ledger-name-${ledger.id}`}
                              blockSize='sm'
                              className='w-full min-w-0'
                              aria-label='台帳名'
                              readOnly={ledger.role !== 'admin'}
                              value={listNames[ledger.id] ?? ledger.name}
                              onChange={(e) =>
                                setListNames((prev) => ({ ...prev, [ledger.id]: e.target.value }))
                              }
                              onBlur={() => void rename(ledger.id, ledger.name)}
                            />
                            {selected ? (
                              <span className='shrink-0 rounded-full bg-blue-100 px-2 py-0.5 text-dns-14N-130 text-blue-900'>
                                選択中
                              </span>
                            ) : null}
                          </div>
                        </td>
                        <td className='px-3 py-2 text-solid-gray-600'>
                          {formatWhen(ledger.created_at)}
                        </td>
                        <td className='px-3 py-2 text-solid-gray-700'>{ledger.row_count ?? 0}</td>
                        <td className='px-3 py-2 text-right'>
                          <span className='inline-flex gap-2'>
                            <Button
                              type='button'
                              variant='outline'
                              size='sm'
                              onClick={(event) => {
                                event.stopPropagation();
                                choose(ledger.id);
                                navigate(`/ledger/${ledger.id}`);
                              }}
                            >
                              開く
                            </Button>
                            {ledger.role === 'admin' ? (
                              <Button
                                variant='outline'
                                size='sm'
                                type='button'
                                onClick={(event) => {
                                  event.stopPropagation();
                                  void remove(ledger.id, listNames[ledger.id] || ledger.name);
                                }}
                              >
                                削除
                              </Button>
                            ) : null}
                          </span>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </Shell>
  );
};

const SYSTEM_FIELD_DEFS: { key: string; label: string }[] = [
  { key: 'business_key', label: '業務キー' },
  { key: 'status', label: '状態' },
  { key: 'assignee', label: '担当' },
  { key: 'registered_at', label: 'データ登録日時' },
  { key: 'comment', label: 'コメント' },
];

const systemDraft = (items?: LedgerSystemField[]) =>
  SYSTEM_FIELD_DEFS.map((field) => ({
    key: field.key,
    label: field.label,
    visible: items?.find((item) => item.key === field.key)?.visible !== false,
  }));

const systemShown = (items: LedgerSystemField[] | undefined, key: string) =>
  items?.find((item) => item.key === key)?.visible !== false;

const COLUMN_KIND = {
  system: '初期項目',
  defined: '設定項目',
  extra: '追加項目',
} as const;

const ORIGIN_LABEL = { imported: '取込', inferred: '推測', entered: '入力' } as const;

const OriginMark = ({ origin }: { origin?: string }) => {
  if (origin !== 'imported' && origin !== 'inferred') return null;
  return (
    <span
      className='inline-flex size-3 shrink-0 items-center justify-center'
      title={ORIGIN_LABEL[origin]}
      aria-label={ORIGIN_LABEL[origin]}
    >
      {origin === 'imported' ? <span className='size-2 border border-blue-900' /> : null}
      {origin === 'inferred' ? (
        <span className='size-1.5 rotate-45 border border-solid-gray-700' />
      ) : null}
    </span>
  );
};

const findFieldFile = (files: LedgerFile[] | undefined, fieldId: string, value: string) =>
  (files || []).find(
    (file) => file.field_id === fieldId || file.file_id === value || (value && file.name === value),
  ) || null;

const sourceFiles = (files: LedgerFile[] | undefined) =>
  (files || []).filter((file) => !file.field_id && file.role !== 'body' && file.role !== 'former');

const isOfficeName = (name: string) => /\.(docx?|xlsx?|pptx?)$/i.test(name);

const canOpenOffice = (name: string) => {
  const ext = name.split('.').pop()?.toLowerCase() || '';
  return officePathForFormat(ext) !== null;
};

const officeTarget = (files: LedgerFile[] | undefined) => {
  const list = files || [];
  const body = list.find((file) => file.role === 'body' && canOpenOffice(file.name));
  if (body) return { file: body, bound: true };
  const other = list.find((file) => file.role !== 'former' && canOpenOffice(file.name));
  if (other) return { file: other, bound: false };
  return null;
};

const officeHref = (rowId: string, file: LedgerFile, bound: boolean) => {
  const ext = file.name.split('.').pop()?.toLowerCase() || '';
  const path = officePathForFormat(ext);
  if (!path) return '';
  const query = new URLSearchParams({ local: '1', row: rowId, file: file.file_id });
  if (bound) query.set('bound', '1');
  return `${path}?${query.toString()}`;
};

type OfficePreview = {
  kind: 'sheets' | 'text' | 'slides';
  note?: string;
  text?: string;
  sheets?: { name: string; rows: string[][] }[];
  slides?: { title: string; lines: string[] }[];
};

const previewKind = (file: LedgerFile, blob: Blob) => {
  const mime = blob.type || file.mime || '';
  const name = file.name.toLowerCase();
  if (mime.startsWith('image/') || /\.(png|jpe?g|gif|webp)$/.test(name)) return 'image' as const;
  if (mime === 'application/pdf' || name.endsWith('.pdf')) return 'pdf' as const;
  if (mime.startsWith('text/') || /\.(txt|csv|md|json|jsonl)$/.test(name)) return 'text' as const;
  return 'other' as const;
};

const FilePreviewDialog = ({
  rowId,
  file,
  onClose,
}: {
  rowId: string;
  file: LedgerFile | null;
  onClose: () => void;
}) => {
  const [url, setUrl] = useState('');
  const [text, setText] = useState('');
  const [office, setOffice] = useState<OfficePreview | null>(null);
  const [kind, setKind] = useState<'image' | 'pdf' | 'text' | 'office' | 'other' | ''>('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const blobRef = useRef<Blob | null>(null);

  useEffect(() => {
    if (!file) return;
    let cancelled = false;
    let objectUrl = '';
    setBusy(true);
    setError('');
    setText('');
    setOffice(null);
    setKind('');
    setUrl('');
    blobRef.current = null;
    void (async () => {
      try {
        if (isOfficeName(file.name)) {
          const [preview, res] = await Promise.all([
            teamApi.get<OfficePreview>(`ledger/rows/${rowId}/files/${file.file_id}/preview`),
            teamApi.getBlob(`ledger/rows/${rowId}/files/${file.file_id}`),
          ]);
          if (cancelled) return;
          blobRef.current = res.blob;
          setOffice(preview.data);
          setKind('office');
          return;
        }
        const res = await teamApi.getBlob(`ledger/rows/${rowId}/files/${file.file_id}`);
        if (cancelled) return;
        blobRef.current = res.blob;
        const next = previewKind(file, res.blob);
        setKind(next);
        if (next === 'text') {
          setText(await res.blob.text());
        } else if (next === 'image' || next === 'pdf') {
          objectUrl = URL.createObjectURL(res.blob);
          setUrl(objectUrl);
        }
      } catch (e) {
        if (!cancelled) setError(ledgerError(e, 'ファイルを表示できませんでした'));
      } finally {
        if (!cancelled) setBusy(false);
      }
    })();
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [file, rowId]);

  const download = () => {
    const blob = blobRef.current;
    if (!blob || !file) return;
    const objectUrl = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = objectUrl;
    anchor.download = file.name || 'file';
    anchor.click();
    URL.revokeObjectURL(objectUrl);
  };

  return (
    <CustomDialog isOpen={!!file} onClose={onClose}>
      <CustomDialogPanel className='max-w-4xl'>
        <CustomDialogHeader hasClose onClose={onClose}>
          {file?.name || 'ファイル'}
        </CustomDialogHeader>
        <CustomDialogBody>
          <div className='flex flex-col gap-3'>
            {busy ? <p className='text-std-16N-170 text-solid-gray-700'>表示しています。</p> : null}
            {error ? (
              <p className='text-red-700' role='alert'>
                {error}
              </p>
            ) : null}
            {kind === 'pdf' && url ? (
              <iframe
                title={file?.name || 'PDF'}
                src={url}
                className='h-[70vh] w-full rounded-8 border border-solid-gray-300 bg-white'
              />
            ) : null}
            {kind === 'image' && url ? (
              <img
                alt={file?.name || ''}
                src={url}
                className='max-h-[70vh] w-full object-contain'
              />
            ) : null}
            {kind === 'text' ? (
              <pre className='max-h-[70vh] overflow-auto whitespace-pre-wrap rounded-8 border border-solid-gray-300 bg-white p-3 text-std-16N-170 text-solid-gray-900'>
                {text}
              </pre>
            ) : null}
            {kind === 'office' && office?.kind === 'text' ? (
              <pre className='max-h-[70vh] overflow-auto whitespace-pre-wrap rounded-8 border border-solid-gray-300 bg-white p-3 text-std-16N-170 text-solid-gray-900'>
                {office.text}
              </pre>
            ) : null}
            {kind === 'office' && office?.kind === 'sheets'
              ? office.sheets?.map((sheet) => (
                  <div
                    key={sheet.name}
                    className='max-h-[70vh] overflow-auto rounded-8 border border-solid-gray-300'
                  >
                    <p className='sticky top-0 bg-solid-gray-50 px-3 py-2 text-std-16B-150 text-solid-gray-900'>
                      {sheet.name}
                    </p>
                    <table className='w-full border-collapse text-dns-14N-130'>
                      <tbody>
                        {sheet.rows.map((row, index) => (
                          <tr key={index} className='border-t border-solid-gray-200'>
                            {row.map((cell, cellIndex) => (
                              <td
                                key={cellIndex}
                                className='px-2 py-1 align-top text-solid-gray-900'
                              >
                                {cell}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ))
              : null}
            {kind === 'office' && office?.kind === 'slides'
              ? office.slides?.map((slide, index) => (
                  <section
                    key={`${slide.title}-${index}`}
                    className='rounded-8 border border-solid-gray-300 p-3'
                  >
                    <h3 className='text-std-16B-150 text-solid-gray-900'>{slide.title}</h3>
                    {slide.lines.map((line) => (
                      <p
                        key={line}
                        className='mt-1 whitespace-pre-wrap text-std-16N-170 text-solid-gray-900'
                      >
                        {line}
                      </p>
                    ))}
                  </section>
                ))
              : null}
            {kind === 'office' && office?.note ? (
              <p className='text-dns-14N-130 text-solid-gray-600'>{office.note}</p>
            ) : null}
            {kind === 'other' ? (
              <p className='text-std-16N-170 text-solid-gray-700'>
                この形式は画面では表示できません。ダウンロードして確認してください。
              </p>
            ) : null}
            <div className='flex justify-end gap-2'>
              <Button variant='outline' size='sm' type='button' onClick={onClose}>
                閉じる
              </Button>
              <Button
                variant='solid-fill'
                size='sm'
                type='button'
                aria-disabled={!blobRef.current || busy}
                onClick={download}
              >
                ダウンロード
              </Button>
            </div>
          </div>
        </CustomDialogBody>
      </CustomDialogPanel>
    </CustomDialog>
  );
};

const KindMark = ({ kind }: { kind: keyof typeof COLUMN_KIND }) => (
  <span
    className='inline-flex size-3 shrink-0 items-center justify-center'
    title={COLUMN_KIND[kind]}
    aria-hidden={true}
  >
    {kind === 'defined' ? <span className='size-2 rounded-[2px] bg-blue-900' /> : null}
    {kind === 'extra' ? <span className='size-1.5 rotate-45 border border-solid-gray-600' /> : null}
    {kind === 'system' ? (
      <span className='size-2 rounded-full border border-solid-gray-500' />
    ) : null}
  </span>
);

const FIELD_TYPE_LABEL: Record<LedgerField['type'], string> = {
  text: '文字',
  number: '数値',
  date: '日付',
  select: '選択',
  longtext: '長文',
  file: 'ファイル',
};

type DraftField = {
  key: string;
  id: string;
  label: string;
  type: LedgerField['type'];
  masked: boolean;
  optionsText: string;
  promote: boolean;
};

const splitOptions = (text: string) =>
  text
    .split(/[、,\n]/)
    .map((item) => item.trim())
    .filter((item, index, all) => item && all.indexOf(item) === index);

const readWidths = (ledgerId: string) => {
  try {
    const parsed = JSON.parse(
      sessionStorage.getItem(`open-genai-ledger-widths:${ledgerId}`) || '{}',
    ) as Record<string, number>;
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
};

const writeWidths = (ledgerId: string, widths: Record<string, number>) => {
  try {
    sessionStorage.setItem(`open-genai-ledger-widths:${ledgerId}`, JSON.stringify(widths));
  } catch {
    /* 保存できなくても画面は動く */
  }
};

const defaultColumnWidth = (key: string, wide?: boolean) => {
  if (key === 'business_key') return 220;
  if (key === 'registered_at') return 200;
  if (key === 'status') return 132;
  if (key === 'comment' || wide) return 240;
  return 168;
};

const toDraft = (field: LedgerField, promote = false): DraftField => ({
  key: field.id || `new-${field.label}`,
  id: field.id || '',
  label: field.label,
  type: field.type,
  masked: !!field.masked,
  optionsText: (field.options || []).join('、'),
  promote,
});

export const LedgerRowsPage = () => {
  const { ledgerId = '' } = useParams();
  const navigate = useNavigate();
  const { data: ledger } = useLedger(ledgerId);
  const [status, setStatus] = useState('');
  const [q, setQ] = useState('');
  const [showDeleted, setShowDeleted] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [ingestOpen, setIngestOpen] = useState(false);
  const [ingestFiles, setIngestFiles] = useState<File[]>([]);
  const [ingestBusy, setIngestBusy] = useState(false);
  const [ingestError, setIngestError] = useState('');
  const [ingestBatch, setIngestBatch] = useState('');
  const [ingestRows, setIngestRows] = useState<
    {
      index: number;
      values: { id: string; label: string; value: string; origin: string; file_name: string }[];
    }[]
  >([]);
  const [ingestPicked, setIngestPicked] = useState<Record<number, boolean>>({});
  const ingestFileRef = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<{ rowId: string; file: LedgerFile } | null>(null);
  const [draftNatural, setDraftNatural] = useState('');
  const [draftStatus, setDraftStatus] = useState('');
  const [draftQ, setDraftQ] = useState('');
  const [draftDeleted, setDraftDeleted] = useState(false);
  const [widths, setWidths] = useState<Record<string, number>>(() => readWidths(ledgerId));
  const query = new URLSearchParams({
    status,
    q,
    include_deleted: showDeleted ? '1' : '0',
  }).toString();
  const { data, mutate } = useLedgerRows(ledgerId, query);
  const [error, setError] = useState('');
  const [selectedRowId, setSelectedRowId] = useState(() => rememberedRow(ledgerId));

  useEffect(() => {
    setSelectedRowId(rememberedRow(ledgerId));
    setWidths(readWidths(ledgerId));
  }, [ledgerId]);

  const chooseRow = (id: string) => {
    setSelectedRowId(id);
    rememberRow(ledgerId, id);
  };

  const openCard = (id: string) => {
    chooseRow(id);
    navigate(`/ledger/${ledgerId}/card/${id}`);
  };

  const openSearch = () => {
    setDraftNatural('');
    setDraftStatus(status);
    setDraftQ(q);
    setDraftDeleted(showDeleted);
    setSearchOpen(true);
  };

  const applySearch = async () => {
    setError('');
    try {
      if (draftNatural.trim()) {
        const res = await teamApi.post<{ filter: { status?: string; q?: string } }>(
          `ledger/ledgers/${ledgerId}/assist/query`,
          { text: draftNatural },
        );
        setStatus(res.data.filter.status || '');
        setQ(res.data.filter.q || '');
      } else {
        setStatus(draftStatus);
        setQ(draftQ.trim());
      }
      setShowDeleted(draftDeleted);
      setSearchOpen(false);
    } catch (e) {
      setError(ledgerError(e, '検索できませんでした'));
    }
  };

  const clearSearch = () => {
    setStatus('');
    setQ('');
    setShowDeleted(false);
  };

  const createRow = async () => {
    try {
      const row = await saveRow(ledgerId, { status: ledger?.statuses[0] || '' });
      openCard(row.id);
    } catch (e) {
      setError(ledgerError(e, 'レコードを作れませんでした'));
    }
  };

  const duplicateRow = async (row: LedgerRow) => {
    setError('');
    try {
      const created = await saveRow(ledgerId, {
        status: row.status,
        assignee: row.assignee,
        comment: row.comment,
        fields: row.fields,
        origins: row.origins,
        extras: row.extras,
      });
      chooseRow(created.id);
      await mutate();
    } catch (e) {
      setError(ledgerError(e, '複製できませんでした'));
    }
  };

  const removeRow = async (row: LedgerRow) => {
    if (!window.confirm('このレコードを一覧から外します。履歴は残ります。')) return;
    setError('');
    try {
      await teamApi.post(`ledger/rows/${row.id}/delete`);
      await mutate();
    } catch (e) {
      setError(ledgerError(e, '削除できませんでした'));
    }
  };

  const restoreRow = async (row: LedgerRow) => {
    setError('');
    try {
      await teamApi.post(`ledger/rows/${row.id}/restore`);
      await mutate();
    } catch (e) {
      setError(ledgerError(e, '戻せませんでした'));
    }
  };

  const [cellDrafts, setCellDrafts] = useState<Record<string, string>>({});
  const latestRows = useRef(new Map<string, LedgerRow>());
  const saveChains = useRef(new Map<string, Promise<void>>());

  useEffect(() => {
    for (const row of data?.rows || []) {
      const prev = latestRows.current.get(row.id);
      if (!prev || (row.updated_at || '') >= (prev.updated_at || '')) {
        latestRows.current.set(row.id, row);
      }
    }
  }, [data]);

  const commitCell = async (
    rowId: string,
    apply: (row: LedgerRow) => Record<string, unknown> | null,
  ) => {
    const prev = saveChains.current.get(rowId) ?? Promise.resolve();
    const job = prev
      .catch(() => undefined)
      .then(async () => {
        const row = latestRows.current.get(rowId);
        if (!row) return;
        const body = apply(row);
        if (!body) return;
        const saved = await updateRow(rowId, body);
        latestRows.current.set(rowId, { ...row, ...saved });
        await mutate(
          (current) =>
            current
              ? {
                  rows: current.rows.map((item) =>
                    item.id === saved.id ? { ...item, ...saved } : item,
                  ),
                }
              : current,
          { revalidate: false },
        );
      });
    saveChains.current.set(rowId, job);
    return job;
  };

  const readIngest = async () => {
    if (!ingestFiles.length) {
      setIngestError('資料を1つ以上選んでください');
      return;
    }
    setIngestError('');
    setIngestBusy(true);
    try {
      const files = await Promise.all(
        ingestFiles.map(async (file) => ({
          name: file.name,
          media_type: file.type,
          data: await new Promise<string>((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => {
              const result = String(reader.result || '');
              const comma = result.indexOf(',');
              resolve(comma >= 0 ? result.slice(comma + 1) : result);
            };
            reader.onerror = () => reject(reader.error);
            reader.readAsDataURL(file);
          }),
        })),
      );
      const res = await teamApi.post<{
        batch_id: string;
        rows: {
          index: number;
          values: { id: string; label: string; value: string; origin: string; file_name: string }[];
        }[];
      }>(`ledger/ledgers/${ledgerId}/ingest`, { files });
      setIngestBatch(res.data.batch_id);
      setIngestRows(res.data.rows || []);
      setIngestPicked(Object.fromEntries((res.data.rows || []).map((row) => [row.index, true])));
    } catch (e) {
      setIngestError(ledgerError(e, '資料から値を読めませんでした'));
    } finally {
      setIngestBusy(false);
    }
  };

  const commitIngest = async () => {
    const indexes = ingestRows.filter((row) => ingestPicked[row.index]).map((row) => row.index);
    if (!indexes.length) {
      setIngestError('登録する行を選んでください');
      return;
    }
    setIngestError('');
    setIngestBusy(true);
    try {
      await teamApi.post(`ledger/ledgers/${ledgerId}/ingest/${ingestBatch}`, { indexes });
      setIngestOpen(false);
      await mutate();
    } catch (e) {
      setIngestError(ledgerError(e, '登録できませんでした'));
      await mutate();
    } finally {
      setIngestBusy(false);
    }
  };

  const filterLabel = [status, q, showDeleted ? '削除を含む' : ''].filter(Boolean).join(' / ');
  const rows = data?.rows || [];
  const extraLabels: string[] = [];
  const seenExtras = new Set<string>();
  for (const row of rows) {
    for (const extra of row.extras || []) {
      const label = extra.label.trim();
      if (!label || seenExtras.has(label)) continue;
      seenExtras.add(label);
      extraLabels.push(label);
    }
  }
  const showSystem = (key: string) => systemShown(ledger?.system, key);
  const sheetColumns = [
    ...(ledger?.source_key === 'office'
      ? [{ key: 'file_name', label: 'ファイル名', wide: true, kind: 'system' as const }]
      : []),
    ...(showSystem('business_key')
      ? [{ key: 'business_key', label: '業務キー', wide: false, kind: 'system' as const }]
      : []),
    ...(showSystem('status')
      ? [{ key: 'status', label: '状態', wide: false, kind: 'system' as const }]
      : []),
    ...(showSystem('assignee')
      ? [{ key: 'assignee', label: '担当', wide: false, kind: 'system' as const }]
      : []),
    ...(showSystem('registered_at')
      ? [{ key: 'registered_at', label: 'データ登録日時', wide: false, kind: 'system' as const }]
      : []),
    ...(ledger?.fields || []).map((field) => ({
      key: `field:${field.id}`,
      label: field.label,
      wide: field.type === 'longtext',
      kind: 'defined' as const,
      field,
    })),
    ...extraLabels.map((label) => ({
      key: `extra:${label}`,
      label,
      wide: false,
      kind: 'extra' as const,
    })),
    ...(showSystem('comment')
      ? [{ key: 'comment', label: 'コメント', wide: true, kind: 'system' as const }]
      : []),
  ];
  const actionWidth = 168;
  const columnCount = sheetColumns.length + 2;
  const columnWidth = (key: string, wide?: boolean) => widths[key] ?? defaultColumnWidth(key, wide);
  const tableWidth = sheetColumns.reduce(
    (sum, column) => sum + columnWidth(column.key, column.wide),
    actionWidth,
  );
  const resizeColumn = (
    key: string,
    wide: boolean | undefined,
    event: ReactPointerEvent<HTMLSpanElement>,
  ) => {
    event.preventDefault();
    event.stopPropagation();
    const startX = event.clientX;
    const start = columnWidth(key, wide);
    const target = event.currentTarget;
    target.setPointerCapture(event.pointerId);
    const move = (ev: globalThis.PointerEvent) => {
      const next = Math.max(96, Math.round(start + ev.clientX - startX));
      setWidths((current) => {
        const saved = { ...current, [key]: next };
        writeWidths(ledgerId, saved);
        return saved;
      });
    };
    const stop = () => {
      target.removeEventListener('pointermove', move);
      target.removeEventListener('pointerup', stop);
    };
    target.addEventListener('pointermove', move);
    target.addEventListener('pointerup', stop);
  };

  const sourceValue = (row: LedgerRow, key: string) => {
    if (key === 'file_name')
      return (row.files || []).find((file) => file.role === 'body')?.name || '';
    if (key === 'business_key')
      return row.deleted_at ? `${row.business_key}（削除）` : row.business_key;
    if (key === 'status') return row.status;
    if (key === 'assignee') return row.assignee;
    if (key === 'registered_at') return formatWhen(row.created_at);
    if (key === 'comment') return row.comment;
    if (key.startsWith('field:')) return row.fields[key.slice(6)] || '';
    if (key.startsWith('extra:')) {
      const label = key.slice(6);
      return row.extras.find((item) => item.label === label)?.value || '';
    }
    return '';
  };

  const shownValue = (row: LedgerRow, key: string) =>
    cellDrafts[`${row.id}:${key}`] ?? sourceValue(row, key);

  const writeCell = (row: LedgerRow, key: string, value: string) => {
    const draftKey = `${row.id}:${key}`;
    setCellDrafts((current) => ({ ...current, [draftKey]: value }));
    const editable = (ledger?.role === 'admin' || ledger?.role === 'editor') && !row.deleted_at;
    if (!editable || key === 'business_key' || key === 'registered_at') return;
    const field = key.startsWith('field:')
      ? ledger?.fields.find((item) => item.id === key.slice(6))
      : undefined;
    if (field?.type === 'file') return;
    const commit = key === 'status' || field?.type === 'select';
    if (!commit) return;
    void flushCell(row, key, value);
  };

  const flushCell = async (row: LedgerRow, key: string, value: string) => {
    const draftKey = `${row.id}:${key}`;
    const editable = (ledger?.role === 'admin' || ledger?.role === 'editor') && !row.deleted_at;
    if (!editable || key === 'business_key') return;
    try {
      await commitCell(row.id, (current) => {
        if (key === 'status') return value === current.status ? null : { status: value };
        if (key === 'assignee') return value === current.assignee ? null : { assignee: value };
        if (key === 'comment') return value === current.comment ? null : { comment: value };
        if (key.startsWith('field:')) {
          const id = key.slice(6);
          if ((current.fields[id] || '') === value) return null;
          return { fields: { [id]: value }, origins: { [id]: { origin: 'entered' } } };
        }
        if (key.startsWith('extra:')) {
          const label = key.slice(6);
          const next = current.extras.filter((item) => item.label !== label);
          if (value.trim()) next.push({ label, value: value.trim() });
          const before = current.extras.find((item) => item.label === label)?.value || '';
          if (before === value.trim()) return null;
          return { extras: next };
        }
        return null;
      });
      setCellDrafts((current) => {
        if (!(draftKey in current)) return current;
        const next = { ...current };
        delete next[draftKey];
        return next;
      });
    } catch (e) {
      setError(ledgerError(e, '保存できませんでした'));
    }
  };

  return (
    <Shell tab='records' ledgerId={ledgerId}>
      <div className='flex min-h-0 flex-1 flex-col gap-3'>
        <div className='flex shrink-0 flex-wrap items-end justify-between gap-2'>
          <div>
            <h2 className='text-std-18B-160 text-solid-gray-900'>{ledger?.name || '台帳'}</h2>
            {ledger?.source_key === 'office' ? (
              <p className='text-dns-14N-130 text-solid-gray-600'>
                オフィスで保存した文書です。開くと続きを編集でき、保存は同じ行の本体を差し替えます。
              </p>
            ) : null}
          </div>
          <div className='flex flex-wrap gap-2'>
            <Button variant='solid-fill' size='sm' type='button' onClick={() => void createRow()}>
              レコードを追加
            </Button>
            {ledger?.role === 'admin' || ledger?.role === 'editor' ? (
              <Button
                variant='outline'
                size='sm'
                type='button'
                onClick={() => {
                  setIngestFiles([]);
                  setIngestError('');
                  setIngestBatch('');
                  setIngestRows([]);
                  setIngestPicked({});
                  setIngestOpen(true);
                }}
              >
                資料から登録
              </Button>
            ) : null}
            <Button variant='outline' size='sm' type='button' onClick={openSearch}>
              検索
            </Button>
          </div>
        </div>
        {filterLabel ? (
          <div className='flex shrink-0 flex-wrap items-center gap-2 text-dns-14N-130 text-solid-gray-700'>
            <span>検索中: {filterLabel}</span>
            <Button variant='outline' size='sm' type='button' onClick={clearSearch}>
              条件をクリア
            </Button>
          </div>
        ) : null}
        {error && !searchOpen ? (
          <p className='shrink-0 text-red-700' role='alert'>
            {error}
          </p>
        ) : null}
        <p className='flex shrink-0 flex-wrap items-center gap-x-4 gap-y-1 text-dns-14N-130 text-solid-gray-600'>
          {(Object.keys(COLUMN_KIND) as (keyof typeof COLUMN_KIND)[]).map((kind) => (
            <span key={kind} className='inline-flex items-center gap-1.5'>
              <KindMark kind={kind} />
              {COLUMN_KIND[kind]}
            </span>
          ))}
          <span className='inline-flex items-center gap-1.5'>
            <OriginMark origin='imported' />
            取込
          </span>
          <span className='inline-flex items-center gap-1.5'>
            <OriginMark origin='inferred' />
            推測
          </span>
          <span>印の無い値は入力</span>
        </p>
        <div className='min-h-0 flex-1 overflow-auto rounded-8 border border-solid-gray-300'>
          <table
            className='table-fixed border-collapse text-dns-14N-130'
            style={{ width: '100%', minWidth: tableWidth }}
          >
            <colgroup>
              {sheetColumns.map((column) => (
                <col key={column.key} style={{ width: columnWidth(column.key, column.wide) }} />
              ))}
              <col />
              <col style={{ width: actionWidth }} />
            </colgroup>
            <thead className='sticky top-0 z-20'>
              <tr className='border-b border-solid-gray-300 bg-solid-gray-50 text-left text-solid-gray-600'>
                {sheetColumns.map((column) => (
                  <th
                    key={column.key}
                    className={
                      column.key === 'business_key' || column.key === 'file_name'
                        ? 'sticky left-0 z-30 bg-solid-gray-50 px-3 py-2'
                        : 'relative bg-solid-gray-50 px-3 py-2'
                    }
                    style={{ width: columnWidth(column.key, column.wide) }}
                  >
                    <span className='flex items-center gap-1.5 pr-2'>
                      <KindMark kind={column.kind} />
                      <span className='truncate'>{column.label}</span>
                    </span>
                    <span
                      role='separator'
                      aria-orientation='vertical'
                      aria-label={`${column.label}の幅`}
                      className='absolute top-0 right-0 z-40 h-full w-2 cursor-col-resize touch-none hover:bg-blue-700'
                      onPointerDown={(event) => resizeColumn(column.key, column.wide, event)}
                    />
                  </th>
                ))}
                <th className='bg-solid-gray-50 p-0' aria-hidden={true} />
                <th className='sticky right-0 z-40 bg-solid-gray-50 px-2 py-2 text-left'>操作</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={columnCount} className='px-3 py-6 text-center text-solid-gray-500'>
                    レコードがありません。
                  </td>
                </tr>
              ) : (
                rows.map((row) => {
                  const editable =
                    (ledger?.role === 'admin' || ledger?.role === 'editor') && !row.deleted_at;
                  const selected = row.id === selectedRowId;
                  const stickyBg = selected
                    ? 'bg-blue-50'
                    : 'bg-white group-hover:bg-solid-gray-50';
                  return (
                    <tr
                      key={row.id}
                      className={
                        selected
                          ? 'group border-b border-solid-gray-200 bg-blue-50 last:border-b-0'
                          : 'group border-b border-solid-gray-200 last:border-b-0'
                      }
                      onFocus={() => chooseRow(row.id)}
                    >
                      {sheetColumns.map((column) => {
                        const value = shownValue(row, column.key);
                        const origin = column.key.startsWith('field:')
                          ? row.origins?.[column.key.slice(6)]?.origin
                          : undefined;
                        const field = 'field' in column ? column.field : undefined;
                        const readOnly =
                          !editable ||
                          column.key === 'business_key' ||
                          column.key === 'file_name' ||
                          field?.type === 'file';
                        const cellClass = 'border-r border-solid-gray-200 px-1 py-1 align-top';
                        const inputClass =
                          'w-full rounded-4 border border-transparent bg-transparent px-2 py-1 text-std-16N-170 text-solid-gray-900 hover:border-solid-gray-300 focus:border-blue-900 focus:bg-white focus:outline-none read-only:hover:border-transparent';
                        return (
                          <td
                            key={column.key}
                            className={
                              column.key === 'business_key' || column.key === 'file_name'
                                ? `sticky left-0 z-10 overflow-hidden ${stickyBg} ${cellClass}`
                                : `overflow-hidden ${cellClass}`
                            }
                          >
                            <div className='flex items-start gap-1'>
                              {origin && origin !== 'entered' ? (
                                <span className='mt-2'>
                                  <OriginMark origin={origin} />
                                </span>
                              ) : null}
                              <div className='min-w-0 flex-1'>
                                {column.key === 'registered_at' ? (
                                  <span className='block truncate px-2 py-1 text-std-16N-170 text-solid-gray-900'>
                                    {value}
                                  </span>
                                ) : column.key === 'status' ? (
                                  <select
                                    className={inputClass}
                                    aria-label={`${row.business_key}の状態`}
                                    value={value}
                                    disabled={!editable}
                                    onChange={(event) =>
                                      writeCell(row, column.key, event.target.value)
                                    }
                                  >
                                    {(ledger?.statuses || []).map((item) => (
                                      <option key={item} value={item}>
                                        {item}
                                      </option>
                                    ))}
                                  </select>
                                ) : field?.type === 'select' ? (
                                  <select
                                    className={inputClass}
                                    aria-label={`${row.business_key}の${column.label}`}
                                    value={value}
                                    disabled={!editable}
                                    onChange={(event) =>
                                      writeCell(row, column.key, event.target.value)
                                    }
                                  >
                                    <option value='' />
                                    {(field.options || []).map((option) => (
                                      <option key={option} value={option}>
                                        {option}
                                      </option>
                                    ))}
                                  </select>
                                ) : column.key === 'file_name' ? (
                                  (() => {
                                    const target = officeTarget(row.files);
                                    const href = target
                                      ? officeHref(row.id, target.file, target.bound)
                                      : '';
                                    return href ? (
                                      <button
                                        type='button'
                                        className={`${inputClass} text-left text-blue-900 underline`}
                                        onClick={() => navigate(href)}
                                      >
                                        {target?.file.name}
                                      </button>
                                    ) : (
                                      <span className='block truncate px-2 py-1 text-solid-gray-500'>
                                        ファイルはまだありません
                                      </span>
                                    );
                                  })()
                                ) : field?.type === 'file' ? (
                                  (() => {
                                    const linked = findFieldFile(row.files, field.id, value);
                                    return linked ? (
                                      <button
                                        type='button'
                                        className={`${inputClass} text-left text-blue-900 underline`}
                                        onClick={() => {
                                          const href = officeHref(row.id, linked, linked.role === 'body');
                                          if (href) navigate(href);
                                          else setPreview({ rowId: row.id, file: linked });
                                        }}
                                      >
                                        {linked.name}
                                      </button>
                                    ) : (
                                      <span className='block truncate px-2 py-1 text-solid-gray-500'>
                                        ファイルはまだありません
                                      </span>
                                    );
                                  })()
                                ) : field?.type === 'longtext' || column.key === 'comment' ? (
                                  <textarea
                                    className={`${inputClass} min-h-10 min-w-0`}
                                    aria-label={`${row.business_key}の${column.label}`}
                                    rows={2}
                                    readOnly={readOnly}
                                    value={value}
                                    onChange={(event) =>
                                      writeCell(row, column.key, event.target.value)
                                    }
                                    onBlur={(event) =>
                                      void flushCell(row, column.key, event.target.value)
                                    }
                                  />
                                ) : (
                                  <span className='flex items-center gap-2'>
                                    <input
                                      className={`${inputClass} min-w-0`}
                                      aria-label={`${row.business_key}の${column.label}`}
                                      type={
                                        field?.type === 'date'
                                          ? 'date'
                                          : field?.type === 'number'
                                            ? 'number'
                                            : 'text'
                                      }
                                      readOnly={readOnly}
                                      value={value}
                                      onChange={(event) =>
                                        writeCell(row, column.key, event.target.value)
                                      }
                                      onBlur={(event) =>
                                        void flushCell(row, column.key, event.target.value)
                                      }
                                    />
                                    {column.key === 'business_key' && selected ? (
                                      <span className='shrink-0 rounded-full bg-blue-100 px-2 py-0.5 text-dns-14N-130 text-blue-900'>
                                        選択中
                                      </span>
                                    ) : null}
                                  </span>
                                )}
                              </div>
                            </div>
                          </td>
                        );
                      })}
                      <td className='p-0' />
                      <td className={`sticky right-0 z-20 px-1 py-1 text-right ${stickyBg}`}>
                        <div className='flex items-center justify-end gap-1'>
                          {officeTarget(row.files) ? (
                            <button
                              type='button'
                              className='inline-flex size-8 items-center justify-center rounded-4 border border-solid-gray-300 bg-white text-blue-900 hover:bg-blue-50'
                              aria-label='オフィスで開く'
                              title='オフィスで開く'
                              onClick={() => {
                                const target = officeTarget(row.files);
                                const href = target
                                  ? officeHref(row.id, target.file, target.bound)
                                  : '';
                                if (href) navigate(href);
                              }}
                            >
                              <PiBookOpenBold className='size-4' aria-hidden={true} />
                            </button>
                          ) : null}
                          <button
                            type='button'
                            className='inline-flex size-8 items-center justify-center rounded-4 border border-solid-gray-300 bg-white text-blue-900 hover:bg-blue-50'
                            aria-label='カード'
                            title='カード'
                            onClick={() => openCard(row.id)}
                          >
                            <PiIdentificationCardBold className='size-4' aria-hidden={true} />
                          </button>
                          {ledger?.role === 'admin' || ledger?.role === 'editor' ? (
                            <button
                              type='button'
                              className='inline-flex size-8 items-center justify-center rounded-4 border border-solid-gray-300 bg-white text-solid-gray-800 hover:bg-solid-gray-100 disabled:opacity-30'
                              aria-label='複製'
                              title='複製'
                              disabled={!!row.deleted_at}
                              onClick={() => void duplicateRow(row)}
                            >
                              <PiCopyBold className='size-4' aria-hidden={true} />
                            </button>
                          ) : null}
                          {row.deleted_at && ledger?.role === 'admin' ? (
                            <button
                              type='button'
                              className='inline-flex size-8 items-center justify-center rounded-4 border border-solid-gray-300 bg-white text-solid-gray-800 hover:bg-solid-gray-100'
                              aria-label='戻す'
                              title='戻す'
                              onClick={() => void restoreRow(row)}
                            >
                              <PiArrowCounterClockwiseBold className='size-4' aria-hidden={true} />
                            </button>
                          ) : null}
                          {!row.deleted_at &&
                          (ledger?.role === 'admin' || ledger?.role === 'editor') ? (
                            <button
                              type='button'
                              className='inline-flex size-8 items-center justify-center rounded-4 border border-solid-gray-300 bg-white text-solid-gray-800 hover:bg-solid-gray-100'
                              aria-label='削除'
                              title='削除'
                              onClick={() => void removeRow(row)}
                            >
                              <PiTrashBold className='size-4' aria-hidden={true} />
                            </button>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        <CustomDialog isOpen={ingestOpen} onClose={() => setIngestOpen(false)}>
          <CustomDialogPanel className='max-w-2xl'>
            <CustomDialogHeader hasClose onClose={() => setIngestOpen(false)}>
              {ingestBatch ? '登録する値' : '資料から登録'}
            </CustomDialogHeader>
            <CustomDialogBody>
              {ingestBatch ? (
                <div className='flex flex-col gap-3'>
                  <p className='text-dns-14N-130 text-solid-gray-600'>
                    残す行に印を付けてください。□は資料に書いてあった値、◇は推測した値です。登録すると、出典のファイルをそのレコードに添付します。状態は変えません。
                  </p>
                  <ul className='flex flex-col gap-3'>
                    {ingestRows.map((row) => (
                      <li key={row.index} className='rounded-8 border border-solid-gray-300 p-3'>
                        <label className='flex items-center gap-2 text-std-16B-150'>
                          <input
                            type='checkbox'
                            checked={!!ingestPicked[row.index]}
                            onChange={(e) =>
                              setIngestPicked((current) => ({
                                ...current,
                                [row.index]: e.target.checked,
                              }))
                            }
                          />
                          {row.index + 1}件目
                        </label>
                        <ul className='mt-2 flex flex-col gap-1'>
                          {row.values.map((item) => (
                            <li
                              key={item.id}
                              className='flex flex-wrap items-center gap-2 text-std-16N-170'
                            >
                              <OriginMark origin={item.origin} />
                              <span>
                                {item.label}: {item.value}（
                                {item.origin === 'imported' ? '取込' : '推測'}）
                              </span>
                              {item.file_name ? (
                                <span className='text-dns-14N-130 text-solid-gray-600'>
                                  {item.file_name}
                                </span>
                              ) : null}
                            </li>
                          ))}
                        </ul>
                      </li>
                    ))}
                  </ul>
                  {ingestError ? (
                    <p className='text-red-700' role='alert'>
                      {ingestError}
                    </p>
                  ) : null}
                  <div className='flex justify-end gap-2'>
                    <Button
                      variant='outline'
                      size='sm'
                      type='button'
                      onClick={() => setIngestBatch('')}
                    >
                      戻る
                    </Button>
                    <Button
                      variant='solid-fill'
                      size='sm'
                      type='button'
                      aria-disabled={
                        ingestBusy || !ingestRows.some((row) => ingestPicked[row.index])
                      }
                      onClick={() => void commitIngest()}
                    >
                      {ingestBusy ? '登録しています' : '登録する'}
                    </Button>
                  </div>
                </div>
              ) : (
                <div className='flex flex-col gap-3'>
                  <p className='text-dns-14N-130 text-solid-gray-600'>
                    PDF、Word、Excel、CSV、テキスト、画像を、3つまで選べます。設定項目に入る値だけを案にします。1つの資料に複数の対象があるときは、行を分けて出します。
                  </p>
                  <input
                    ref={ingestFileRef}
                    type='file'
                    multiple
                    accept='.pdf,.docx,.xlsx,.xls,.csv,.txt,.png,.jpg,.jpeg,.webp,application/pdf,text/csv,text/plain,image/png,image/jpeg,image/webp'
                    className='hidden'
                    onChange={(e) => {
                      const picked = Array.from(e.target.files || []).slice(0, 3);
                      e.target.value = '';
                      setIngestError('');
                      setIngestFiles(picked);
                    }}
                  />
                  <div>
                    <Button
                      variant='outline'
                      size='sm'
                      type='button'
                      aria-disabled={ingestBusy}
                      onClick={() => ingestFileRef.current?.click()}
                    >
                      ファイルを選ぶ
                    </Button>
                  </div>
                  {ingestFiles.length ? (
                    <ul className='text-std-16N-170 text-solid-gray-800'>
                      {ingestFiles.map((file) => (
                        <li key={file.name}>{file.name}</li>
                      ))}
                    </ul>
                  ) : null}
                  {ingestError ? (
                    <p className='text-red-700' role='alert'>
                      {ingestError}
                    </p>
                  ) : null}
                  <div className='flex justify-end gap-2'>
                    <Button
                      variant='outline'
                      size='sm'
                      type='button'
                      onClick={() => setIngestOpen(false)}
                    >
                      閉じる
                    </Button>
                    <Button
                      variant='solid-fill'
                      size='sm'
                      type='button'
                      aria-disabled={ingestBusy || ingestFiles.length === 0}
                      onClick={() => void readIngest()}
                    >
                      {ingestBusy ? '読んでいます' : '次へ'}
                    </Button>
                  </div>
                </div>
              )}
            </CustomDialogBody>
          </CustomDialogPanel>
        </CustomDialog>
        <FilePreviewDialog
          rowId={preview?.rowId || ''}
          file={preview?.file || null}
          onClose={() => setPreview(null)}
        />
        <CustomDialog isOpen={searchOpen} onClose={() => setSearchOpen(false)}>
          <CustomDialogPanel>
            <CustomDialogHeader hasClose onClose={() => setSearchOpen(false)}>
              検索
            </CustomDialogHeader>
            <CustomDialogBody>
              <div className='flex flex-col gap-4'>
                <label className='block text-std-16B-150'>
                  文で探す
                  <input
                    className={fieldClass}
                    placeholder='先月、処理中の山田'
                    value={draftNatural}
                    onChange={(e) => setDraftNatural(e.target.value)}
                  />
                </label>
                <label className='block text-std-16B-150'>
                  状態
                  <select
                    className={fieldClass}
                    value={draftStatus}
                    onChange={(e) => setDraftStatus(e.target.value)}
                  >
                    <option value=''>すべての状態</option>
                    {(ledger?.statuses || []).map((item) => (
                      <option key={item} value={item}>
                        {item}
                      </option>
                    ))}
                  </select>
                </label>
                <label className='block text-std-16B-150'>
                  キーワード
                  <input
                    className={fieldClass}
                    value={draftQ}
                    onChange={(e) => setDraftQ(e.target.value)}
                  />
                </label>
                {ledger?.role === 'admin' ? (
                  <label className='flex items-center gap-2 text-std-16N-170'>
                    <input
                      type='checkbox'
                      checked={draftDeleted}
                      onChange={(e) => setDraftDeleted(e.target.checked)}
                    />
                    削除したレコードも見る
                  </label>
                ) : null}
                <p className='text-dns-14N-130 text-solid-gray-600'>
                  文を書くと、その解釈を使います。空なら状態とキーワードを使います。
                </p>
                {error ? (
                  <p className='text-red-700' role='alert'>
                    {error}
                  </p>
                ) : null}
                <div className='flex gap-2'>
                  <Button
                    variant='solid-fill'
                    size='md'
                    type='button'
                    onClick={() => void applySearch()}
                  >
                    検索
                  </Button>
                  <Button
                    variant='outline'
                    size='md'
                    type='button'
                    onClick={() => setSearchOpen(false)}
                  >
                    閉じる
                  </Button>
                </div>
              </div>
            </CustomDialogBody>
          </CustomDialogPanel>
        </CustomDialog>
      </div>
    </Shell>
  );
};

export const LedgerFieldsPage = () => {
  const { ledgerId = '' } = useParams();
  const { data: ledger, mutate } = useLedger(ledgerId);
  const loadedFor = useRef('');
  const [draftFields, setDraftFields] = useState<DraftField[]>([]);
  const [systemFields, setSystemFields] = useState<LedgerSystemField[]>(() => systemDraft());
  const [newLabel, setNewLabel] = useState('');
  const [newType, setNewType] = useState<LedgerField['type']>('text');
  const [newOptions, setNewOptions] = useState('');
  const [proposals, setProposals] = useState<LedgerField[]>([]);
  const [suggested, setSuggested] = useState(false);
  const [materialOpen, setMaterialOpen] = useState(false);
  const [materialStep, setMaterialStep] = useState<'source' | 'review'>('source');
  const [materialText, setMaterialText] = useState('');
  const [materialBusy, setMaterialBusy] = useState(false);
  const [materialReading, setMaterialReading] = useState(false);
  const [materialError, setMaterialError] = useState('');
  const [materialFields, setMaterialFields] = useState<LedgerField[]>([]);
  const [materialPicked, setMaterialPicked] = useState<Record<string, boolean>>({});
  const materialFileRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const canEdit = ledger?.role === 'admin';

  useEffect(() => {
    if (!ledger || ledger.id !== ledgerId || loadedFor.current === ledger.id) return;
    loadedFor.current = ledger.id;
    setDraftFields((ledger.fields || []).map((field) => toDraft(field)));
    setSystemFields(systemDraft(ledger.system));
  }, [ledger, ledgerId]);

  const moveField = (index: number, delta: number) => {
    setDraftFields((current) => {
      const target = index + delta;
      if (target < 0 || target >= current.length) return current;
      const next = current.slice();
      const [item] = next.splice(index, 1);
      next.splice(target, 0, item);
      return next;
    });
    setNotice('');
  };

  const addDraftField = () => {
    const label = newLabel.trim();
    if (!label) return;
    if (newType === 'select' && splitOptions(newOptions).length === 0) {
      setError('選択項目の候補を1つ以上書いてください');
      return;
    }
    setError('');
    setNotice('');
    setDraftFields((current) => [
      ...current,
      {
        key: `new-${Date.now()}`,
        id: '',
        label,
        type: newType,
        masked: false,
        optionsText: newOptions,
        promote: false,
      },
    ]);
    setNewLabel('');
    setNewType('text');
    setNewOptions('');
  };

  const suggest = async () => {
    setError('');
    try {
      const res = await teamApi.post<{ fields: LedgerField[] }>(
        `ledger/ledgers/${ledgerId}/assist/definition`,
        {
          note: '',
        },
      );
      setProposals(res.data.fields || []);
      setSuggested(true);
    } catch (e) {
      setError(ledgerError(e, '項目案を作れませんでした'));
    }
  };

  const openMaterial = () => {
    setMaterialStep('source');
    setMaterialText('');
    setMaterialError('');
    setMaterialFields([]);
    setMaterialPicked({});
    setMaterialOpen(true);
  };

  const readMaterialFile = async (file: File) => {
    const ext = file.name.split('.').pop()?.toLowerCase() || '';
    if (!['pdf', 'docx', 'xlsx', 'xls', 'csv', 'txt', 'png', 'jpg', 'jpeg', 'webp'].includes(ext)) {
      setMaterialError(
        '資料は PDF、Word、Excel、CSV、テキスト、画像（PNG、JPEG）で選んでください。',
      );
      return;
    }
    if (file.size > 8 * 1024 * 1024) {
      setMaterialError('ファイルが大きすぎます。8MB までの資料を選んでください。');
      return;
    }
    setMaterialError('');
    setMaterialReading(true);
    try {
      const data = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => {
          const result = String(reader.result || '');
          const comma = result.indexOf(',');
          resolve(comma >= 0 ? result.slice(comma + 1) : result);
        };
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(file);
      });
      const res = await teamApi.post<{ text: string }>(
        `ledger/ledgers/${ledgerId}/assist/material/read`,
        {
          name: file.name,
          media_type: file.type,
          data,
        },
      );
      setMaterialText(res.data.text || '');
    } catch (e) {
      setMaterialError(ledgerError(e, '資料を読めませんでした'));
    } finally {
      setMaterialReading(false);
    }
  };

  const askMaterial = async () => {
    setMaterialError('');
    setMaterialBusy(true);
    try {
      const res = await teamApi.post<{ fields: LedgerField[] }>(
        `ledger/ledgers/${ledgerId}/assist/material`,
        {
          text: materialText,
        },
      );
      const fields = res.data.fields || [];
      setMaterialFields(fields);
      setMaterialPicked(Object.fromEntries(fields.map((field) => [field.label, true])));
      setMaterialStep('review');
    } catch (e) {
      setMaterialError(ledgerError(e, 'モデルから案を受け取れませんでした'));
    } finally {
      setMaterialBusy(false);
    }
  };

  const takeMaterial = () => {
    const chosen = materialFields.filter((field) => materialPicked[field.label]);
    if (!chosen.length) return;
    setDraftFields((current) => {
      const labels = new Set(current.map((item) => item.label));
      const next = [...current];
      for (const field of chosen) {
        if (labels.has(field.label)) continue;
        labels.add(field.label);
        next.push(toDraft(field));
      }
      return next;
    });
    setMaterialOpen(false);
    setNotice('案を一覧に足しました。保存すると台帳に入ります。');
  };

  const adopt = (field: LedgerField) => {
    setDraftFields((current) =>
      current.some((item) => item.label === field.label)
        ? current
        : [...current, toDraft(field, true)],
    );
    setProposals((current) => current.filter((item) => item.label !== field.label));
    setNotice('');
  };

  const saveFields = async () => {
    if (!ledger || !canEdit) return;
    const fields = draftFields.map((field) => ({
      id: field.id,
      label: field.label.trim(),
      type: field.type,
      masked: field.masked,
      options: field.type === 'select' ? splitOptions(field.optionsText) : [],
    }));
    if (fields.some((field) => !field.label)) {
      setError('項目の名前を書いてください');
      return;
    }
    if (fields.some((field) => field.type === 'select' && field.options.length === 0)) {
      setError('選択項目の候補を1つ以上書いてください');
      return;
    }
    setError('');
    try {
      const saved = await patchLedger(ledger.id, { fields, system: systemFields });
      for (const field of draftFields.filter((item) => item.promote)) {
        const created = [...saved.fields]
          .reverse()
          .find((item) => item.label === field.label.trim());
        await teamApi.post(`ledger/ledgers/${ledgerId}/promote`, {
          label: field.label.trim(),
          type: field.type,
          field_id: created?.id || '',
        });
      }
      const reloaded = await mutate();
      const next = reloaded?.fields || saved.fields;
      loadedFor.current = saved.id;
      setDraftFields(next.map((field) => toDraft(field)));
      setSystemFields(systemDraft(reloaded?.system || saved.system));
      setNotice('保存しました');
    } catch (e) {
      setError(ledgerError(e, '定義項目を保存できませんでした'));
    }
  };

  return (
    <Shell tab='fields' ledgerId={ledgerId}>
      <h2 className='text-std-18B-160 text-solid-gray-900'>{ledger?.name || '台帳'}</h2>
      <p className='text-dns-14N-130 text-solid-gray-600'>
        初期項目はすべての台帳にあります。表示するかどうかだけ変えられます。データ登録日時には、レコードを作った時刻が入ります。
        設定項目はこの台帳に足した項目です。名前と順番は変えられます。型は変えられず、項目は消せません。
        カードの追加項目は、そのレコードだけの文字で、ここには出ません。
      </p>
      {!canEdit && ledger ? (
        <p className='text-std-16N-170 text-solid-gray-700'>
          順番と名前を変えるのは、オーナーのチームです。
        </p>
      ) : null}
      <section className='flex flex-col gap-2'>
        <h3 className='text-std-16B-150 text-solid-gray-900'>初期項目</h3>
        <div className='overflow-x-auto rounded-8 border border-solid-gray-300'>
          <table className='w-full border-collapse text-dns-14N-130'>
            <thead>
              <tr className='border-b border-solid-gray-300 bg-solid-gray-50 text-left text-solid-gray-600'>
                <th className='px-3 py-2'>名前</th>
                <th className='px-3 py-2'>表示</th>
              </tr>
            </thead>
            <tbody>
              {systemFields.map((field) => (
                <tr key={field.key} className='border-b border-solid-gray-200 last:border-b-0'>
                  <td className='px-3 py-2 text-std-16N-170 text-solid-gray-900'>
                    {field.label}
                    {field.key === 'registered_at' ? (
                      <span className='ml-2 text-dns-14N-130 text-solid-gray-600'>
                        記録した時刻
                      </span>
                    ) : null}
                  </td>
                  <td className='px-3 py-2'>
                    <label className='inline-flex items-center gap-2 text-std-16N-170'>
                      <input
                        type='checkbox'
                        checked={field.visible}
                        disabled={!canEdit}
                        onChange={(e) =>
                          setSystemFields((current) =>
                            current.map((item) =>
                              item.key === field.key
                                ? { ...item, visible: e.target.checked }
                                : item,
                            ),
                          )
                        }
                      />
                      表示する
                    </label>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <h3 className='mt-10 text-std-16B-150 text-solid-gray-900'>設定項目</h3>
      <p className='text-dns-14N-130 text-solid-gray-600'>
        マスクを付けた項目は、読み取りだけのチームには空で見えます。オーナーと読み書きのチームには、値が見えます。保存してから効きます。
      </p>
      <div className={canEdit ? 'mt-2 grid items-start gap-8 lg:grid-cols-2' : 'mt-2'}>
        <div className='flex flex-col gap-3'>
          {draftFields.length === 0 ? (
            <p className='text-std-16N-170 text-solid-gray-600'>定義項目はまだありません。</p>
          ) : (
            draftFields.map((field, index) => (
              <div
                key={field.key}
                className='grid items-end gap-2 rounded-8 border border-solid-gray-300 p-3 sm:grid-cols-[auto_1fr_auto_auto]'
              >
                <div className='flex flex-col gap-1'>
                  <button
                    type='button'
                    aria-label='上へ'
                    className='rounded-4 border border-solid-gray-300 p-1 text-solid-gray-700 hover:bg-solid-gray-100 disabled:opacity-30'
                    disabled={!canEdit || index === 0}
                    onClick={() => moveField(index, -1)}
                  >
                    <PiArrowUpBold className='size-4' aria-hidden={true} />
                  </button>
                  <button
                    type='button'
                    aria-label='下へ'
                    className='rounded-4 border border-solid-gray-300 p-1 text-solid-gray-700 hover:bg-solid-gray-100 disabled:opacity-30'
                    disabled={!canEdit || index === draftFields.length - 1}
                    onClick={() => moveField(index, 1)}
                  >
                    <PiArrowDownBold className='size-4' aria-hidden={true} />
                  </button>
                </div>
                <label className='block text-dns-14N-130 text-solid-gray-700'>
                  名前
                  <input
                    className={fieldClass}
                    value={field.label}
                    readOnly={!canEdit}
                    onChange={(e) =>
                      setDraftFields((current) =>
                        current.map((item) =>
                          item.key === field.key ? { ...item, label: e.target.value } : item,
                        ),
                      )
                    }
                  />
                </label>
                <div className='pb-2 text-std-16N-170 text-solid-gray-800'>
                  <p className='text-dns-14N-130 text-solid-gray-700'>型</p>
                  <p className='mt-1'>{FIELD_TYPE_LABEL[field.type]}</p>
                </div>
                <label className='flex items-end gap-2 pb-2 text-std-16N-170'>
                  <input
                    type='checkbox'
                    checked={field.masked}
                    disabled={!canEdit}
                    onChange={(e) =>
                      setDraftFields((current) =>
                        current.map((item) =>
                          item.key === field.key ? { ...item, masked: e.target.checked } : item,
                        ),
                      )
                    }
                  />
                  マスク
                </label>
                {field.type === 'select' ? (
                  <label className='block text-dns-14N-130 text-solid-gray-700 sm:col-span-4'>
                    候補（読点区切り）
                    <input
                      className={fieldClass}
                      value={field.optionsText}
                      readOnly={!canEdit}
                      onChange={(e) =>
                        setDraftFields((current) =>
                          current.map((item) =>
                            item.key === field.key
                              ? { ...item, optionsText: e.target.value }
                              : item,
                          ),
                        )
                      }
                    />
                  </label>
                ) : null}
              </div>
            ))
          )}
          {canEdit ? (
            <section className='mt-6 flex flex-col gap-3'>
              <h3 className='text-std-16B-150 text-solid-gray-900'>設定項目を追加</h3>
              <label className='block text-dns-14N-130 text-solid-gray-700'>
                名前
                <input
                  className={fieldClass}
                  value={newLabel}
                  onChange={(e) => setNewLabel(e.target.value)}
                />
              </label>
              <div className='flex items-end gap-2'>
                <label className='block min-w-0 flex-1 text-dns-14N-130 text-solid-gray-700'>
                  型
                  <select
                    className={fieldClass}
                    value={newType}
                    onChange={(e) => setNewType(e.target.value as LedgerField['type'])}
                  >
                    {(Object.keys(FIELD_TYPE_LABEL) as LedgerField['type'][]).map((type) => (
                      <option key={type} value={type}>
                        {FIELD_TYPE_LABEL[type]}
                      </option>
                    ))}
                  </select>
                </label>
                <Button variant='outline' size='sm' type='button' onClick={addDraftField}>
                  追加
                </Button>
              </div>
              {newType === 'select' ? (
                <label className='block text-dns-14N-130 text-solid-gray-700'>
                  候補（読点区切り）
                  <input
                    className={fieldClass}
                    value={newOptions}
                    onChange={(e) => setNewOptions(e.target.value)}
                  />
                </label>
              ) : null}
            </section>
          ) : null}
          {canEdit ? (
            <section className='mt-6 flex flex-col gap-3'>
              <h3 className='text-std-16B-150 text-solid-gray-900'>追加項目から提案</h3>
              <p className='text-dns-14N-130 text-solid-gray-600'>
                カードに書いた追加項目を見て、設定項目にする案を出します。採用すると上の一覧に足されます。保存するまで台帳は変わりません。マスクした項目の値は読みません。
              </p>
              <div>
                <Button variant='outline' size='sm' type='button' onClick={() => void suggest()}>
                  項目を提案
                </Button>
              </div>
              {proposals.length > 0 ? (
                <ul className='flex flex-col gap-2'>
                  {proposals.map((field) => (
                    <li
                      key={field.label}
                      className='flex flex-wrap items-center justify-between gap-2'
                    >
                      <span>
                        {field.label}（{FIELD_TYPE_LABEL[field.type] || field.type}
                        {field.seen ? `、${field.seen}件` : ''}）
                      </span>
                      <Button
                        variant='outline'
                        size='sm'
                        type='button'
                        onClick={() => adopt(field)}
                      >
                        採用
                      </Button>
                    </li>
                  ))}
                </ul>
              ) : suggested ? (
                <p className='text-std-16N-170 text-solid-gray-700'>
                  設定項目にできる追加項目は、まだありません。
                </p>
              ) : null}
            </section>
          ) : null}
        </div>
        {canEdit ? (
          <aside className='flex flex-col gap-3 rounded-8 border border-solid-gray-300 p-4'>
            <h3 className='text-std-16B-150 text-solid-gray-900'>資料から提案</h3>
            <p className='text-dns-14N-130 text-solid-gray-600'>
              PDF、Word、Excel、CSV、テキスト、画像を読み、管理項目の案を出します。この提案ではモデルを使います。マイナンバーや個人番号は送りません。採用した案は左の一覧に足され、保存するまで台帳は変わりません。
            </p>
            <div>
              <Button variant='outline' size='sm' type='button' onClick={openMaterial}>
                資料を読み込む
              </Button>
            </div>
          </aside>
        ) : null}
      </div>
      <CustomDialog isOpen={materialOpen} onClose={() => setMaterialOpen(false)}>
        <CustomDialogPanel className='max-w-2xl'>
          <CustomDialogHeader hasClose onClose={() => setMaterialOpen(false)}>
            {materialStep === 'source' ? '資料を読み込む' : '管理項目の案'}
          </CustomDialogHeader>
          <CustomDialogBody>
            {materialStep === 'source' ? (
              <div className='flex flex-col gap-3'>
                <p className='text-dns-14N-130 text-solid-gray-600'>
                  PDF、Word、Excel、CSV、テキスト、画像（PNG、JPEG）を選ぶか、文章を貼ってください。Excel
                  は見出しと見本だけを読みます。文字の無い PDF
                  は、ページを画像で選んでください。マイナンバーや個人番号の行は送りません。
                </p>
                <textarea
                  className={`${fieldClass} min-h-40`}
                  value={materialText}
                  onChange={(e) => setMaterialText(e.target.value)}
                />
                <input
                  ref={materialFileRef}
                  type='file'
                  accept='.pdf,.docx,.xlsx,.xls,.csv,.txt,.png,.jpg,.jpeg,.webp,application/pdf,text/csv,text/plain,image/png,image/jpeg,image/webp'
                  className='hidden'
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    e.target.value = '';
                    if (file) void readMaterialFile(file);
                  }}
                />
                <div>
                  <Button
                    variant='outline'
                    size='sm'
                    type='button'
                    aria-disabled={materialReading || materialBusy}
                    onClick={() => materialFileRef.current?.click()}
                  >
                    {materialReading ? '読んでいます' : 'ファイルを選ぶ'}
                  </Button>
                </div>
                {materialError ? (
                  <p className='text-red-700' role='alert'>
                    {materialError}
                  </p>
                ) : null}
                <div className='flex justify-end gap-2'>
                  <Button
                    variant='outline'
                    size='sm'
                    type='button'
                    onClick={() => setMaterialOpen(false)}
                  >
                    閉じる
                  </Button>
                  <Button
                    variant='solid-fill'
                    size='sm'
                    type='button'
                    aria-disabled={materialBusy || materialReading || !materialText.trim()}
                    onClick={() => void askMaterial()}
                  >
                    {materialBusy ? '読んでいます' : '次へ'}
                  </Button>
                </div>
              </div>
            ) : (
              <div className='flex flex-col gap-3'>
                <p className='text-dns-14N-130 text-solid-gray-600'>
                  足したい項目に印を付けてください。一覧に足したあと、定義項目の保存で台帳に入ります。
                </p>
                <ul className='flex flex-col gap-2'>
                  {materialFields.map((field) => (
                    <li key={field.label}>
                      <label className='flex items-start gap-2 text-std-16N-170'>
                        <input
                          type='checkbox'
                          className='mt-1'
                          checked={!!materialPicked[field.label]}
                          onChange={(e) =>
                            setMaterialPicked((current) => ({
                              ...current,
                              [field.label]: e.target.checked,
                            }))
                          }
                        />
                        <span>
                          {field.label}（{FIELD_TYPE_LABEL[field.type] || field.type}）
                          {field.options?.length ? `　${field.options.join('、')}` : ''}
                        </span>
                      </label>
                    </li>
                  ))}
                </ul>
                {materialError ? (
                  <p className='text-red-700' role='alert'>
                    {materialError}
                  </p>
                ) : null}
                <div className='flex justify-end gap-2'>
                  <Button
                    variant='outline'
                    size='sm'
                    type='button'
                    onClick={() => setMaterialStep('source')}
                  >
                    戻る
                  </Button>
                  <Button
                    variant='solid-fill'
                    size='sm'
                    type='button'
                    aria-disabled={!materialFields.some((field) => materialPicked[field.label])}
                    onClick={takeMaterial}
                  >
                    一覧に足す
                  </Button>
                </div>
              </div>
            )}
          </CustomDialogBody>
        </CustomDialogPanel>
      </CustomDialog>
      {error ? (
        <p className='text-red-700' role='alert'>
          {error}
        </p>
      ) : null}
      {notice ? <p className='text-std-16N-170 text-solid-gray-700'>{notice}</p> : null}
      {canEdit ? (
        <div className='mt-10'>
          <Button variant='solid-fill' size='md' type='button' onClick={() => void saveFields()}>
            保存
          </Button>
        </div>
      ) : null}
    </Shell>
  );
};

const ApiBlock = ({ children }: { children: string }) => (
  <pre className='mt-2 overflow-x-auto rounded-8 bg-solid-gray-50 p-3 font-mono text-dns-14N-130 text-solid-gray-900'>
    {children}
  </pre>
);

export const LedgerApiPage = () => {
  const { ledgerId = '' } = useParams();
  const { data: ledger } = useLedger(ledgerId);
  const id = ledgerId || '{台帳ID}';

  return (
    <Shell tab='api' ledgerId={ledgerId}>
      <h2 className='text-std-18B-160 text-solid-gray-900'>{ledger?.name || '台帳'}の API</h2>
      <p className='text-std-16N-170 text-solid-gray-700'>
        呼び出し先は、この画面と同じ <span className='font-mono'>/ledger</span>{' '}
        です。ログインした利用者の権限がそのまま効きます。外部システムは、利用者一括管理で発行したサービストークンを{' '}
        <span className='font-mono'>Authorization: Bearer</span>{' '}
        に載せます。このトークンは台帳だけに効き、チャットや管理画面には使えません。読み取りは閲覧者、値の登録は読み書き、定義とアクセス権はオーナーです。マスクした項目は、閲覧者には空で返ります。
      </p>

      <section className='mt-8 flex flex-col gap-2'>
        <h3 className='text-std-16B-150 text-solid-gray-900'>レコードを読む</h3>
        <p className='text-dns-14N-130 text-solid-gray-600'>
          条件を空にすると、見えているレコードを返します。削除した行は、オーナーが include_deleted=1
          を付けたときだけ入ります。
        </p>
        <ApiBlock>{`GET /ledger/ledgers/${id}/rows?status=&q=&offset=0&limit=50`}</ApiBlock>
        <ApiBlock>{`GET /ledger/rows/{レコードID}`}</ApiBlock>
      </section>

      <section className='mt-8 flex flex-col gap-2'>
        <h3 className='text-std-16B-150 text-solid-gray-900'>レコードを書く</h3>
        <p className='text-dns-14N-130 text-solid-gray-600'>
          同じ business_key があればその行を更新し、無ければ新しい行を作ります。fields のキーは項目
          ID です。origins を省いた値は取込になります。画面から人が入れるときは
          entered、資料から補うときは inferred
          を付けます。推測は取込と入力を上書きせず、取込は入力を上書きしません。残せなかった項目は
          kept で返ります。
        </p>
        <ApiBlock>{`POST /ledger/ledgers/${id}/rows
POST /ledger/rows/{レコードID}`}</ApiBlock>
        <ApiBlock>{`{
  "business_key": "",
  "status": "受付",
  "assignee": "",
  "comment": "",
  "fields": { "項目ID": "値" },
  "origins": { "項目ID": { "origin": "imported" } },
  "extras": [{ "label": "追加の名前", "value": "文字" }]
}`}</ApiBlock>
      </section>

      <section className='mt-8 flex flex-col gap-2'>
        <h3 className='text-std-16B-150 text-solid-gray-900'>ファイルで書き出す</h3>
        <p className='text-dns-14N-130 text-solid-gray-600'>
          JSON は台帳の項目一覧と行です。設定項目は fields に項目 ID で入り、追加項目は extras
          に入ります。出自は origins に入ります。JSONL は行だけです。CSV は
          business_key、status、assignee、comment
          と設定項目の名前だけで、追加項目と出自は入りません。文字コードは UTF-8（BOM
          付き）です。見られないマスク項目は、どの形式からも除きます。
        </p>
        <ApiBlock>{`GET /ledger/ledgers/${id}/export?format=json&status=&q=&include_deleted=0`}</ApiBlock>
        <p className='text-dns-14N-130 text-solid-gray-600'>format は json、jsonl、csv です。</p>
      </section>

      <section className='mt-8 flex flex-col gap-2'>
        <h3 className='text-std-16B-150 text-solid-gray-900'>ファイルから行を入れる</h3>
        <p className='text-dns-14N-130 text-solid-gray-600'>
          定義は変わりません。CSV は business_key
          が必要で、知らない列はエラーになります。追加項目は変わりません。JSON と JSONL
          は、知らない項目 ID を追加項目にします。ここから入れた値は取込です。
        </p>
        <ApiBlock>{`POST /ledger/ledgers/${id}/import
{ "format": "json", "text": "…" }`}</ApiBlock>
      </section>

      <section className='mt-8 flex flex-col gap-2'>
        <h3 className='text-std-16B-150 text-solid-gray-900'>添付ファイル</h3>
        <p className='text-dns-14N-130 text-solid-gray-600'>
          出典も、項目としてのファイルも、レコードの添付です。登録は multipart の file です。Office
          のプレビューは文字と表だけを返し、元のファイルは別の取得で落とします。文書台帳への保存は、row_id
          と file_id があると同じ行の本体を差し替え、無いときは下書きの行を作ります。force=1
          は、開いた版と違っていても上書きします。確定の行を上書きできるのはオーナーです。
        </p>
        <ApiBlock>{`POST /ledger/rows/{レコードID}/files
GET  /ledger/rows/{レコードID}/files/{ファイルID}
GET  /ledger/rows/{レコードID}/files/{ファイルID}/preview
PUT  /ledger/office/files?name=議事.docx&row_id=&file_id=&force=0
POST /ledger/office/rows/{レコードID}/body
{ "file_id": "以前の本体" }`}</ApiBlock>
      </section>

      <section className='mt-8 flex flex-col gap-2'>
        <h3 className='text-std-16B-150 text-solid-gray-900'>資料から値の案を出す</h3>
        <p className='text-dns-14N-130 text-solid-gray-600'>
          1回目は保存しません。files は名前と base64
          です。表に書いてある値は取込、空欄を補った値は推測です。2回目で残す行の番号を送ると、レコードになり、出典ファイルが付きます。状態は変わりません。
        </p>
        <ApiBlock>{`POST /ledger/ledgers/${id}/ingest
{ "files": [{ "name": "備品.xlsx", "media_type": "…", "data": "base64" }] }

POST /ledger/ledgers/${id}/ingest/{batch_id}
{ "indexes": [0, 1] }`}</ApiBlock>
      </section>

      <section className='mt-8 flex flex-col gap-2'>
        <h3 className='text-std-16B-150 text-solid-gray-900'>ほかの呼び出し</h3>
        <ApiBlock>{`GET   /ledger/ledgers
POST  /ledger/ledgers
GET   /ledger/ledgers/${id}
PATCH /ledger/ledgers/${id}
POST  /ledger/ledgers/${id}/delete
POST  /ledger/rows/{レコードID}/delete
POST  /ledger/rows/{レコードID}/restore
POST  /ledger/ledgers/${id}/promote
POST  /ledger/ledgers/${id}/assist/definition
POST  /ledger/ledgers/${id}/assist/material
POST  /ledger/ledgers/${id}/assist/query`}</ApiBlock>
        <p className='text-dns-14N-130 text-solid-gray-600'>
          promote は追加項目を設定項目へ移します。assist/definition
          は追加項目から設定項目の案、assist/material
          は資料から設定項目の案です。どちらも保存しません。assist/query
          は検索文を状態とキーワードに分けます。
        </p>
      </section>
    </Shell>
  );
};

export const LedgerExportPage = () => {
  const { ledgerId = '' } = useParams();
  const fileRef = useRef<HTMLInputElement>(null);
  const { data: ledger } = useLedger(ledgerId);
  const [status, setStatus] = useState('');
  const [q, setQ] = useState('');
  const [showDeleted, setShowDeleted] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const canWrite = ledger?.role === 'admin' || ledger?.role === 'editor';

  const download = async (format: 'json' | 'jsonl' | 'csv') => {
    setError('');
    setNotice('');
    try {
      const res = await teamApi.getBlob(`ledger/ledgers/${ledgerId}/export`, {
        params: {
          format,
          status,
          q: q.trim(),
          include_deleted: showDeleted ? '1' : '0',
        },
      });
      const url = URL.createObjectURL(res.blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `${ledger?.name || 'ledger'}.${format}`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(ledgerError(e, '書き出せませんでした'));
    }
  };

  const importText = async (format: string, file: File) => {
    setError('');
    setNotice('');
    try {
      const text = await file.text();
      const res = await teamApi.post<{ imported: number }>(`ledger/ledgers/${ledgerId}/import`, {
        format,
        text,
      });
      setNotice(`${res.data.imported}件を読み込みました`);
    } catch (e) {
      setError(ledgerError(e, '読み込めませんでした'));
    }
  };

  return (
    <Shell tab='export' ledgerId={ledgerId}>
      <h2 className='text-std-18B-160 text-solid-gray-900'>{ledger?.name || '台帳'}</h2>
      <section className='flex max-w-xl flex-col gap-3'>
        <h3 className='text-std-16B-150'>書き出し</h3>
        <p className='text-dns-14N-130 text-solid-gray-600'>
          条件に合うレコードを、JSON、JSONL、CSV
          で書き出します。条件を空にすると、見えているレコードをすべて書き出します。
        </p>
        <label className='block text-std-16B-150'>
          状態
          <select className={fieldClass} value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value=''>すべての状態</option>
            {(ledger?.statuses || []).map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </label>
        <label className='block text-std-16B-150'>
          キーワード
          <input className={fieldClass} value={q} onChange={(e) => setQ(e.target.value)} />
        </label>
        {ledger?.role === 'admin' ? (
          <label className='flex items-center gap-2 text-std-16N-170'>
            <input
              type='checkbox'
              checked={showDeleted}
              onChange={(e) => setShowDeleted(e.target.checked)}
            />
            削除したレコードも含める
          </label>
        ) : null}
        <div className='flex flex-wrap gap-2'>
          {(['json', 'jsonl', 'csv'] as const).map((format) => (
            <Button
              key={format}
              variant='outline'
              size='sm'
              type='button'
              onClick={() => void download(format)}
            >
              {format.toUpperCase()}
            </Button>
          ))}
        </div>
      </section>
      <section className='flex max-w-xl flex-col gap-3'>
        <h3 className='text-std-16B-150'>読み込み</h3>
        <p className='text-dns-14N-130 text-solid-gray-600'>
          JSON、JSONL、CSV
          のレコードをこの台帳へ取り込みます。定義項目の案を読むものではありません。JSON
          を読み込んでも、定義は変わりません。
        </p>
        {canWrite ? (
          <>
            <Button
              variant='outline'
              size='sm'
              type='button'
              onClick={() => fileRef.current?.click()}
            >
              ファイルを選ぶ
            </Button>
            <input
              ref={fileRef}
              className='hidden'
              type='file'
              accept='.json,.jsonl,.csv,text/csv,application/json'
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = '';
                if (!file) return;
                const format = file.name.endsWith('.csv')
                  ? 'csv'
                  : file.name.endsWith('.jsonl')
                    ? 'jsonl'
                    : 'json';
                void importText(format, file);
              }}
            />
          </>
        ) : (
          <p className='text-std-16N-170 text-solid-gray-700'>
            読み込むには、読み書きできるチームである必要があります。
          </p>
        )}
      </section>
      {error ? (
        <p className='text-red-700' role='alert'>
          {error}
        </p>
      ) : null}
      {notice ? <p className='text-std-16N-170 text-solid-gray-700'>{notice}</p> : null}
    </Shell>
  );
};

export const LedgerRowPage = () => {
  const { rowId = '' } = useParams();
  const { data: row } = useLedgerRow(rowId);
  if (!row) {
    return (
      <Shell tab='card'>
        <p className='text-std-16N-170'>読み込んでいます。</p>
      </Shell>
    );
  }
  return <Navigate to={`/ledger/${row.ledger_id}/card/${row.id}`} replace />;
};

export const LedgerCardPage = () => {
  const { ledgerId = '', rowId = '' } = useParams();
  const navigate = useNavigate();
  const { data: row, mutate } = useLedgerRow(rowId || undefined);
  const { data: ledger } = useLedger(ledgerId || row?.ledger_id);
  const { data: listData, mutate: reloadRows } = useLedgerRows(
    ledgerId || row?.ledger_id,
    'status=&q=&include_deleted=0',
  );
  const [draft, setDraft] = useState<LedgerRow | null>(null);
  const [touched, setTouched] = useState<Record<string, true>>({});
  const [pendingExtras, setPendingExtras] = useState<Record<string, string>>({});
  const [error, setError] = useState('');
  const [historyOpen, setHistoryOpen] = useState(false);
  const [preview, setPreview] = useState<LedgerFile | null>(null);
  const [pageIndex, setPageIndex] = useState(0);
  const [frameHeight, setFrameHeight] = useState(360);
  const frameRef = useRef<HTMLDivElement>(null);
  const current = draft && draft.id === row?.id ? draft : row;

  const setField = (id: string, value: string) => {
    if (!current) return;
    setTouched((items) => ({ ...items, [id]: true }));
    setDraft({ ...current, fields: { ...current.fields, [id]: value } });
  };

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!current) return;
    setError('');
    try {
      const extras = current.extras.slice();
      for (const [label, value] of Object.entries(pendingExtras)) {
        if (!value.trim()) continue;
        const index = extras.findIndex((item) => item.label === label);
        if (index >= 0) extras[index] = { label, value: value.trim() };
        else extras.push({ label, value: value.trim() });
      }
      const origins = Object.fromEntries(
        Object.keys(touched).map((id) => [id, { origin: 'entered' }]),
      );
      const saved = await updateRow(current.id, {
        status: current.status,
        assignee: current.assignee,
        comment: current.comment,
        fields: current.fields,
        origins,
        extras,
      });
      setTouched({});
      setPendingExtras({});
      setDraft(saved);
      await mutate();
    } catch (e) {
      setError(ledgerError(e, '保存できませんでした'));
    }
  };

  useEffect(() => {
    setDraft(null);
    setTouched({});
    setPendingExtras({});
    setPageIndex(0);
    setHistoryOpen(false);
  }, [rowId]);

  useEffect(() => {
    const node = frameRef.current;
    if (!node) return;
    const update = () => setFrameHeight(node.clientHeight || 360);
    update();
    const observer = new ResizeObserver(update);
    observer.observe(node);
    return () => observer.disconnect();
  }, [current?.id, ledger?.id]);

  useEffect(() => {
    if (ledger?.id && current?.id) rememberRow(ledger.id, current.id);
  }, [ledger?.id, current?.id]);

  const canWrite = ledger?.role === 'admin' || ledger?.role === 'editor';
  const restoreBody = async (fileId: string) => {
    if (!current) return;
    setError('');
    try {
      await teamApi.post(`ledger/office/rows/${current.id}/body`, { file_id: fileId });
      await mutate();
      await reloadRows();
    } catch (e) {
      setError(ledgerError(e, 'この版を現在にできませんでした'));
    }
  };
  const addRecord = async () => {
    if (!ledger) return;
    setError('');
    try {
      const created = await saveRow(ledger.id, { status: ledger.statuses[0] || '' });
      await reloadRows();
      rememberRow(ledger.id, created.id);
      setDraft(null);
      setPendingExtras({});
      navigate(`/ledger/${ledger.id}/card/${created.id}`);
    } catch (e) {
      setError(ledgerError(e, 'レコードを作れませんでした'));
    }
  };

  if (!rowId) {
    return (
      <Shell tab='card' ledgerId={ledgerId}>
        <div className='flex flex-wrap items-center justify-between gap-2'>
          <p className='text-std-16N-170 text-solid-gray-700'>
            レコードが選ばれていません。追加すると、このカードで入力できます。
          </p>
          {canWrite ? (
            <Button variant='solid-fill' size='sm' type='button' onClick={() => void addRecord()}>
              レコードを追加
            </Button>
          ) : null}
        </div>
        {error ? <p className='text-red-700'>{error}</p> : null}
      </Shell>
    );
  }

  if (!current || !ledger) {
    return (
      <Shell tab='card' ledgerId={ledgerId}>
        <p className='text-std-16N-170'>読み込んでいます。</p>
      </Shell>
    );
  }

  const records = listData?.rows || [];
  const recordIndex = records.findIndex((item) => item.id === current.id);
  const previous = recordIndex > 0 ? records[recordIndex - 1] : undefined;
  const following =
    recordIndex >= 0 && recordIndex < records.length - 1 ? records[recordIndex + 1] : undefined;
  const extraLabels: string[] = [];
  const seenExtras = new Set(current.extras.map((item) => item.label.trim()).filter(Boolean));
  for (const item of records) {
    for (const extra of item.extras || []) {
      const label = extra.label.trim();
      if (!label || seenExtras.has(label)) continue;
      seenExtras.add(label);
      extraLabels.push(label);
    }
  }
  const setExtra = (index: number, patch: Partial<LedgerExtra>) => {
    const extras = current.extras.slice();
    extras[index] = { ...extras[index], ...patch };
    setDraft({ ...current, extras });
  };
  const openRecord = (id: string) => {
    rememberRow(ledger.id, id);
    setDraft(null);
    setPendingExtras({});
    navigate(`/ledger/${ledger.id}/card/${id}`);
  };

  const cells: { key: string; tall: boolean; node: ReactNode }[] = [];
  const pushCell = (
    key: string,
    kind: keyof typeof COLUMN_KIND,
    label: string,
    control: ReactNode,
    tall = false,
    origin?: string,
  ) => {
    cells.push({
      key,
      tall,
      node: (
        <label className='block text-std-16B-150 text-solid-gray-900'>
          <span className='flex items-center gap-1.5'>
            <KindMark kind={kind} />
            {label}
            <OriginMark origin={origin} />
          </span>
          {control}
        </label>
      ),
    });
  };
  if (systemShown(ledger.system, 'business_key')) {
    pushCell(
      'business_key',
      'system',
      '業務キー',
      <input className={fieldClass} value={current.business_key} readOnly />,
    );
  }
  if (systemShown(ledger.system, 'status')) {
    pushCell(
      'status',
      'system',
      '状態',
      <select
        className={fieldClass}
        value={current.status}
        onChange={(e) => setDraft({ ...current, status: e.target.value })}
      >
        {ledger.statuses.map((item) => (
          <option key={item}>{item}</option>
        ))}
      </select>,
    );
  }
  if (systemShown(ledger.system, 'assignee')) {
    pushCell(
      'assignee',
      'system',
      '担当',
      <input
        className={fieldClass}
        value={current.assignee}
        onChange={(e) => setDraft({ ...current, assignee: e.target.value })}
      />,
    );
  }
  if (systemShown(ledger.system, 'registered_at')) {
    pushCell(
      'registered_at',
      'system',
      'データ登録日時',
      <input className={fieldClass} value={formatWhen(current.created_at)} readOnly />,
    );
  }
  for (const field of ledger.fields) {
    const tall = field.type === 'longtext';
    const control =
      field.type === 'select' ? (
        <select
          className={fieldClass}
          value={current.fields[field.id] || ''}
          onChange={(e) => setField(field.id, e.target.value)}
        >
          <option value=''>選ぶ</option>
          {(field.options || []).map((opt) => (
            <option key={opt}>{opt}</option>
          ))}
        </select>
      ) : field.type === 'longtext' ? (
        <textarea
          className={fieldClass}
          rows={3}
          value={current.fields[field.id] || ''}
          onChange={(e) => setField(field.id, e.target.value)}
        />
      ) : field.type === 'file' ? (
        (() => {
          const linked = findFieldFile(current.files, field.id, current.fields[field.id] || '');
          return linked ? (
            <Button
              variant='outline'
              size='sm'
              type='button'
              onClick={() => {
                const href = officeHref(current.id, linked, linked.role === 'body');
                if (href) navigate(href);
                else setPreview(linked);
              }}
            >
              {linked.name}
            </Button>
          ) : (
            <p className='mt-1 text-std-16N-170 text-solid-gray-600'>ファイルはまだありません</p>
          );
        })()
      ) : (
        <input
          className={fieldClass}
          type={field.type === 'date' ? 'date' : field.type === 'number' ? 'number' : 'text'}
          value={current.fields[field.id] || ''}
          onChange={(e) => setField(field.id, e.target.value)}
        />
      );
    pushCell(field.id, 'defined', field.label, control, tall, current.origins?.[field.id]?.origin);
  }
  current.extras.forEach((extra, index) => {
    cells.push({
      key: `extra-${index}`,
      tall: true,
      node: (
        <div className='rounded-8 border border-dashed border-solid-gray-420 p-3'>
          <span className='mb-1 flex items-center gap-1.5 text-std-16B-150 text-solid-gray-900'>
            <KindMark kind='extra' />
            追加項目
          </span>
          <input
            className={fieldClass}
            aria-label={`追加項目${index + 1}の項目名`}
            placeholder='項目名'
            value={extra.label}
            onChange={(e) => setExtra(index, { label: e.target.value })}
          />
          <input
            className={fieldClass}
            aria-label={
              extra.label.trim() ? `${extra.label.trim()}の値` : `追加項目${index + 1}の値`
            }
            placeholder='値'
            value={extra.value}
            onChange={(e) => setExtra(index, { value: e.target.value })}
          />
        </div>
      ),
    });
  });
  for (const label of extraLabels) {
    pushCell(
      `shared-${label}`,
      'extra',
      label,
      <input
        className={fieldClass}
        value={pendingExtras[label] || ''}
        placeholder='値'
        onChange={(e) =>
          setPendingExtras((currentValues) => ({ ...currentValues, [label]: e.target.value }))
        }
      />,
    );
  }
  cells.push({
    key: 'add-extra',
    tall: false,
    node: (
      <div className='flex h-full items-end'>
        <Button
          variant='outline'
          size='sm'
          type='button'
          onClick={() => {
            setDraft({ ...current, extras: [...current.extras, { label: '', value: '' }] });
            setPageIndex(1000);
          }}
        >
          追加項目を足す
        </Button>
      </div>
    ),
  });
  if (systemShown(ledger.system, 'comment')) {
    pushCell(
      'comment',
      'system',
      'コメント',
      <textarea
        className={fieldClass}
        rows={3}
        value={current.comment}
        onChange={(e) => setDraft({ ...current, comment: e.target.value })}
      />,
      true,
    );
  }

  const columnBudget = Math.max(2, Math.floor(frameHeight / 108));
  const cardPages: (typeof cells)[][] = [];
  let column: typeof cells = [];
  let columns: (typeof cells)[] = [];
  let used = 0;
  const pushColumn = () => {
    if (!column.length) return;
    columns.push(column);
    column = [];
    used = 0;
    if (columns.length === 2) {
      cardPages.push(columns);
      columns = [];
    }
  };
  for (const cell of cells) {
    const weight = cell.tall ? 2 : 1;
    if (used + weight > columnBudget && column.length) pushColumn();
    column.push(cell);
    used += weight;
  }
  pushColumn();
  if (columns.length) cardPages.push(columns);
  const safePage = Math.min(pageIndex, Math.max(0, cardPages.length - 1));
  const visibleColumns = cardPages[safePage] || [];

  return (
    <Shell tab='card' ledgerId={ledger.id} rowId={current.id}>
      <div className='flex min-h-0 flex-1 flex-col gap-3'>
        <div className='flex shrink-0 flex-wrap items-end justify-between gap-2'>
          <h2 className='text-std-18B-160 text-solid-gray-900'>{ledger.name}</h2>
          <div className='flex flex-wrap items-center gap-2'>
            {canWrite ? (
              <Button variant='solid-fill' size='sm' type='button' onClick={() => void addRecord()}>
                レコードを追加
              </Button>
            ) : null}
            <Button
              variant='outline'
              size='sm'
              type='button'
              aria-disabled={!previous || undefined}
              onClick={() => previous && openRecord(previous.id)}
            >
              前のレコード
            </Button>
            <span className='text-dns-14N-130 text-solid-gray-600'>
              {recordIndex >= 0 ? `${recordIndex + 1} / ${records.length}` : current.business_key}
            </span>
            <Button
              variant='outline'
              size='sm'
              type='button'
              aria-disabled={!following || undefined}
              onClick={() => following && openRecord(following.id)}
            >
              次のレコード
            </Button>
          </div>
        </div>
        {officeTarget(current.files) || (current.files || []).some((file) => file.role === 'former') ? (
          <div className='flex shrink-0 flex-col gap-2'>
            {(() => {
              const target = officeTarget(current.files);
              const href = target ? officeHref(current.id, target.file, target.bound) : '';
              const canRestore =
                canWrite &&
                !current.deleted_at &&
                (current.status !== '確定' || ledger?.role === 'admin');
              const formers = (current.files || [])
                .filter((file) => file.role === 'former')
                .slice()
                .sort((left, right) =>
                  (right.saved_at || right.replaced_at || '').localeCompare(
                    left.saved_at || left.replaced_at || '',
                  ),
                );
              return (
                <>
                  {target ? (
                    <div className='flex flex-wrap items-center gap-2'>
                      <span className='w-10 shrink-0 text-dns-14N-130 text-solid-gray-600'>現在</span>
                      {href ? (
                        <Button
                          variant='outline'
                          size='sm'
                          type='button'
                          onClick={() => navigate(href)}
                        >
                          {target.file.name}
                        </Button>
                      ) : (
                        <Button
                          variant='outline'
                          size='sm'
                          type='button'
                          onClick={() => setPreview(target.file)}
                        >
                          {target.file.name}
                        </Button>
                      )}
                      <span className='text-dns-14N-130 text-solid-gray-600'>
                        {versionWhen(target.file)}
                      </span>
                    </div>
                  ) : null}
                  {formers.map((file) => {
                    const sameName = target?.file.name === file.name;
                    const openFormer = () => {
                      const previousHref = officeHref(current.id, file, false);
                      if (previousHref) navigate(previousHref);
                      else setPreview(file);
                    };
                    return (
                      <div key={file.file_id} className='flex flex-wrap items-center gap-2'>
                        <span className='w-10 shrink-0 text-dns-14N-130 text-solid-gray-600'>以前</span>
                        {sameName ? null : (
                          <Button variant='outline' size='sm' type='button' onClick={openFormer}>
                            {file.name}
                          </Button>
                        )}
                        <span className='text-dns-14N-130 text-solid-gray-800'>{versionWhen(file)}</span>
                        {sameName ? (
                          <Button variant='outline' size='sm' type='button' onClick={openFormer}>
                            開く
                          </Button>
                        ) : null}
                        {canRestore ? (
                          <Button
                            variant='outline'
                            size='sm'
                            type='button'
                            onClick={() => void restoreBody(file.file_id)}
                          >
                            この版を現在にする
                          </Button>
                        ) : null}
                      </div>
                    );
                  })}
                </>
              );
            })()}
          </div>
        ) : null}
        {sourceFiles(current.files).length ? (
          <div className='flex shrink-0 flex-wrap items-center gap-2'>
            <span className='text-dns-14N-130 text-solid-gray-600'>出典</span>
            {sourceFiles(current.files).map((file) => (
              <Button
                key={file.file_id}
                variant='outline'
                size='sm'
                type='button'
                onClick={() => {
                  const sourceHref = officeHref(current.id, file, file.role === 'body');
                  if (sourceHref) navigate(sourceHref);
                  else setPreview(file);
                }}
              >
                {file.name}
              </Button>
            ))}
          </div>
        ) : null}
        <FilePreviewDialog rowId={current.id} file={preview} onClose={() => setPreview(null)} />
        <form className='flex min-h-0 flex-1 flex-col gap-3' onSubmit={save}>
          <div ref={frameRef} className='min-h-0 flex-1 overflow-hidden'>
            <div className='grid h-full grid-cols-2 items-start gap-x-8'>
              {[0, 1].map((index) => (
                <div key={index} className='flex min-w-0 flex-col gap-4'>
                  {(visibleColumns[index] || []).map((cell) => (
                    <div key={cell.key}>{cell.node}</div>
                  ))}
                </div>
              ))}
            </div>
          </div>
          {error ? <p className='shrink-0 text-red-700'>{error}</p> : null}
          <div className='flex shrink-0 flex-wrap items-center justify-between gap-2 border-t border-solid-gray-200 pt-3'>
            <div className='flex items-center gap-2'>
              <Button
                variant='outline'
                size='sm'
                type='button'
                aria-disabled={safePage <= 0 || undefined}
                onClick={() => setPageIndex(Math.max(0, safePage - 1))}
              >
                前の頁
              </Button>
              <span className='text-dns-14N-130 text-solid-gray-600'>
                {cardPages.length ? safePage + 1 : 1} / {Math.max(1, cardPages.length)}
              </span>
              <Button
                variant='outline'
                size='sm'
                type='button'
                aria-disabled={safePage >= cardPages.length - 1 || undefined}
                onClick={() => setPageIndex(Math.min(cardPages.length - 1, safePage + 1))}
              >
                次の頁
              </Button>
            </div>
            <div className='flex flex-wrap gap-2'>
              <Button
                variant='outline'
                size='md'
                type='button'
                onClick={() => setHistoryOpen(true)}
              >
                履歴
              </Button>
              <Button
                variant='outline'
                size='md'
                type='button'
                onClick={async () => {
                  try {
                    await teamApi.post(
                      `ledger/rows/${current.id}/${current.deleted_at ? 'restore' : 'delete'}`,
                    );
                    await mutate();
                  } catch (e) {
                    setError(ledgerError(e, '操作できませんでした'));
                  }
                }}
              >
                {current.deleted_at ? '戻す' : '削除'}
              </Button>
              <Button variant='solid-fill' size='md' type='submit'>
                保存
              </Button>
            </div>
          </div>
        </form>
      </div>
      <CustomDialog isOpen={historyOpen} onClose={() => setHistoryOpen(false)}>
        <CustomDialogPanel className='max-w-2xl'>
          <CustomDialogHeader hasClose onClose={() => setHistoryOpen(false)}>
            履歴
          </CustomDialogHeader>
          <CustomDialogBody>
            {(current.revisions || []).length === 0 ? (
              <p className='text-std-16N-170 text-solid-gray-700'>履歴はまだありません。</p>
            ) : (
              <ul className='flex flex-col gap-2 text-std-16N-170 text-solid-gray-800'>
                {current.revisions?.map((rev) => (
                  <li key={rev.id}>
                    {formatWhen(rev.created_at)} {rev.actor_user_id}{' '}
                    {rev.changes
                      .map((change) => change.label)
                      .filter(Boolean)
                      .join('、')}
                  </li>
                ))}
              </ul>
            )}
          </CustomDialogBody>
        </CustomDialogPanel>
      </CustomDialog>
    </Shell>
  );
};

const ROLE_OPTIONS: { value: LedgerGrant['role'] | ''; label: string }[] = [
  { value: 'admin', label: 'オーナー' },
  { value: 'editor', label: '読み書き' },
  { value: 'viewer', label: '読み取りだけ' },
  { value: '', label: 'なし' },
];

export const LedgerAccessPage = () => {
  const { ledgerId = '' } = useParams();
  const { config } = useLedgerConfig();
  const { data: ledger, mutate } = useLedger(ledgerId);
  const [roles, setRoles] = useState<Record<string, LedgerGrant['role'] | ''>>({});
  const [error, setError] = useState('');
  const [savedNote, setSavedNote] = useState('');

  useEffect(() => {
    if (!ledger) return;
    const next: Record<string, LedgerGrant['role'] | ''> = {};
    for (const grant of ledger.grants || []) {
      next[grant.team_id] = grant.role;
    }
    setRoles(next);
  }, [ledger]);

  const teams = (() => {
    const known = new Map((config?.teams || []).map((team) => [team.id, team.name]));
    for (const grant of ledger?.grants || []) {
      if (!known.has(grant.team_id)) known.set(grant.team_id, grant.team_id);
    }
    return [...known.entries()].map(([id, name]) => ({ id, name }));
  })();

  const save = async () => {
    if (!ledger) return;
    const grants = teams
      .map((team) => ({ team_id: team.id, role: roles[team.id] || '' }))
      .filter(
        (grant): grant is LedgerGrant =>
          grant.role === 'admin' || grant.role === 'editor' || grant.role === 'viewer',
      );
    if (!grants.some((grant) => grant.role === 'admin')) {
      setError('オーナーにするチームを1つ残してください');
      setSavedNote('');
      return;
    }
    setError('');
    try {
      await patchLedger(ledger.id, { grants });
      setSavedNote('保存しました');
      await mutate();
    } catch (e) {
      setSavedNote('');
      setError(ledgerError(e, 'アクセス権を保存できませんでした'));
    }
  };

  const editable = ledger?.role === 'admin';

  return (
    <Shell tab='access' ledgerId={ledgerId}>
      <section className='flex flex-col gap-3'>
        <h2 className='text-std-18B-160 text-solid-gray-900'>
          {ledger?.name || '台帳'}のアクセス権
        </h2>
        <p className='text-std-16N-170 text-solid-gray-700'>
          オーナーは台帳を管理するチームです。読み書きと読み取りだけは、それ以外のチームへ個別に渡せます。
        </p>
        {!ledger ? <p className='text-std-16N-170'>読み込んでいます。</p> : null}
        {ledger && teams.length === 0 ? (
          <p className='text-std-16N-170 text-solid-gray-600'>
            この棟に設定できるチームがありません。
          </p>
        ) : null}
        {ledger && teams.length > 0 ? (
          <div className='overflow-x-auto rounded-8 border border-solid-gray-300'>
            <table className='w-full min-w-[40rem] border-collapse text-dns-14N-130'>
              <thead>
                <tr className='border-b border-solid-gray-300 bg-solid-gray-50 text-left text-solid-gray-600'>
                  <th className='px-3 py-2'>チーム</th>
                  <th className='px-3 py-2'>権限</th>
                </tr>
              </thead>
              <tbody>
                {teams.map((team) => (
                  <tr key={team.id} className='border-b border-solid-gray-200 last:border-b-0'>
                    <td className='px-3 py-2 text-std-16N-170 text-solid-gray-900'>{team.name}</td>
                    <td className='px-3 py-2'>
                      <select
                        className='rounded-8 border border-solid-gray-300 bg-white px-3 py-1.5 text-std-16N-170'
                        aria-label={`${team.name}の権限`}
                        value={roles[team.id] || ''}
                        disabled={!editable}
                        onChange={(e) =>
                          setRoles((current) => ({
                            ...current,
                            [team.id]: e.target.value as LedgerGrant['role'] | '',
                          }))
                        }
                      >
                        {ROLE_OPTIONS.map((option) => (
                          <option key={option.label} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
        {error ? (
          <p className='text-red-700' role='alert'>
            {error}
          </p>
        ) : null}
        {savedNote ? <p className='text-solid-gray-700'>{savedNote}</p> : null}
        {editable ? (
          <div>
            <Button variant='solid-fill' size='sm' type='button' onClick={() => void save()}>
              保存
            </Button>
          </div>
        ) : ledger ? (
          <p className='text-dns-14N-130 text-solid-gray-600'>
            この台帳のアクセス権を変えるには、オーナーのチームに入っている必要があります。
          </p>
        ) : null}
      </section>
    </Shell>
  );
};

export const LegacyLedgerRowRedirect = () => {
  const { rowId } = useParams();
  return <Navigate to={rowId ? `/ledger/rows/${rowId}` : '/ledger'} replace />;
};
