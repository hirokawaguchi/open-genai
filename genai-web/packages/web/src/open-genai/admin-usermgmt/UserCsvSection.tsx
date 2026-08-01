import { useRef, useState } from 'react';
import {
  CustomDialog,
  CustomDialogBody,
  CustomDialogHeader,
  CustomDialogPanel,
} from '@/components/ui/CustomDialog';
import { Button } from '@/components/ui/dads/Button';
import { ErrorText } from '@/components/ui/dads/ErrorText';
import { Label } from '@/components/ui/dads/Label';
import { SupportText } from '@/components/ui/dads/SupportText';
import { Textarea } from '@/components/ui/dads/Textarea';
import { useUserMgmtActions } from './useUserMgmt';
import type { ApplyResult, PlanRow } from './types';

const ACTION_LABEL: Record<string, string> = {
  create: '作成',
  update: '更新',
  delete: '削除',
  upsert: '作成/更新',
};

const actionLabel = (action: string): string => ACTION_LABEL[action] ?? action;

const CSV_SAMPLE = `action,username,email,name,password,groups,enabled
upsert,yamada,yamada@example.com,山田太郎,Passw0rd!,UserGroup,true`;

type Props = {
  onApplied: () => void;
};

/** 「CSV一括処理」: 貼り付け／ファイルからドライラン→適用（確認ダイアログ）まで。 */
export const UserCsvSection = ({ onApplied }: Props) => {
  const { plan, apply, submitting, error, setError } = useUserMgmtActions();
  const [csvText, setCsvText] = useState('');
  const [planRows, setPlanRows] = useState<PlanRow[] | null>(null);
  const [applyResults, setApplyResults] = useState<ApplyResult[] | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const resetOutputs = () => {
    setPlanRows(null);
    setApplyResults(null);
  };

  const handleFile = async (file: File | undefined) => {
    if (!file) {
      return;
    }
    const text = await file.text();
    setCsvText(text);
    resetOutputs();
    setError(null);
  };

  const handleDryRun = async () => {
    resetOutputs();
    const res = await plan(csvText);
    if (res) {
      setPlanRows(res.rows);
    }
  };

  const handleApply = async () => {
    setConfirmOpen(false);
    setApplyResults(null);
    const res = await apply(csvText);
    if (res) {
      setApplyResults(res.results);
      setPlanRows(null);
      onApplied();
    }
  };

  const planErrorCount = planRows?.filter((r) => r.error).length ?? 0;

  return (
    <div className='flex flex-col gap-5'>
      <div className='flex flex-col gap-1.5'>
        <Label htmlFor='csv-text' size='sm'>
          CSV（貼り付け）
        </Label>
        <SupportText>
          見出し: action, username, email, firstName, lastName, name, password, groups, enabled。
          action は create / update / delete / upsert（既定 upsert）。
        </SupportText>
        <Textarea
          id='csv-text'
          rows={8}
          value={csvText}
          placeholder={CSV_SAMPLE}
          onChange={(e) => {
            setCsvText(e.target.value);
            resetOutputs();
          }}
          className='font-mono'
        />
      </div>

      <div className='flex flex-col gap-1.5'>
        <Label htmlFor='csv-file' size='sm'>
          CSV ファイル（貼り付けの代わりに読み込み）
        </Label>
        <input
          id='csv-file'
          ref={fileRef}
          type='file'
          accept='.csv,.txt'
          onChange={(e) => handleFile(e.target.files?.[0])}
          className='text-std-16N-170 text-solid-gray-800'
        />
      </div>

      {error && <ErrorText>＊{error}</ErrorText>}

      <div className='flex flex-wrap items-center gap-3'>
        <Button
          type='button'
          variant='outline'
          size='md'
          onClick={handleDryRun}
          aria-disabled={submitting || !csvText.trim() || undefined}
        >
          {submitting ? '処理中...' : 'ドライラン（変更しない）'}
        </Button>
        <Button
          type='button'
          variant='solid-fill'
          size='md'
          onClick={() => setConfirmOpen(true)}
          aria-disabled={submitting || !csvText.trim() || undefined}
        >
          適用（Keycloak に反映）
        </Button>
      </div>

      {planRows && (
        <div className='flex flex-col gap-2'>
          <h3 className='text-std-16B-150'>ドライラン結果（変更なし）</h3>
          <SupportText>
            {planRows.length} 件中、エラー {planErrorCount} 件。問題なければ「適用」を実行してください。
          </SupportText>
          <ResultTable
            headers={['#', 'username', '操作', 'groups', '判定']}
            rows={planRows.map((r, i) => [
              String(i + 1),
              r.username || '-',
              actionLabel(r.action),
              r.groups.join(', ') || '-',
              r.error ? `エラー: ${r.error}` : '実行予定',
            ])}
            errorRow={(i) => !!planRows[i].error}
          />
        </div>
      )}

      {applyResults && (
        <div className='flex flex-col gap-2'>
          <h3 className='text-std-16B-150'>適用結果</h3>
          <ResultTable
            headers={['#', 'username', '操作', '結果', '備考']}
            rows={applyResults.map((r, i) => [
              String(i + 1),
              r.username || '-',
              actionLabel(r.action),
              r.result,
              r.note || '-',
            ])}
            errorRow={(i) => applyResults[i].result === 'エラー'}
          />
        </div>
      )}

      <CustomDialog isOpen={confirmOpen} onClose={() => setConfirmOpen(false)}>
        <CustomDialogPanel>
          <CustomDialogHeader hasClose onClose={() => setConfirmOpen(false)}>
            CSV を Keycloak に反映
          </CustomDialogHeader>
          <CustomDialogBody>
            <p className='text-std-16N-170 text-solid-gray-800'>
              CSV の内容を Keycloak に反映します（利用者の作成・更新・削除を含む）。削除は元に戻せません。ドライランで確認済みですか？
            </p>
            <div className='mt-6 flex justify-end gap-3'>
              <Button
                type='button'
                variant='outline'
                size='md'
                onClick={() => setConfirmOpen(false)}
              >
                キャンセル
              </Button>
              <Button
                type='button'
                variant='solid-fill'
                size='md'
                onClick={handleApply}
                aria-disabled={submitting || undefined}
              >
                {submitting ? '適用中...' : '適用する'}
              </Button>
            </div>
          </CustomDialogBody>
        </CustomDialogPanel>
      </CustomDialog>
    </div>
  );
};

type TableProps = {
  headers: string[];
  rows: string[][];
  errorRow?: (index: number) => boolean;
};

const ResultTable = ({ headers, rows, errorRow }: TableProps) => (
  <div className='overflow-x-auto rounded-8 border border-solid-gray-300'>
    <table className='w-full border-collapse text-left text-dns-14N-130'>
      <thead className='bg-solid-gray-50 text-solid-gray-700'>
        <tr>
          {headers.map((h) => (
            <th key={h} className='whitespace-nowrap px-3 py-2 font-bold'>
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody className='divide-y divide-solid-gray-300'>
        {rows.map((cols, i) => (
          <tr
            // 行の並びは固定でインデックスが安定するため index キーで十分。
            key={i}
            className={errorRow?.(i) ? 'text-error-1' : 'text-solid-gray-900'}
          >
            {cols.map((c, j) => (
              <td key={j} className='px-3 py-2 align-top'>
                {c}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);
