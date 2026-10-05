import { useEffect, useRef, useState } from 'react';
import { PiBookOpenBold, PiCopySimple, PiFilePlus } from 'react-icons/pi';
import { PageTitle } from '@/components/PageTitle';
import {
  CustomDialog,
  CustomDialogBody,
  CustomDialogHeader,
  CustomDialogPanel,
} from '@/components/ui/CustomDialog';
import { Button } from '@/components/ui/dads/Button';
import { Disclosure, DisclosureSummary } from '@/components/ui/dads/Disclosure';
import { Input } from '@/components/ui/dads/Input';
import { Label } from '@/components/ui/dads/Label';
import { Legend } from '@/components/ui/dads/Legend';
import {
  linkActiveStyle,
  linkDefaultStyle,
  linkFocusStyle,
  linkHoverStyle,
} from '@/components/ui/dads/Link';
import { Textarea } from '@/components/ui/dads/Textarea';
import { ManagedAppHeader } from '@/features/exapp/components/ManagedAppHeader';
import { useRegisteredAppMeta } from '@/features/exapp/hooks/useRegisteredAppMeta';
import { COMMON_EXAPPS_TEAM_ID } from '@/features/exapps/constants';
import { DiagramTypeButton } from '@/features/generate-diagram/components/DiagramTypeButton';
import { ModelSelector } from '@/features/generate-diagram/components/ModelSelector';
import { DIAGRAM_DATA } from '@/features/generate-diagram/constants';
import type { DiagramType } from '@/features/generate-diagram/types';
import { useChatApi } from '@/hooks/useChatApi';
import { useSelectedModel } from '@/hooks/useSelectedModel';
import { LayoutBody } from '@/layout/LayoutBody';
import { isApiError } from '@/lib/fetcher';
import {
  createDiagram,
  deleteDiagram,
  getDiagram,
  listDiagrams,
  type SavedDiagram,
  type SavedDiagramSummary,
  updateDiagram,
} from './api';
import { DrawioFrame, type DrawioFrameHandle, type DrawioLoad } from './DrawioFrame';
import { BLANK_DRAWIO_XML, xmlLooksConverted } from './drawio';
import { generateMermaidDraft } from './generateDraft';

const formatWhen = (value: string) => {
  const date = new Date(Number(value));
  if (Number.isNaN(date.getTime())) return '';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
};

const errorText = (error: unknown, fallback: string) => {
  if (isApiError(error)) {
    const data = error.data;
    if (data && typeof data === 'object') {
      if ('message' in data && typeof data.message === 'string') return data.message;
      if ('error' in data && typeof data.error === 'string') return data.error;
    }
  }
  if (error instanceof Error && error.message) return error.message;
  return fallback;
};

const toSummary = (diagram: SavedDiagram): SavedDiagramSummary => ({
  diagramId: diagram.diagramId,
  title: diagram.title,
  createdDate: diagram.createdDate,
  updatedDate: diagram.updatedDate,
});

const isDiagramType = (value: string): value is DiagramType => value in DIAGRAM_DATA;

const mainTypeOptions = Object.values(DIAGRAM_DATA).filter((item) => item.category === 'main');
const otherTypeOptions = Object.values(DIAGRAM_DATA).filter((item) => item.category === 'other');

const copyTitle = (title: string, titles: string[]) => {
  const base = `${title} のコピー`;
  if (!titles.includes(base)) return base;
  let n = 2;
  while (titles.includes(`${base} (${n})`)) n += 1;
  return `${base} (${n})`;
};

type Pane = 'list' | 'draft' | 'edit';

