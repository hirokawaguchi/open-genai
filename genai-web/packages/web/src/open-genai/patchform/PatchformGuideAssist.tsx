import { useState } from 'react';
import { Button } from '@/components/ui/dads/Button';
import { FilePickButton } from './runtime/FilePickButton';
import type { AssistProcedurePreview, AssistProcedureResult, FormVisibility } from './types';

type Props = {
  model?: string;
  readingFile: boolean;
  guideFileName: string;
  guideText: string;
  busy: boolean;
  error: string | null;
  setError: (msg: string | null) => void;
  onPickFile: (file: File | null) => void;
  previewProcedure: (input: {
    text: string;
    visibility?: FormVisibility;
  }) => Promise<AssistProcedurePreview | null>;
  applyProcedureDraft: (input: {
    draft: Record<string, unknown>;
    apply: { forms?: boolean; navigation?: boolean; notice?: boolean };
    form_keys?: string[];
    visibility?: FormVisibility;
  }) => Promise<AssistProcedureResult | null>;
  onApplied: (result: AssistProcedureResult) => void;
};

export const PatchformGuideAssist = ({
  model,
  readingFile,
  guideFileName,
  guideText,
  busy,
  error,
  setError,
  onPickFile,
  previewProcedure,
  applyProcedureDraft,
  onApplied,
}: Props) => {
  const [preview, setPreview] = useState<AssistProcedurePreview | null>(null);
  const [applyForms, setApplyForms] = useState(false);
  const [applyNav, setApplyNav] = useState(false);
  const [applyNotice, setApplyNotice] = useState(false);
  const [formKeys, setFormKeys] = useState<string[]>([]);

  const resetPreview = () => {
    setPreview(null);
    setApplyForms(false);
    setApplyNav(false);
    setApplyNotice(false);
    setFormKeys([]);
  };

  const onPreview = async () => {
    setError(null);
    if (!guideText.trim()) {
      setError('手引きのファイルを選んでください。');
      return;
    }
    const res = await previewProcedure({ text: guideText.trim(), visibility: 'internal' });
    if (!res) return;
    const navFound = res.preview.navigation.found;
    const forms = res.preview.forms;
    const weakName = !res.preview.name || res.preview.name === '手続き（仮）';
    setPreview(res);
    setApplyForms(forms.length > 0);
    setApplyNav(navFound);
    setApplyNotice((navFound || forms.length > 0) && !weakName);
    setFormKeys(forms.map((f) => f.key).filter(Boolean));
  };

  const onApply = async () => {
    if (!preview) return;
    setError(null);
    if (!applyForms && !applyNav && !applyNotice) {
      setError('反映するものを1つ以上選んでください。');
      return;
    }
    const res = await applyProcedureDraft({
      draft: preview.draft,
      apply: { forms: applyForms, navigation: applyNav, notice: applyNotice },
      form_keys: applyForms ? formKeys : [],
      visibility: 'internal',
    });
    if (res) onApplied(res);
  };

  const toggleFormKey = (key: string, checked: boolean) => {
    setFormKeys((prev) => (checked ? [...prev, key] : prev.filter((k) => k !== key)));
  };

  const selectedCount = [applyForms, applyNav, applyNotice].filter(Boolean).length;
  const canApply = selectedCount > 0 && (!applyForms || formKeys.length > 0);

  return (
    <div id='pf-proc-ai' className='rounded-8 border border-solid-gray-300 bg-solid-gray-50 px-4 py-4'>
      <h3 className='text-std-16B-150'>手引きファイルで候補を出す（任意）</h3>
      <p className='mt-1 text-dns-16N-130 text-solid-gray-700'>
        手引きは手続きを一度に完成させるものではありません。読み取れた様式・手続きの選択肢・案内から、反映するものを選んでください。公開はしません。
      </p>
      <div className='mt-4'>
        <FilePickButton
          id='pf-proc-guide-file'
          accept='.txt,.md,.pdf,.docx,.doc,.xlsx,.xls,.pptx,.ppt,.csv,.html,text/plain,text/markdown,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.openxmlformats-officedocument.presentationml.presentation'
          disabled={readingFile || busy}
          busy={readingFile}
          busyLabel='読み取り中...'
          filename={guideFileName}
          buttonLabel='手引きファイルを選ぶ'
          onFile={(file) => {
            resetPreview();
            onPickFile(file);
          }}
        />
        <p className='mt-1 text-dns-14N-130 text-solid-gray-600'>
          txt / md / pdf / Word（docx） / Excel（xlsx）を選べます。古い Word（doc）や PowerPoint、スキャン画像だけの PDF は読めません。
        </p>
        {guideText.trim() ? (
          <p className='mt-2 text-dns-16N-130 text-solid-gray-700'>
            ファイルを読み込みました（{guideText.trim().length.toLocaleString('ja-JP')}文字）。下のボタンで候補を出せます。
          </p>
        ) : null}
      </div>
      <p className='mt-3 text-dns-14N-130 text-solid-gray-600'>
        候補の作成に使います: {model || '（未設定）'}。うまく作れないときはひな型を使います。
      </p>
      {error ? (
        <p className='mt-2 text-error-1' role='alert'>
          {error}
        </p>
      ) : null}
      <div className='mt-4'>
        <Button
          type='button'
          variant='outline'
          size='md'
          aria-disabled={busy || readingFile || !guideText.trim()}
          onClick={() => void onPreview()}
        >
          {busy && !preview ? '読み取り中...' : '読み取った候補を見る'}
        </Button>
      </div>

      {preview ? (
        <div className='mt-4 flex flex-col gap-4 rounded-8 border border-solid-gray-420 bg-white px-4 py-4'>
          <div>
            <p className='text-std-16B-150'>読み取れた候補</p>
            <p className='mt-1 text-dns-14N-130 text-solid-gray-600'>
              {preview.source === 'template'
                ? 'ひな型からの候補です。文書に無いものは外してください。'
                : 'AI が文書から拾った候補です。必要なものだけ選んでください。'}
              {preview.notes ? ` ${preview.notes}` : ''}
            </p>
          </div>
          {preview.preview.outline?.read?.length ? (
            <p className='text-dns-14N-130 text-solid-gray-700'>
              目次から{preview.preview.outline.chapter_count}章を切り、
              {preview.preview.outline.read
                .map((ch) => `「${ch.title || ch.id}」`)
                .join('、')}
              を読みました。
            </p>
          ) : null}
          {preview.preview.warnings.length > 0 ? (
            <ul className='list-disc pl-5 text-dns-16N-130 text-solid-gray-700'>
              {preview.preview.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          ) : null}

          <fieldset>
            <legend className='text-std-16B-150'>反映するもの</legend>
            <div className='mt-2 flex flex-col gap-3'>
              <label className='flex items-start gap-2 text-std-16N-170'>
                <input
                  type='checkbox'
                  className='mt-1'
                  checked={applyForms}
                  disabled={preview.preview.forms.length === 0}
                  onChange={(e) => {
                    const checked = e.target.checked;
                    setApplyForms(checked);
                    if (!checked && !applyNav) setApplyNotice(false);
                  }}
                />
                <span>
                  様式（フォーム）
                  <span className='mt-0.5 block text-dns-14N-130 text-solid-gray-600'>
                    {preview.preview.forms.length
                      ? preview.preview.forms.every((f) => f.title_only)
                        ? '様式名だけの下書きです。中身はあとから足してください。'
                        : '申請用紙の下書きを作ります。あとから部品を直せます。'
                      : 'この文書からは様式を読み取れませんでした。'}
                  </span>
                </span>
              </label>
              {applyForms && preview.preview.forms.length > 0 ? (
                <ul className='ml-6 flex flex-col gap-1'>
                  {preview.preview.forms.map((form) => (
                    <li key={form.key}>
                      <label className='flex items-start gap-2 text-dns-16N-130'>
                        <input
                          type='checkbox'
                          className='mt-0.5'
                          checked={formKeys.includes(form.key)}
                          onChange={(e) => toggleFormKey(form.key, e.target.checked)}
                        />
                        <span>
                          {form.title}
                          <span className='text-solid-gray-600'>
                            {form.title_only || form.field_count === 0
                              ? '（題名のみ）'
                              : `（部品 ${form.field_count}）`}
                          </span>
                        </span>
                      </label>
                    </li>
                  ))}
                </ul>
              ) : null}

              <label className='flex items-start gap-2 text-std-16N-170'>
                <input
                  type='checkbox'
                  className='mt-1'
                  checked={applyNav}
                  disabled={!preview.preview.navigation.found}
                  onChange={(e) => {
                    const checked = e.target.checked;
                    setApplyNav(checked);
                    if (!checked && !applyForms) setApplyNotice(false);
                  }}
                />
                <span>
                  手続きの選択肢（ナビゲーションフォーム）
                  <span className='mt-0.5 block text-dns-14N-130 text-solid-gray-600'>
                    {preview.preview.navigation.found
                      ? preview.preview.navigation.questions
                          .map((q) => `${q.label}（${q.options.join(' / ') || '選択肢なし'}）`)
                          .join('、')
                      : '状況を聞く選択肢は読み取れていません。'}
                  </span>
                </span>
              </label>

              <label className='flex items-start gap-2 text-std-16N-170'>
                <input
                  type='checkbox'
                  className='mt-1'
                  checked={applyNotice}
                  disabled={!applyForms && !applyNav}
                  onChange={(e) => setApplyNotice(e.target.checked)}
                />
                <span>
                  手続きの案内
                  <span className='mt-0.5 block text-dns-14N-130 text-solid-gray-600'>
                    名前「{preview.preview.notice.name || '（未設定）'}」と、答えと用紙の対応を下書きします。
                    {preview.preview.notice.rule_count
                      ? ` 対応 ${preview.preview.notice.rule_count} 件。`
                      : ' 対応はまだありません。'}
                  </span>
                </span>
              </label>
            </div>
          </fieldset>

          <div>
            <Button
              type='button'
              variant='solid-fill'
              size='md'
              aria-disabled={busy || !canApply}
              onClick={() => void onApply()}
            >
              {busy ? '作成中...' : '選んだものを下書きする'}
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
};