export const DiagramWorkspacePage = () => {
  const { documentTitle, title, description } = useRegisteredAppMeta(
    COMMON_EXAPPS_TEAM_ID,
    'diagram',
    'ダイアグラムを生成',
    '文章から図の下書きを作り、draw.io で編集して画像にします。',
  );
  const { predict } = useChatApi();
  const { selectedModelId } = useSelectedModel();
  const frameRef = useRef<DrawioFrameHandle>(null);
  const nonceRef = useRef(0);
  const saveTimer = useRef<number | null>(null);
  const instructionSaveSeq = useRef(0);
  const currentIdRef = useRef<string | null>(null);
  const generateTargetRef = useRef<{
    id: string;
    instruction: string;
    diagramType: DiagramType;
    mermaid: string;
  } | null>(null);

  const [pane, setPane] = useState<Pane>('list');
  const [helpOpen, setHelpOpen] = useState(false);
  const [diagrams, setDiagrams] = useState<SavedDiagramSummary[]>([]);
  const [listTitles, setListTitles] = useState<Record<string, string>>({});
  const [newName, setNewName] = useState('');
  const [current, setCurrent] = useState<SavedDiagram | null>(null);
  const [instruction, setInstruction] = useState('');
  const [diagramType, setDiagramType] = useState<DiagramType>('flowchart');
  const [load, setLoad] = useState<DrawioLoad | null>(null);
  const [listError, setListError] = useState('');
  const [notice, setNotice] = useState('');
  const [saveState, setSaveState] = useState('');
  const [generating, setGenerating] = useState(false);
  const [busy, setBusy] = useState(false);

  currentIdRef.current = current?.diagramId ?? null;

  useEffect(() => {
    if (pane !== 'edit') return;
    const id = window.requestAnimationFrame(() => {
      window.dispatchEvent(new Event('resize'));
    });
    return () => window.cancelAnimationFrame(id);
  }, [pane]);

  useEffect(() => {
    listDiagrams()
      .then(setDiagrams)
      .catch((error: unknown) => {
        setListError(errorText(error, '図の一覧を読み込めませんでした'));
      });
    return () => {
      if (saveTimer.current) window.clearTimeout(saveTimer.current);
    };
  }, []);

  const paneFor = (diagram: SavedDiagram): Pane =>
    xmlLooksConverted(diagram.drawioXml || '') ? 'edit' : 'draft';

  const showDiagram = (diagram: SavedDiagram, nextPane: Pane) => {
    nonceRef.current += 1;
    setCurrent(diagram);
    setInstruction(diagram.instruction || '');
    setDiagramType(isDiagramType(diagram.diagramType) ? diagram.diagramType : 'flowchart');
    setLoad({
      nonce: nonceRef.current,
      kind: 'xml',
      xml: diagram.drawioXml || BLANK_DRAWIO_XML,
    });
    setSaveState('');
    setNotice('');
    setPane(nextPane);
  };

  const openSaved = async (diagramId: string) => {
    setBusy(true);
    try {
      const diagram = await getDiagram(diagramId);
      showDiagram(diagram, paneFor(diagram));
    } catch (error: unknown) {
      setNotice(errorText(error, '図を開けませんでした'));
    } finally {
      setBusy(false);
    }
  };

  const createNamed = async () => {
    const title = newName.trim();
    if (!title) return;
    setBusy(true);
    setNotice('');
    try {
      const diagram = await createDiagram({
        title,
        instruction: '',
        diagramType: 'flowchart',
        drawioXml: BLANK_DRAWIO_XML,
      });
      setDiagrams((prev) => [toSummary(diagram), ...prev]);
      setNewName('');
      showDiagram(diagram, 'draft');
    } catch (error: unknown) {
      setNotice(errorText(error, '図を作成できませんでした'));
    } finally {
      setBusy(false);
    }
  };

  const duplicate = async (diagramId: string) => {
    setBusy(true);
    setNotice('');
    try {
      const source = await getDiagram(diagramId);
      const diagram = await createDiagram({
        title: copyTitle(
          source.title,
          diagrams.map((item) => item.title),
        ),
        instruction: source.instruction,
        diagramType: isDiagramType(source.diagramType) ? source.diagramType : 'flowchart',
        mermaidSource: source.mermaidSource,
        drawioXml: source.drawioXml || BLANK_DRAWIO_XML,
      });
      setDiagrams((prev) => [toSummary(diagram), ...prev]);
      showDiagram(diagram, paneFor(diagram));
    } catch (error: unknown) {
      setNotice(errorText(error, '図を複製できませんでした'));
    } finally {
      setBusy(false);
    }
  };

  const commitListTitle = async (diagramId: string, stored: string) => {
    const next = (listTitles[diagramId] ?? stored).trim();
    if (!next || next === stored) {
      setListTitles((prev) => ({ ...prev, [diagramId]: stored }));
      return;
    }
    try {
      const diagram = await updateDiagram(diagramId, { title: next });
      setDiagrams((prev) =>
        prev.map((item) => (item.diagramId === diagramId ? toSummary(diagram) : item)),
      );
      setListTitles((prev) => ({ ...prev, [diagramId]: diagram.title }));
      if (current?.diagramId === diagramId) setCurrent(diagram);
    } catch (error: unknown) {
      setNotice(errorText(error, '名前を保存できませんでした'));
      setListTitles((prev) => ({ ...prev, [diagramId]: stored }));
    }
  };

  const persistInstruction = async (next: string) => {
    if (!current || next === current.instruction) return;
    const seq = ++instructionSaveSeq.current;
    const diagramId = current.diagramId;
    const previous = current.instruction;
    try {
      const diagram = await updateDiagram(diagramId, { instruction: next });
      if (instructionSaveSeq.current !== seq) return;
      setCurrent(diagram);
      setDiagrams((prev) =>
        prev.map((item) => (item.diagramId === diagram.diagramId ? toSummary(diagram) : item)),
      );
    } catch (error: unknown) {
      if (instructionSaveSeq.current !== seq) return;
      setNotice(errorText(error, '下書きの文章を保存できませんでした'));
      setInstruction(previous);
    }
  };

  const commitInstruction = () => {
    void persistInstruction(instruction);
  };

  const applySample = () => {
    const sample = DIAGRAM_DATA[diagramType].example.content;
    setInstruction(sample);
    void persistInstruction(sample);
  };

  const changeType = async (next: DiagramType) => {
    setDiagramType(next);
    if (!current || next === current.diagramType) return;
    try {
      const diagram = await updateDiagram(current.diagramId, { diagramType: next });
      setCurrent(diagram);
    } catch (error: unknown) {
      setNotice(errorText(error, '図の種類を保存できませんでした'));
      setDiagramType(isDiagramType(current.diagramType) ? current.diagramType : 'flowchart');
    }
  };

  const onGenerate = async () => {
    if (!current || generating) return;
    const text = instruction.trim();
    if (!text) {
      setNotice('下書きの文章を入力してください');
      return;
    }
    if (
      xmlLooksConverted(current.drawioXml) &&
      !window.confirm('この文章から下書きを作り直し、今の図を置き換えます。')
    ) {
      return;
    }
    setGenerating(true);
    setNotice('');
    try {
      const mermaid = await generateMermaidDraft({
        content: text,
        type: diagramType,
        modelId: selectedModelId,
        predict,
      });
      generateTargetRef.current = {
        id: current.diagramId,
        instruction: text,
        diagramType,
        mermaid,
      };
      nonceRef.current += 1;
      setPane('edit');
      setLoad({ nonce: nonceRef.current, kind: 'mermaid', mermaid });
      setSaveState('図形に変換しています');
    } catch (error: unknown) {
      setNotice(errorText(error, '下書きの生成に失敗しました'));
    } finally {
      setGenerating(false);
    }
  };

  const onConverted = async (xml: string) => {
    const target = generateTargetRef.current;
    generateTargetRef.current = null;
    if (!target) return;
    try {
      const diagram = await updateDiagram(target.id, {
        instruction: target.instruction,
        diagramType: target.diagramType,
        mermaidSource: target.mermaid,
        drawioXml: xml,
      });
      setDiagrams((prev) =>
        [toSummary(diagram), ...prev.filter((item) => item.diagramId !== target.id)].sort(
          (a, b) => Number(b.updatedDate) - Number(a.updatedDate),
        ),
      );
      if (currentIdRef.current === target.id) {
        setCurrent(diagram);
        setLoad((prev) => (prev ? { nonce: prev.nonce, kind: 'xml', xml } : prev));
        setSaveState('保存しました');
        setNotice('');
      }
    } catch (error: unknown) {
      setNotice(errorText(error, '変換できましたが、保存に失敗しました'));
      setSaveState('');
      if (currentIdRef.current === target.id) restoreSavedDrawing();
    }
  };

  const onAutosave = (xml: string) => {
    const diagramId = currentIdRef.current;
    if (!diagramId) return;
    if (saveTimer.current) window.clearTimeout(saveTimer.current);
    setSaveState('保存待ち');
    saveTimer.current = window.setTimeout(() => {
      setSaveState('保存中');
      updateDiagram(diagramId, { drawioXml: xml })
        .then((diagram) => {
          if (currentIdRef.current !== diagramId) return;
          setCurrent(diagram);
          setDiagrams((prev) =>
            [toSummary(diagram), ...prev.filter((item) => item.diagramId !== diagramId)].sort(
              (a, b) => Number(b.updatedDate) - Number(a.updatedDate),
            ),
          );
          setSaveState('保存しました');
        })
        .catch((error: unknown) => {
          setSaveState(errorText(error, '保存に失敗しました'));
        });
    }, 1500);
  };

  const remove = async (diagramId: string, title: string) => {
    if (!window.confirm(`「${title}」を削除しますか？`)) return;
    try {
      await deleteDiagram(diagramId);
      setDiagrams((prev) => prev.filter((item) => item.diagramId !== diagramId));
      if (current?.diagramId === diagramId) {
        setCurrent(null);
        setLoad(null);
        setInstruction('');
        setSaveState('');
        setPane('list');
      }
    } catch (error: unknown) {
      setNotice(errorText(error, '削除できませんでした'));
    }
  };

  const restoreSavedDrawing = () => {
    if (!current) return;
    nonceRef.current += 1;
    setLoad({
      nonce: nonceRef.current,
      kind: 'xml',
      xml: current.drawioXml || BLANK_DRAWIO_XML,
    });
  };

  return (
    <LayoutBody>
      <PageTitle title={documentTitle} />
      <div
        className={
          pane === 'edit'
            ? 'mx-auto flex h-[calc(100dvh-var(--header-height))] w-full max-w-(--page-width) flex-col gap-2 overflow-hidden px-4 py-2 lg:px-6'
            : 'mx-auto flex w-full max-w-(--page-width) flex-col gap-3 p-4 lg:p-6'
        }
      >
        {pane === 'edit' ? (
          <div className='flex min-w-0 items-baseline gap-3'>
            <h1 className='shrink-0 text-std-16B-170 text-solid-gray-900'>{title}</h1>
            {description && (
              <p className='truncate text-dns-14N-130 text-solid-gray-600' title={description}>
                {description}
              </p>
            )}
          </div>
        ) : (
          <ManagedAppHeader
            teamId={COMMON_EXAPPS_TEAM_ID}
            exAppId='diagram'
            fallbackTitle='ダイアグラムを生成'
            fallbackDescription='文章から図の下書きを作り、draw.io で編集して画像にします。'
            hideHowTo={true}
          />
        )}

        <div className='flex flex-wrap items-center justify-between gap-2'>
          <div className='flex flex-wrap gap-1 overflow-x-auto border-b border-solid-gray-300'>
            {(
              [
                ['list', '図一覧'],
                ['draft', '下書き'],
                ['edit', '編集'],
              ] as const
            ).map(([id, label]) => (
              <button
                key={id}
                type='button'
                onClick={() => setPane(id)}
                className={
                  pane === id
                    ? 'whitespace-nowrap border-b-2 border-blue-900 px-3 py-2 text-std-16B-150 text-blue-900'
                    : 'whitespace-nowrap px-3 py-2 text-std-16N-170 text-solid-gray-700 hover:text-blue-900'
                }
              >
                {label}
              </button>
            ))}
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

        {notice && pane === 'list' && (
          <p className='text-error-2' role='alert'>
            {notice}
          </p>
        )}

        {pane === 'list' && (
          <section className='flex flex-col gap-3'>
            <div className='flex flex-wrap items-end justify-between gap-2'>
              <h2 className='text-std-18B-160 text-solid-gray-900'>図一覧</h2>
              <div className='flex flex-wrap items-end gap-2'>
                <label className='flex flex-col gap-1 text-dns-14N-130 text-solid-gray-700'>
                  新規の図の名前
                  <Input
                    blockSize='sm'
                    value={newName}
                    onChange={(event) => setNewName(event.target.value)}
                    className='w-64'
                  />
                </label>
                <Button
                  type='button'
                  variant='solid-fill'
                  size='sm'
                  aria-disabled={busy || !newName.trim() || undefined}
                  onClick={() => {
                    if (busy || !newName.trim()) return;
                    void createNamed();
                  }}
                >
                  <span className='inline-flex items-center gap-1 whitespace-nowrap'>
                    <PiFilePlus className='size-4' aria-hidden={true} />
                    作成
                  </span>
                </Button>
              </div>
            </div>
            {listError && (
              <p className='text-dns-14N-130 text-error-2' role='alert'>
                {listError}
              </p>
            )}
            <div className='overflow-x-auto rounded-8 border border-solid-gray-300'>
              <table className='w-full min-w-[56rem] border-collapse text-dns-14N-130'>
                <thead>
                  <tr className='border-b border-solid-gray-300 bg-solid-gray-50 text-left text-solid-gray-600'>
                    <th className='w-3/5 min-w-[32rem] px-3 py-2'>図の名前</th>
                    <th className='px-3 py-2'>更新</th>
                    <th className='px-3 py-2 text-right'>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {diagrams.length === 0 ? (
                    <tr>
                      <td colSpan={3} className='px-3 py-6 text-center text-solid-gray-500'>
                        図がありません。右上から新規作成してください。
                      </td>
                    </tr>
                  ) : (
                    diagrams.map((item) => (
                      <tr key={item.diagramId} className='border-b border-solid-gray-200'>
                        <td className='w-3/5 min-w-[32rem] px-3 py-2'>
                          <Input
                            blockSize='sm'
                            className='w-full min-w-0'
                            aria-label='図の名前'
                            value={listTitles[item.diagramId] ?? item.title}
                            onChange={(event) =>
                              setListTitles((prev) => ({
                                ...prev,
                                [item.diagramId]: event.target.value,
                              }))
                            }
                            onBlur={() => void commitListTitle(item.diagramId, item.title)}
                          />
                        </td>
                        <td className='px-3 py-2 text-solid-gray-600'>
                          {formatWhen(item.updatedDate)}
                        </td>
                        <td className='px-3 py-2 text-right'>
                          <div className='inline-flex gap-2'>
                            <Button
                              type='button'
                              variant='solid-fill'
                              size='xs'
                              onClick={() => void openSaved(item.diagramId)}
                            >
                              開く
                            </Button>
                            <Button
                              type='button'
                              variant='outline'
                              size='xs'
                              className='inline-flex items-center gap-1'
                              onClick={() => void duplicate(item.diagramId)}
                            >
                              <PiCopySimple aria-hidden={true} className='size-3.5' />
                              複製
                            </Button>
                            <Button
                              type='button'
                              variant='outline'
                              size='xs'
                              onClick={() => void remove(item.diagramId, item.title)}
                            >
                              削除
                            </Button>
                          </div>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {(pane === 'draft' || pane === 'edit') && !current && (
          <div className='rounded-8 border border-solid-gray-300 bg-solid-gray-50 p-6 text-std-16N-170 text-solid-gray-600'>
            「図一覧」タブから図を開いてください。
          </div>
        )}

        {pane === 'draft' && current && (
          <section className='flex flex-col gap-3'>
            {notice && (
              <p className='text-error-2' role='alert'>
                {notice}
              </p>
            )}
            <p className='text-dns-14N-130 text-solid-gray-600'>
              {`「${current.title}」の下書きです。文章を書き換えても、図はまだ変わりません。`}
            </p>
            <fieldset>
              <Legend size='lg' className='mb-1'>
                図の種類を選択
                <span className='font-normal'>（{DIAGRAM_DATA[diagramType].title}を選択中）</span>
              </Legend>
              <div className='grid grid-cols-[repeat(auto-fit,minmax(calc(180/16*1rem),1fr))] gap-2'>
                {mainTypeOptions.map((option) => (
                  <DiagramTypeButton
                    key={option.id}
                    option={option}
                    isSelected={diagramType === option.id}
                    onChange={(type) => void changeType(type)}
                    hasError={false}
                  />
                ))}
              </div>
              <Disclosure className='mt-3'>
                <DisclosureSummary>他の図の種類を見る</DisclosureSummary>
                <div className='mt-3 grid grid-cols-[repeat(auto-fit,minmax(calc(180/16*1rem),1fr))] gap-2 pb-2'>
                  {otherTypeOptions.map((option) => (
                    <DiagramTypeButton
                      key={option.id}
                      option={option}
                      isSelected={diagramType === option.id}
                      onChange={(type) => void changeType(type)}
                      hasError={false}
                    />
                  ))}
                </div>
              </Disclosure>
            </fieldset>
            <div className='flex flex-col gap-1.5'>
              <Label htmlFor='diagram-instruction' size='lg'>
                下書きの文章
              </Label>
              <button
                type='button'
                className={`mb-1 w-fit ${linkDefaultStyle} ${linkHoverStyle} ${linkFocusStyle} ${linkActiveStyle}`}
                onClick={applySample}
              >
                {DIAGRAM_DATA[diagramType].example.title}を入力する
              </button>
              <Textarea
                id='diagram-instruction'
                rows={8}
                value={instruction}
                onChange={(event) => setInstruction(event.target.value)}
                onBlur={commitInstruction}
              />
            </div>
            <ModelSelector />
            <div className='flex justify-center'>
              <Button
                type='button'
                variant='solid-fill'
                size='lg'
                className='w-60'
                aria-disabled={generating || !instruction.trim() || undefined}
                onClick={() => {
                  if (generating || !instruction.trim()) return;
                  void onGenerate();
                }}
              >
                {generating ? '作成中...' : 'この文章で下書きを作る'}
              </Button>
            </div>
          </section>
        )}

        {pane === 'edit' && current && (
          <section className='flex items-center justify-between gap-3'>
            <h2 className='min-w-0 truncate text-std-18B-160 text-solid-gray-900'>
              {current.title}
            </h2>
            <div className='flex shrink-0 items-center gap-2'>
              <Button
                type='button'
                variant='outline'
                size='sm'
                aria-disabled={!load}
                onClick={() => frameRef.current?.exportImage('png', current.title || '図')}
              >
                PNG
              </Button>
              <Button
                type='button'
                variant='outline'
                size='sm'
                aria-disabled={!load}
                onClick={() => frameRef.current?.exportImage('svg', current.title || '図')}
              >
                SVG
              </Button>
              {saveState && (
                <span className='text-dns-14N-130 text-solid-gray-600'>{saveState}</span>
              )}
            </div>
          </section>
        )}

        {pane === 'edit' && current && notice && (
          <p className='text-error-2' role='alert'>
            {notice}
          </p>
        )}

        {current && load && (
          <div
            className={
              pane === 'edit'
                ? 'min-h-0 flex-1 overflow-hidden rounded-8 border border-solid-gray-300 bg-solid-gray-50'
                : 'pointer-events-none fixed top-0 left-[-10000px] h-[calc(100dvh-var(--header-height)-8rem)] w-[min(100vw,80rem)] overflow-hidden'
            }
            aria-hidden={pane !== 'edit'}
          >
            <DrawioFrame
              ref={frameRef}
              load={load}
              onConverted={(xml) => void onConverted(xml)}
              onConvertError={(message) => {
                generateTargetRef.current = null;
                setNotice(message);
                setSaveState('');
                restoreSavedDrawing();
              }}
              onAutosave={onAutosave}
            />
          </div>
        )}
      </div>

      <CustomDialog isOpen={helpOpen} onClose={() => setHelpOpen(false)}>
        <CustomDialogPanel>
          <CustomDialogHeader hasClose onClose={() => setHelpOpen(false)}>
            使い方
          </CustomDialogHeader>
          <CustomDialogBody>
            <div className='space-y-3 text-std-16N-170 text-solid-gray-800'>
              <p>
                図一覧で名前を付けて作成すると、下書きタブが開きます。名前の変更、複製、削除も一覧で行います。図がまだ無いときは「開く」も下書きを開きます。
              </p>
              <p>
                「下書き」タブで図の種類を選び、サンプルを文章欄へ入れられます。文章を書き換えても図はまだ変わりません。「この文章で下書きを作る」を押すと、その文章から図を作り直して「編集」タブに移ります。
              </p>
              <p>
                複製は、図と下書きの文章をコピーした新しい行を作ります。文章を直してから、あらためて下書きを作れます。元の図はそのまま残ります。
              </p>
              <p>できた図は draw.io で動かせます。PNG と SVG で書き出せます。</p>
            </div>
          </CustomDialogBody>
        </CustomDialogPanel>
      </CustomDialog>
    </LayoutBody>
  );
};
